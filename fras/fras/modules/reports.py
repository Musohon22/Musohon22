"""Reports catalogue, on-screen run, async exports with audit (SCR-50 … SCR-52)."""

from __future__ import annotations

import threading
from datetime import date, timedelta
from pathlib import Path

from pydantic import BaseModel, Field
from starlette.responses import Response

from .. import db as dbm
from ..errors import ApiError, forbidden, gone, not_found, unprocessable
from ..http import Ctx, route
from ..services import notify, report_svc, tenancy
from ..util import dumps, iso, loads, new_id, now_iso, parse_dt, utcnow

SYNC_ROW_LIMIT = 50_000


class RunIn(BaseModel):
    type: str
    params: dict = {}


class ExportIn(BaseModel):
    type: str
    params: dict = {}
    format: str = Field(pattern="^(xlsx|csv|pdf)$")
    reason: str | None = Field(default=None, max_length=300)


def _spec(ctx: Ctx, rtype: str) -> dict:
    spec = next((r for r in report_svc.CATALOG if r["type"] == rtype), None)
    if not spec:
        raise not_found("Report type")
    ctx.require(spec["perm"])
    return spec


def _check_range(params: dict) -> None:
    if params.get("from") and params.get("to"):
        a, b = date.fromisoformat(params["from"]), date.fromisoformat(params["to"])
        if b < a or (b - a).days > 366:
            raise unprocessable("Period must be 1–366 days", "RANGE_INVALID")


def _tz(ctx: Ctx, params: dict) -> str:
    if params.get("site_id"):
        return dbm.scalar(ctx.conn, "SELECT timezone FROM sites WHERE id = ? AND tenant_id = ?",
                          (params["site_id"], ctx.tenant_id)) or "Asia/Tashkent"
    return dbm.scalar(ctx.conn, "SELECT timezone FROM sites WHERE tenant_id = ? LIMIT 1", (ctx.tenant_id,)) or "Asia/Tashkent"


@route("GET", "/api/v1/reports", perm="report.view")
def catalog(ctx: Ctx):
    last = {r["kind"]: r["created_at"] for r in dbm.all_(
        ctx.conn, "SELECT kind, max(created_at) AS created_at FROM exports WHERE tenant_id = ? GROUP BY kind",
        (ctx.tenant_id,))}
    return {"items": [{**r, "last_run_at": last.get(r["type"]), "allowed": ctx.can(r["perm"])}
                      for r in report_svc.CATALOG]}


@route("POST", "/api/v1/reports/run", perm="report.view", auth="user_or_api")
def run(ctx: Ctx, body: RunIn):
    _spec(ctx, body.type)
    _check_range(body.params)
    scope = ctx.employee_filter("attendance.read")
    report = report_svc.run(ctx.conn, ctx.tenant_id, body.type, body.params, scope, _tz(ctx, body.params))
    if len(report["rows"]) > SYNC_ROW_LIMIT:
        raise ApiError(408, "REPORT_TOO_LARGE", "Report is large; use export (runs in the background)")
    if body.type in ("daily", "timesheet", "absences", "lateness", "payroll"):
        ctx.audit("report.viewed", "report", body.type, after={"params": body.params, "rows": len(report["rows"])})
    period = None
    if body.params.get("from"):
        closed = dbm.one(ctx.conn, "SELECT 1 AS x FROM periods WHERE tenant_id = ? AND status = 'closed' AND start_date <= ? "
                                   "AND end_date >= ?", (ctx.tenant_id, body.params["from"], body.params.get("to", "")))
        period = "closed" if closed else "open"
    return {**report, "period_status": period, "row_count": len(report["rows"])}


