"""Notification centre (SCR-90) and feedback collection."""

from __future__ import annotations

from pydantic import BaseModel, Field

from .. import db as dbm
from ..http import Ctx, route
from ..util import new_id, now_iso


class FeedbackIn(BaseModel):
    score: int | None = Field(default=None, ge=0, le=10)
    comment: str | None = Field(default=None, max_length=2000)
    context: str | None = Field(default=None, max_length=80)


@route("GET", "/api/v1/notifications", mfa_exempt=True)
def list_notifications(ctx: Ctx):
    only_unread = ctx.q("unread") == "1"
    where = "user_id = ?" + (" AND read_at IS NULL" if only_unread else "")
    rows = dbm.all_(ctx.conn, f"SELECT * FROM notifications WHERE {where} ORDER BY created_at DESC LIMIT 100", (ctx.actor,))
    unread = dbm.scalar(ctx.conn, "SELECT COUNT(*) FROM notifications WHERE user_id = ? AND read_at IS NULL", (ctx.actor,))
    return {"items": rows, "unread": unread}


@route("POST", "/api/v1/notifications/{id}/read", mfa_exempt=True)
def mark_read(ctx: Ctx):
    ctx.conn.execute("UPDATE notifications SET read_at = ? WHERE id = ? AND user_id = ? AND read_at IS NULL",
                     (now_iso(), ctx.path["id"], ctx.actor))
    return {"ok": True}


@route("POST", "/api/v1/notifications/read-all", mfa_exempt=True)
def mark_all(ctx: Ctx):
    ctx.conn.execute("UPDATE notifications SET read_at = ? WHERE user_id = ? AND read_at IS NULL", (now_iso(), ctx.actor))
    return {"ok": True}


@route("POST", "/api/v1/feedback")
def feedback(ctx: Ctx, body: FeedbackIn):
    dbm.insert(ctx.conn, "feedback", {"id": new_id(), "tenant_id": ctx.tenant_id, "user_id": ctx.actor,
                                      "score": body.score, "comment": body.comment, "context": body.context,
                                      "created_at": now_iso()})
    return 201, {"ok": True}
