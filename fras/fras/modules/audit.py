"""Audit log browser and integrity verification (SCR-73)."""

from __future__ import annotations

import csv
import io

from starlette.responses import Response

from .. import db as dbm
from ..http import Ctx, page_params, paged, route
from ..security import audit as auditlog
from ..services.alerts import raise_alert

# Which audit actions each non-auditor role may see (spec D.2: "HR amallari", "xavfsizlik").
PREFIXES_BY_PERM = {
    "employee.write": ("employee.", "correction.", "leave.", "period.", "shift.", "calendar.", "biometric.", "consent."),
    "alert.manage": ("biometric.", "device.", "attendance.", "auth.", "session.", "user.", "consent."),
}


def _filters(ctx: Ctx) -> tuple[list[str], list]:
    where, params = ["a.tenant_id = ?"], [ctx.tenant_id]
    if not (ctx.can("audit.export") or ctx.can("role.manage") or ctx.can("user.manage")):
        prefixes = set()
        for perm, pre in PREFIXES_BY_PERM.items():
            if ctx.can(perm):
                prefixes.update(pre)
        if prefixes:
            where.append("(" + " OR ".join("a.action LIKE ?" for _ in prefixes) + ")")
            params += [p + "%" for p in sorted(prefixes)]
    for col, name in (("a.actor_id", "actor_id"), ("a.object_type", "object_type"), ("a.object_id", "object_id"),
                      ("a.result", "result")):
        if ctx.q(name):
            where.append(f"{col} = ?")
            params.append(ctx.q(name))
    if ctx.q("action"):
        where.append("a.action LIKE ?")
        params.append(ctx.q("action").replace("*", "%"))
    if ctx.q("from"):
        where.append("a.created_at >= ?")
        params.append(ctx.q("from"))
    if ctx.q("to"):
        where.append("a.created_at <= ?")
        params.append(ctx.q("to") + ("T23:59:59Z" if len(ctx.q("to")) == 10 else ""))
    return where, params


@route("GET", "/api/v1/audit", perm="audit.read")
def list_audit(ctx: Ctx):
    where, params = _filters(ctx)
    limit, offset = page_params(ctx, 500)
    total = dbm.scalar(ctx.conn, f"SELECT COUNT(*) FROM audit_logs a WHERE {' AND '.join(where)}", params)
    rows = dbm.all_(ctx.conn, f"SELECT a.*, COALESCE(u.name, d.name) AS actor_name FROM audit_logs a "
                              f"LEFT JOIN users u ON u.id = a.actor_id LEFT JOIN devices d ON d.id = a.actor_id "
                              f"WHERE {' AND '.join(where)} ORDER BY a.seq DESC LIMIT ? OFFSET ?",
                    [*params, limit, offset])
    return paged(rows, total, limit, offset)


@route("POST", "/api/v1/audit/verify", perm="audit.read")
def verify(ctx: Ctx):
    result = auditlog.verify_chain(ctx.conn, ctx.tenant_id)
    if not result["ok"]:
        ctx.keep_on_error = True
        raise_alert(ctx.conn, ctx.tenant_id, "audit_chain_broken", "critical", result)
    ctx.audit("audit.verified", "audit", None, after=result)
    return result


@route("GET", "/api/v1/audit/export", perm="audit.export")
def export(ctx: Ctx):
    where, params = _filters(ctx)
    rows = dbm.all_(ctx.conn, f"SELECT a.seq, a.created_at, a.actor_type, a.actor_id, a.action, a.object_type, a.object_id, "
                              f"a.ip, a.result, a.before_json, a.after_json, a.hash FROM audit_logs a "
                              f"WHERE {' AND '.join(where)} ORDER BY a.seq LIMIT 200000", params)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["seq", "created_at", "actor_type", "actor_id", "action", "object_type", "object_id", "ip", "result",
                "before", "after", "hash"])
    for r in rows:
        w.writerow(list(r.values()))
    ctx.audit("audit.exported", "audit", None, after={"rows": len(rows)})
    return Response(buf.getvalue().encode("utf-8-sig"), media_type="text/csv",
                    headers={"Content-Disposition": "attachment; filename=fras-audit.csv"})