def _do_export(state, export_id: str, tenant_id: str, rtype: str, params: dict, fmt: str, scope, watermark: str, tz: str,
               user_id: str) -> None:
    conn = state.db.connect()
    try:
        report = report_svc.run(conn, tenant_id, rtype, params, scope, tz)
        data, _mime, ext = report_svc.render(report, fmt, watermark)
        folder = Path(state.settings.data_dir) / "exports" / tenant_id
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{export_id}.{ext}"
        path.write_bytes(data)
        conn.execute("UPDATE exports SET status = 'ready', file_path = ?, rows = ?, finished_at = ?, expires_at = ? "
                     "WHERE id = ?", (str(path), len(report["rows"]), now_iso(),
                                      iso(utcnow() + timedelta(days=7)), export_id))
        notify.notify_user(conn, tenant_id, user_id, "export_ready", "Eksport tayyor", report["title"],
                           "/app/reports/exports")
    except Exception as e:  # noqa: BLE001 - recorded on the export row
        conn.execute("UPDATE exports SET status = 'failed', error = ?, finished_at = ? WHERE id = ?",
                     (str(e)[:500], now_iso(), export_id))
    finally:
        state.db.release(conn)


def start_export(ctx: Ctx, rtype: str, params: dict, fmt: str, reason: str | None = None) -> dict:
    if fmt in ("xlsx", "pdf") and not tenancy.has_feature(ctx.conn, ctx.tenant_id, "xlsx_pdf"):
        raise ApiError(402, "PLAN_FEATURE", "XLSX/PDF export is available from the Business plan; CSV is included")
    _check_range(params)
    user = dbm.one(ctx.conn, "SELECT name, login FROM users WHERE id = ?", (ctx.actor,)) if ctx.p.kind == "user" else None
    watermark = f"FRAS · {user['name'] if user else ctx.p.name} · {now_iso()}"
    export_id = new_id()
    dbm.insert(ctx.conn, "exports", {"id": export_id, "tenant_id": ctx.tenant_id, "kind": rtype, "params": dumps(params),
                                     "format": fmt, "status": "running", "file_path": None, "rows": None, "error": None,
                                     "requested_by": ctx.actor, "created_at": now_iso(), "finished_at": None,
                                     "expires_at": None})
    ctx.audit("report.exported", "export", export_id, after={"type": rtype, "params": params, "format": fmt,
                                                             "reason": reason})
    scope = ctx.employee_filter("attendance.read")
    state, tid, tz, uid = ctx.state, ctx.tenant_id, _tz(ctx, params), ctx.actor
    ctx.after_commit(lambda: threading.Thread(
        target=_do_export, args=(state, export_id, tid, rtype, params, fmt, scope, watermark, tz, uid), daemon=True).start())
    return {"export_id": export_id, "status": "running"}


@route("POST", "/api/v1/reports/export", perm="report.export")
def export(ctx: Ctx, body: ExportIn):
    _spec(ctx, body.type)
    return 202, start_export(ctx, body.type, body.params, body.format, body.reason)


@route("GET", "/api/v1/exports", perm="report.view")
def list_exports(ctx: Ctx):
    where, params = ["e.tenant_id = ?"], [ctx.tenant_id]
    if not ctx.can("audit.export"):
        where.append("e.requested_by = ?")
        params.append(ctx.actor)
    rows = dbm.all_(ctx.conn, f"SELECT e.*, u.name AS requested_by_name FROM exports e LEFT JOIN users u ON u.id = "
                              f"e.requested_by WHERE {' AND '.join(where)} ORDER BY e.created_at DESC LIMIT 100", params)
    for r in rows:
        r["params"] = loads(r["params"], {})
        r.pop("file_path", None)
        if r["status"] == "ready" and r["expires_at"] and parse_dt(r["expires_at"]) < utcnow():
            r["status"] = "expired"
    return {"items": rows}


@route("GET", "/api/v1/exports/{id}", perm="report.view")
def get_export(ctx: Ctx):
    e = dbm.one(ctx.conn, "SELECT id, kind, format, status, rows, error, created_at, finished_at, expires_at FROM exports "
                          "WHERE id = ? AND tenant_id = ?", (ctx.path["id"], ctx.tenant_id))
    if not e:
        raise not_found("Export")
    return e


