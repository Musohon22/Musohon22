"""Security alerts queue (SCR-74)."""

from __future__ import annotations

from pydantic import BaseModel, Field

from .. import db as dbm
from ..errors import conflict, not_found, unprocessable
from ..http import Ctx, page_params, paged, route
from ..services.alerts import TITLES
from ..util import loads, now_iso


class AlertUpdateIn(BaseModel):
    status: str = Field(pattern="^(in_review|closed)$")
    resolution: str | None = Field(default=None, max_length=1000)
    version_updated_at: str | None = None


@route("GET", "/api/v1/security/alerts", perm="alert.read")
def list_alerts(ctx: Ctx):
    where, params = ["a.tenant_id = ?"], [ctx.tenant_id]
    for col, name in (("a.status", "status"), ("a.severity", "severity"), ("a.kind", "kind")):
        vals = ctx.qlist(name)
        if vals:
            where.append(f"{col} IN ({','.join('?' * len(vals))})")
            params += vals
    limit, offset = page_params(ctx)
    total = dbm.scalar(ctx.conn, f"SELECT COUNT(*) FROM security_alerts a WHERE {' AND '.join(where)}", params)
    rows = dbm.all_(ctx.conn, f"SELECT a.*, d.name AS device_name, u.name AS assignee_name FROM security_alerts a "
                              f"LEFT JOIN devices d ON d.id = a.device_id LEFT JOIN users u ON u.id = a.assignee "
                              f"WHERE {' AND '.join(where)} ORDER BY CASE a.severity WHEN 'critical' THEN 0 WHEN 'high' "
                              f"THEN 1 WHEN 'medium' THEN 2 ELSE 3 END, a.created_at DESC LIMIT ? OFFSET ?",
                    [*params, limit, offset])
    for r in rows:
        r["details"] = loads(r["details"], {})
        r["title"] = TITLES.get(r["kind"], r["kind"])
    counts = {s: dbm.scalar(ctx.conn, "SELECT COUNT(*) FROM security_alerts WHERE tenant_id = ? AND status = ?",
                            (ctx.tenant_id, s)) for s in ("new", "in_review", "closed")}
    return {**paged(rows, total, limit, offset), "counts": counts}


@route("PATCH", "/api/v1/security/alerts/{id}", perm="alert.manage")
def update_alert(ctx: Ctx, body: AlertUpdateIn):
    a = dbm.one(ctx.conn, "SELECT * FROM security_alerts WHERE id = ? AND tenant_id = ?", (ctx.path["id"], ctx.tenant_id))
    if not a:
        raise not_found("Alert")
    if body.version_updated_at and body.version_updated_at != a["updated_at"]:
        raise conflict("Alert was changed by another user", "VERSION_CONFLICT")
    if a["status"] == "closed":
        raise conflict("Alert is already closed", "ALERT_CLOSED")
    if body.status == "closed" and not (body.resolution and len(body.resolution) >= 10):
        raise unprocessable("A closing summary (min 10 characters) is required", "RESOLUTION_REQUIRED")
    changes = {"status": body.status, "updated_at": now_iso(), "assignee": a["assignee"] or ctx.actor}
    if body.resolution:
        changes["resolution"] = body.resolution
    dbm.update(ctx.conn, "security_alerts", {"id": a["id"]}, changes)
    ctx.audit(f"alert.{body.status}", "security_alert", a["id"], after=changes)
    return {**a, **changes, "details": loads(a["details"], {})}
