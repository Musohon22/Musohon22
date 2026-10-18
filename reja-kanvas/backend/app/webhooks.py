"""Outgoing webhooks: signed JSON POSTs when plans change, with retries.

Events are queued inside the request's transaction and delivered later, outside any database
transaction, so a slow receiver never blocks the app. Private network addresses are refused
(SSRF protection) unless REJA_WEBHOOK_ALLOW_PRIVATE=1 (for local development)."""

import hashlib
import hmac
import ipaddress
import json
import os
import secrets
import socket
import urllib.error
import urllib.request
import uuid
from datetime import timedelta
from urllib.parse import urlparse

from . import db, timeutil
from .errors import ApiError, not_found
from .plans import stamp

EVENT_FOR_KIND = {
    "created": "plan.created",
    "submitted": "plan.submitted",
    "completed": "plan.completed",
    "approved": "plan.completed",
    "returned": "plan.returned",
    "deleted": "plan.deleted",
}
MAX_HOOKS = 10
MAX_ATTEMPTS = 6
DISABLE_AFTER_FAILURES = 15


def _allow_private() -> bool:
    return os.environ.get("REJA_WEBHOOK_ALLOW_PRIVATE") == "1"


def check_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" and not (_allow_private() and parsed.scheme == "http"):
        raise ApiError(400, "webhook_https_only")
    if not parsed.hostname:
        raise ApiError(400, "webhook_bad_url")
    if _allow_private():
        return
    try:
        infos = socket.getaddrinfo(parsed.hostname, parsed.port or 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        raise ApiError(400, "webhook_unresolvable")
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
            raise ApiError(400, "webhook_private_address")


def create(conn, user_id: str, url: str, events: list[str]) -> dict:
    if conn.execute("SELECT COUNT(*) FROM webhooks WHERE user_id = ?", (user_id,)).fetchone()[0] >= MAX_HOOKS:
        raise ApiError(400, "too_many_webhooks", limit=MAX_HOOKS)
    check_url(url)
    hid = str(uuid.uuid4())
    secret = "whsec_" + secrets.token_urlsafe(24)
    conn.execute(
        "INSERT INTO webhooks(id, user_id, url, secret, events, created_at) VALUES (?,?,?,?,?,?)",
        (hid, user_id, url, secret, json.dumps(sorted(set(events))), stamp()),
    )
    # The signing secret is shown once.
    return {**_public(conn.execute("SELECT * FROM webhooks WHERE id = ?", (hid,)).fetchone()), "secret": secret}


def _public(row) -> dict:
    return {
        "id": row["id"], "url": row["url"], "events": json.loads(row["events"]), "active": bool(row["active"]),
        "failures": row["failures"], "last_status": row["last_status"], "created_at": row["created_at"],
    }


def list_for(conn, user_id: str) -> list[dict]:
    return [_public(r) for r in conn.execute("SELECT * FROM webhooks WHERE user_id = ? ORDER BY created_at", (user_id,))]


def delete(conn, user_id: str, hook_id: str) -> None:
    if not conn.execute("DELETE FROM webhooks WHERE id = ? AND user_id = ?", (hook_id, user_id)).rowcount:
        raise not_found("webhook")


def reactivate(conn, user_id: str, hook_id: str) -> dict:
    if not conn.execute("UPDATE webhooks SET active = 1, failures = 0 WHERE id = ? AND user_id = ?", (hook_id, user_id)).rowcount:
        raise not_found("webhook")
    return _public(conn.execute("SELECT * FROM webhooks WHERE id = ?", (hook_id,)).fetchone())


def enqueue(conn, user_id: str, event: str, payload: dict) -> int:
    hooks = conn.execute("SELECT id, events FROM webhooks WHERE user_id = ? AND active = 1", (user_id,)).fetchall()
    count = 0
    for hook in hooks:
        if event in json.loads(hook["events"]):
            body = json.dumps({"event": event, "sent_at": stamp(), "data": payload}, ensure_ascii=False)
            conn.execute(
                "INSERT INTO webhook_deliveries(webhook_id, event, payload, next_attempt_at, created_at) VALUES (?,?,?,?,?)",
                (hook["id"], event, body, stamp(), stamp()),
            )
            count += 1
    return count


def on_event(conn, plan_id: str, kind: str) -> None:
    """Called for every plan history event; queues the matching webhook event, if any."""
    event = EVENT_FOR_KIND.get(kind)
    if not event:
        return
    plan = conn.execute(
        "SELECT id, owner_id, title, status, due_at, priority, tag, completed_at FROM plans WHERE id = ?", (plan_id,)
    ).fetchone()
    if plan:
        enqueue(conn, plan["owner_id"], event, {k: plan[k] for k in plan.keys() if k != "owner_id"})


def sign(secret: str, body: bytes, timestamp: str) -> str:
    return hmac.new(secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256).hexdigest()


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):  # never follow redirects to somewhere else
        return None


def post(url: str, body: bytes, headers: dict) -> int:
    opener = urllib.request.build_opener(_NoRedirect)
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with opener.open(req, timeout=10) as res:
            return res.status
    except urllib.error.HTTPError as e:
        return e.code


def deliver_pending(limit: int = 50) -> int:
    """Sends due deliveries. Reads and writes in short transactions; network I/O happens between them."""
    now = stamp()
    with db.session() as conn:
        due = [
            dict(r)
            for r in conn.execute(
                """SELECT d.id, d.payload, d.event, d.attempts, w.id AS hook_id, w.url, w.secret FROM webhook_deliveries d
                   JOIN webhooks w ON w.id = d.webhook_id WHERE d.delivered_at IS NULL AND d.attempts < ?
                   AND d.next_attempt_at <= ? AND w.active = 1 ORDER BY d.id LIMIT ?""",
                (MAX_ATTEMPTS, now, limit),
            )
        ]
    sent = 0
    for d in due:
        body = d["payload"].encode()
        ts = str(int(timeutil.now().timestamp()))
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "Reja-Webhooks/1",
            "X-Reja-Event": d["event"],
            "X-Reja-Delivery": str(d["id"]),
            "X-Reja-Timestamp": ts,
            "X-Reja-Signature": "sha256=" + sign(d["secret"], body, ts),
        }
        error = None
        status = None
        try:
            check_url(d["url"])  # DNS may have changed since the hook was created
            status = post(d["url"], body, headers)
        except ApiError as e:
            error = e.code
        except (OSError, ValueError) as e:
            error = type(e).__name__
        ok = status is not None and 200 <= status < 300
        with db.session() as conn:
            if ok:
                conn.execute("UPDATE webhook_deliveries SET delivered_at = ?, attempts = attempts + 1 WHERE id = ?", (stamp(), d["id"]))
                conn.execute("UPDATE webhooks SET failures = 0, last_status = ? WHERE id = ?", (str(status), d["hook_id"]))
                sent += 1
            else:
                backoff = timedelta(minutes=2 ** d["attempts"])
                conn.execute(
                    "UPDATE webhook_deliveries SET attempts = attempts + 1, next_attempt_at = ?, last_error = ? WHERE id = ?",
                    (timeutil.to_iso(timeutil.now() + backoff), error or str(status), d["id"]),
                )
                conn.execute(
                    """UPDATE webhooks SET failures = failures + 1, last_status = ?,
                       active = CASE WHEN failures + 1 >= ? THEN 0 ELSE active END WHERE id = ?""",
                    (error or str(status), DISABLE_AFTER_FAILURES, d["hook_id"]),
                )
    return sent