@route("GET", "/api/v1/exports/{id}/download", perm="report.view")
def download(ctx: Ctx):
    e = dbm.one(ctx.conn, "SELECT * FROM exports WHERE id = ? AND tenant_id = ?", (ctx.path["id"], ctx.tenant_id))
    if not e:
        raise not_found("Export")
    if e["requested_by"] != ctx.actor and not ctx.can("audit.export"):
        raise forbidden("Only the requester can download this file")
    if not ctx.can("report.export") and e["kind"] != "employees":
        raise forbidden("Export permission required")
    if e["status"] != "ready":
        raise unprocessable(f"Export is {e['status']}", "EXPORT_NOT_READY")
    if parse_dt(e["expires_at"]) < utcnow():
        raise gone("File has expired (7 days)", "EXPORT_EXPIRED")
    path = Path(e["file_path"])
    if not path.exists():
        raise gone("File has expired", "EXPORT_EXPIRED")
    ctx.audit("export.downloaded", "export", e["id"])
    mime = {"xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "csv": "text/csv",
            "pdf": "application/pdf"}[e["format"]]
    return Response(path.read_bytes(), media_type=mime,
                    headers={"Content-Disposition": f"attachment; filename=fras-{e['kind']}-{e['id'][:8]}.{e['format']}"})


# employees export lives here because it shares the export pipeline
class EmployeeExportIn(BaseModel):
    format: str = Field(pattern="^(xlsx|csv)$")
    include_sensitive: bool = False
    reason: str | None = Field(default=None, max_length=300)
    filters: dict = {}


@route("POST", "/api/v1/employees/export", perm="employee.export")
def export_employees(ctx: Ctx, body: EmployeeExportIn):
    if body.include_sensitive:
        ctx.require("employee.read_sensitive")
        if not (body.reason and len(body.reason) >= 10):
            raise unprocessable("Exporting personal fields needs a reason (min 10 characters)", "REASON_REQUIRED")
    sql, params = ctx.employee_filter("employee.read")
    rows = dbm.all_(ctx.conn, f"SELECT e.personnel_no, e.last_name, e.first_name, e.middle_name, d.name AS department, "
                              f"p.name AS position, e.team, e.hire_date, e.status, e.biometric_status, e.phone, "
                              f"e.birth_date, e.pinfl_last4 FROM employees e LEFT JOIN departments d ON d.id = "
                              f"e.department_id LEFT JOIN positions p ON p.id = e.position_id WHERE e.tenant_id = ? AND "
                              f"{sql} ORDER BY e.last_name", [ctx.tenant_id, *params])
    cols = ["personnel_no", "last_name", "first_name", "middle_name", "department", "position", "team", "hire_date",
            "status", "biometric_status"] + (["phone", "birth_date", "pinfl_last4"] if body.include_sensitive else [])
    report = {"title": "Xodimlar", "columns": cols, "rows": [[r[c] for c in cols] for r in rows]}
    user = dbm.one(ctx.conn, "SELECT name FROM users WHERE id = ?", (ctx.actor,))
    data, mime, ext = report_svc.render(report, body.format, f"FRAS · {user['name']} · {now_iso()}")
    export_id = new_id()
    folder = Path(ctx.settings.data_dir) / "exports" / ctx.tenant_id
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{export_id}.{ext}"
    path.write_bytes(data)
    dbm.insert(ctx.conn, "exports", {"id": export_id, "tenant_id": ctx.tenant_id, "kind": "employees",
                                     "params": dumps({"sensitive": body.include_sensitive}), "format": body.format,
                                     "status": "ready", "file_path": str(path), "rows": len(rows), "error": None,
                                     "requested_by": ctx.actor, "created_at": now_iso(), "finished_at": now_iso(),
                                     "expires_at": iso(utcnow() + timedelta(days=1))})
    ctx.audit("employee.exported", "export", export_id, after={"rows": len(rows), "columns": cols,
                                                               "reason": body.reason})
    return 201, {"export_id": export_id, "status": "ready", "rows": len(rows)}
