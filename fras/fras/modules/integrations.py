"""API keys, webhooks, Telegram bot binding (SCR-86, INT-01/02, NTF-02)."""

from __future__ import annotations

import hashlib
import hmac
import time
from datetime import date, timedelta

from pydantic import BaseModel, Field

from .. import db as dbm
from ..errors import ApiError, not_found, unprocessable
from ..http import Ctx, route
from ..security import crypto, tokens
from ..services import notify, tenancy
from ..util import dumps, iso, loads, new_id, now_iso, token, utcnow

API_SCOPES = {"attendance.read", "employee.read", "report.view", "org.read"}
WEBHOOK_EVENTS = {"attendance.event", "attendance.summary", "employee.created", "employee.deactivated", "period.closed"}


class ApiKeyIn(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    scopes: list[str] = Field(min_length=1)
    ip_allowlist: list[str] = []
    expires_on: date | None = None


class WebhookIn(BaseModel):
    url: str = Field(pattern=r"^https://", max_length=500)
    events: list[str] = Field(min_length=1)


@route("GET", "/api/v1/integrations/api-keys", perm="integration.manage")
def list_keys(ctx: Ctx):
    rows = dbm.all_(ctx.conn, "SELECT id, name, prefix, scopes, ip_allowlist, expires_at, created_at, revoked_at, "
                              "last_used_at FROM api_keys WHERE tenant_id = ? ORDER BY created_at DESC", (ctx.tenant_id,))
    for r in rows:
        r["scopes"] = loads(r["scopes"], [])
        r["ip_allowlist"] = loads(r["ip_allowlist"], [])
        r["rotation_due"] = r["created_at"] < iso(utcnow() - timedelta(days=90)) and not r["revoked_at"]
    return {"items": rows, "available_scopes": sorted(API_SCOPES)}


@route("POST", "/api/v1/integrations/api-keys", perm="integration.manage")
def create_key(ctx: Ctx, body: ApiKeyIn):
    if not tenancy.has_feature(ctx.conn, ctx.tenant_id, "api"):
        raise ApiError(402, "PLAN_FEATURE", "REST API is available from the Professional plan")
    bad = set(body.scopes) - API_SCOPES
    if bad:
        raise unprocessable("Unsupported scopes", "SCOPE_INVALID", scopes=sorted(bad))
    prefix = token(6)[:8].replace("-", "x").replace("_", "y")
    secret = token(24).replace("_", "z")
    key = f"fras_{prefix}_{secret}"
    row = {"id": new_id(), "tenant_id": ctx.tenant_id, "name": body.name, "prefix": prefix,
           "key_hash": tokens.hash_token(key), "scopes": dumps(sorted(body.scopes)),
           "ip_allowlist": dumps(body.ip_allowlist),
           "expires_at": f"{body.expires_on.isoformat()}T23:59:59Z" if body.expires_on else None,
           "created_by": ctx.actor, "created_at": now_iso(), "revoked_at": None, "last_used_at": None}
    dbm.insert(ctx.conn, "api_keys", row)
    ctx.audit("integration.api_key_created", "api_key", row["id"], after={"name": body.name, "scopes": body.scopes})
    return 201, {"id": row["id"], "key": key, "note": "Kalit faqat bir marta ko'rsatiladi"}


@route("POST", "/api/v1/integrations/api-keys/{id}/revoke", perm="integration.manage")
def revoke_key(ctx: Ctx):
    k = dbm.one(ctx.conn, "SELECT id FROM api_keys WHERE id = ? AND tenant_id = ?", (ctx.path["id"], ctx.tenant_id))
    if not k:
        raise not_found("API key")
    ctx.conn.execute("UPDATE api_keys SET revoked_at = ? WHERE id = ?", (now_iso(), k["id"]))
    ctx.audit("integration.api_key_revoked", "api_key", k["id"])
    return {"ok": True}


@route("GET", "/api/v1/integrations/webhooks", perm="integration.manage")
def list_hooks(ctx: Ctx):
    rows = dbm.all_(ctx.conn, "SELECT id, url, events, status, created_at FROM webhooks WHERE tenant_id = ?", (ctx.tenant_id,))
    for r in rows:
        r["events"] = loads(r["events"], [])
        r["recent"] = dbm.all_(ctx.conn, "SELECT status, attempts, last_error, created_at FROM notification_outbox WHERE "
                                         "channel = 'webhook' AND recipient = ? ORDER BY created_at DESC LIMIT 5", (r["id"],))
    return {"items": rows, "events": sorted(WEBHOOK_EVENTS)}


@route("POST", "/api/v1/integrations/webhooks", perm="integration.manage")
def create_hook(ctx: Ctx, body: WebhookIn):
    if not tenancy.has_feature(ctx.conn, ctx.tenant_id, "webhooks"):
        raise ApiError(402, "PLAN_FEATURE", "Webhooks are available from the Professional plan")
    bad = set(body.events) - WEBHOOK_EVENTS
    if bad:
        raise unprocessable("Unknown events", "EVENT_INVALID", events=sorted(bad))
    secret = token(32)
    sealed = crypto.seal(ctx.dek(), secret.encode(), b"webhook")
    row = {"id": new_id(), "tenant_id": ctx.tenant_id, "url": body.url, "events": dumps(sorted(body.events)),
           "secret_enc": sealed, "secret_nonce": b"", "status": "active", "created_by": ctx.actor, "created_at": now_iso()}
    dbm.insert(ctx.conn, "webhooks", row)
    ctx.audit("integration.webhook_created", "webhook", row["id"], after={"url": body.url, "events": body.events})
    return 201, {"id": row["id"], "signing_secret": secret,
                 "note": "Har so'rov X-FRAS-Signature: sha256=HMAC(secret, timestamp.body) bilan imzolanadi"}


@route("DELETE", "/api/v1/integrations/webhooks/{id}", perm="integration.manage")
def delete_hook(ctx: Ctx):
    h = dbm.one(ctx.conn, "SELECT id FROM webhooks WHERE id = ? AND tenant_id = ?", (ctx.path["id"], ctx.tenant_id))
    if not h:
        raise not_found("Webhook")
    ctx.conn.execute("UPDATE webhooks SET status = 'deleted' WHERE id = ?", (h["id"],))
    ctx.audit("integration.webhook_deleted", "webhook", h["id"])
    return {"ok": True}


@route("POST", "/api/v1/integrations/webhooks/{id}/test", perm="integration.manage")
def test_hook(ctx: Ctx):
    h = dbm.one(ctx.conn, "SELECT id FROM webhooks WHERE id = ? AND tenant_id = ? AND status = 'active'",
                (ctx.path["id"], ctx.tenant_id))
    if not h:
        raise not_found("Webhook")
    notify.enqueue(ctx.conn, ctx.tenant_id, "webhook", h["id"], {"type": "ping", "at": now_iso()})
    return {"queued": True}


def emit(conn, tenant_id: str, event: str, data: dict) -> int:
    n = 0
    for h in dbm.all_(conn, "SELECT id, events FROM webhooks WHERE tenant_id = ? AND status = 'active'", (tenant_id,)):
        if event in loads(h["events"], []):
            notify.enqueue(conn, tenant_id, "webhook", h["id"], {"type": event, "data": data, "at": now_iso()})
            n += 1
    return n


def sign_webhook(secret: str, body: bytes, ts: int | None = None) -> tuple[str, str]:
    ts = ts or int(time.time())
    sig = hmac.new(secret.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
    return str(ts), f"sha256={sig}"


class TelegramUpdate(BaseModel):
    update_id: int | None = None
    message: dict | None = None


@route("POST", "/api/v1/integrations/telegram/{secret}", auth="public", rate="public")
def telegram_webhook(ctx: Ctx, body: TelegramUpdate):
    """Bot webhook: `/link 123456` binds the chat to the user who generated the code."""
    expected = hashlib.sha256((ctx.settings.telegram_bot_token or "disabled").encode()).hexdigest()[:32]
    if not ctx.settings.telegram_bot_token or not hmac.compare_digest(ctx.path["secret"], expected):
        raise not_found("Endpoint")
    msg = body.message or {}
    text = (msg.get("text") or "").strip()
    chat_id = str((msg.get("chat") or {}).get("id", ""))
    if text.startswith("/link ") and chat_id:
        code = text.split(" ", 1)[1].strip()
        entry = ctx.state.telegram_codes.pop(code, None)
        if entry and entry[1] > time.time():
            ctx.conn.execute("UPDATE users SET telegram_chat_id = ? WHERE id = ?", (chat_id, entry[0]))
            notify.enqueue(ctx.conn, None, "telegram", chat_id, {"text": "FRAS: akkaunt bog'landi ✓"})
        else:
            notify.enqueue(ctx.conn, None, "telegram", chat_id, {"text": "Kod noto'g'ri yoki muddati o'tgan"})
    return {"ok": True}

