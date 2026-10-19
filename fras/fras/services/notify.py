"""In-app notifications plus an outbox for email / Telegram delivery (with retries)."""

from __future__ import annotations

from datetime import timedelta

from .. import db as dbm
from ..util import dumps, iso, new_id, now_iso, utcnow


def users_with_permission(conn, tenant_id: str, perm: str, site_id: str | None = None) -> list[dict]:
    from ..http import load_user_principal

    out = []
    for u in dbm.all_(conn, "SELECT * FROM users WHERE tenant_id = ? AND status = 'active'", (tenant_id,)):
        p = load_user_principal(conn, u, None)
        scopes = p.perms.get(perm)
        if not scopes:
            continue
        if site_id and not any(s[0] == "global" or (s[0] == "site" and s[1] == site_id) for s in scopes):
            dept_sites = {dbm.scalar(conn, "SELECT site_id FROM departments WHERE id = ?", ((s[1] or "").split(":")[0],))
                          for s in scopes if s[0] in ("department", "team")}
            if site_id not in dept_sites:
                continue
        out.append(u)
    return out


def notify_user(conn, tenant_id: str, user_id: str, kind: str, title: str, body: str, link: str | None = None,
                channels: tuple[str, ...] = ("in_app",)) -> None:
    dbm.insert(conn, "notifications", {"id": new_id(), "tenant_id": tenant_id, "user_id": user_id, "kind": kind,
                                       "title": title, "body": body, "link": link, "read_at": None,
                                       "created_at": now_iso()})
    user = dbm.one(conn, "SELECT email, telegram_chat_id FROM users WHERE id = ?", (user_id,))
    if "email" in channels and user and user["email"]:
        enqueue(conn, tenant_id, "email", user["email"], {"subject": title, "body": body, "link": link})
    if "telegram" in channels and user and user["telegram_chat_id"]:
        enqueue(conn, tenant_id, "telegram", user["telegram_chat_id"], {"text": f"{title}\n{body}"})


def notify_permission(conn, tenant_id: str, perm: str, kind: str, title: str, body: str, link: str | None = None,
                      site_id: str | None = None, channels: tuple[str, ...] = ("in_app",),
                      exclude_user: str | None = None) -> int:
    n = 0
    for u in users_with_permission(conn, tenant_id, perm, site_id):
        if u["id"] == exclude_user:
            continue
        notify_user(conn, tenant_id, u["id"], kind, title, body, link, channels)
        n += 1
    return n


def notify_employee(conn, tenant_id: str, employee_id: str, kind: str, title: str, body: str,
                    link: str | None = None) -> None:
    user = dbm.one(conn, "SELECT id FROM users WHERE tenant_id = ? AND employee_id = ?", (tenant_id, employee_id))
    if user:
        notify_user(conn, tenant_id, user["id"], kind, title, body, link, ("in_app", "telegram"))


def enqueue(conn, tenant_id: str | None, channel: str, recipient: str, payload: dict) -> None:
    dbm.insert(conn, "notification_outbox", {"id": new_id(), "tenant_id": tenant_id, "channel": channel,
                                             "recipient": recipient, "payload": dumps(payload), "status": "pending",
                                             "attempts": 0, "next_attempt_at": now_iso(), "last_error": None,
                                             "created_at": now_iso()})


def backoff(attempts: int) -> str:
    return iso(utcnow() + timedelta(seconds=min(3600, 30 * (2 ** attempts))))
