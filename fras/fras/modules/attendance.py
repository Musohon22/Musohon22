"""Attendance journal, event review, timesheet, anomalies, periods (SCR-30 … SCR-36)."""

from __future__ import annotations

from datetime import date, timedelta

from pydantic import BaseModel, Field

from .. import db as dbm
from ..errors import ApiError, conflict, forbidden, not_found, unprocessable
from ..http import Ctx, page_params, paged, route
from ..live import broker
from ..services import attendance_svc, notify
from ..util import loads, new_id, now_iso, parse_dt


class ReviewIn(BaseModel):
    comment: str | None = Field(default=None, max_length=500)


class RejectIn(BaseModel):
    comment: str = Field(min_length=10, max_length=500)
    open_incident: bool = False


class CaptureIn(BaseModel):
    reason: str = Field(min_length=10, max_length=300)


class PeriodIn(BaseModel):
    site_id: str
    start_date: date
    end_date: date


class CloseIn(BaseModel):
    note: str | None = Field(default=None, max_length=500)
    force: bool = False


class ReopenIn(BaseModel):
    reason: str = Field(min_length=10, max_length=500)


EVENT_SELECT = ("SELECT ev.*, e.personnel_no, e.last_name, e.first_name, e.department_id, ap.name AS access_point_name, "
                "d.name AS device_name, r.decision AS review_decision, r.comment AS review_comment "
                "FROM attendance_events ev LEFT JOIN employees e ON e.id = ev.employee_id "
                "LEFT JOIN access_points ap ON ap.id = ev.access_point_id LEFT JOIN devices d ON d.id = ev.device_id "
                "LEFT JOIN event_reviews r ON r.event_id = ev.id ")


def event_view(row: dict, ctx: Ctx) -> dict:
    out = dict(row)
    out["flags"] = loads(row.get("flags"), [])
    out.pop("signature", None)
    out["has_capture"] = bool(row.get("capture_ref"))
    out.pop("capture_ref", None)
    score = row.get("score")
    out["confidence"] = None if score is None else ("high" if score >= 0.7 else "medium" if score >= 0.55 else "low")
    if not (ctx.can("biometric.review") or ctx.can("employee.read_sensitive")):
        out.pop("score", None)
        out.pop("liveness_score", None)
    out["review_status"] = row.get("review_decision") or ("pending" if row.get("result") == "review" else "none")
    return out


def _event_scope(ctx: Ctx) -> tuple[str, list]:
    if ctx.is_global("attendance.read"):
        return "1=1", []
    emp_sql, params = ctx.employee_filter("attendance.read", "e")
    sites = ctx.site_ids("attendance.read") or set()
    # security staff with site scope also see unknown-person events of their sites
    unknown = ""
    if ctx.can("alert.manage") and sites:
        unknown = f" OR (ev.employee_id IS NULL AND ev.site_id IN ({','.join('?' * len(sites))}))"
        params = [*params, *sites]
    return f"({emp_sql}{unknown})", params


@route("GET", "/api/v1/attendance/events", perm="attendance.read", auth="user_or_api")
def list_events(ctx: Ctx):
    scope_sql, params = _event_scope(ctx)
    where = ["ev.tenant_id = ?", scope_sql]
    p = [ctx.tenant_id, *params]
    frm = ctx.q("from", date.today().isoformat())
    to = ctx.q("to", frm)
    if (date.fromisoformat(to) - date.fromisoformat(frm)).days > 93:
        raise unprocessable("Range is limited to 93 days; use reports for longer periods", "RANGE_TOO_LARGE")
    where += ["ev.captured_at >= ?", "ev.captured_at < ?"]
    p += [f"{frm}T00:00:00Z" if "T" not in frm else frm,
          (date.fromisoformat(to[:10]) + timedelta(days=1)).isoformat() + "T00:00:00Z"]
    tab = ctx.q("tab", "all")
    if tab == "suspicious":
        where.append("(ev.result IN ('pad','review','unknown') OR ev.clock_suspect = 1)")
    elif tab == "duplicate":
        where.append("ev.result = 'duplicate'")
    elif tab == "rejected":
        where.append("(ev.result IN ('denied','pad','unknown') OR r.decision = 'rejected')")
    elif tab == "late":
        where.append("ev.late_arrival = 1")
    for col, name in (("ev.employee_id", "employee_id"), ("e.department_id", "department_id"), ("ev.site_id", "site_id"),
                      ("ev.device_id", "device_id"), ("ev.access_point_id", "access_point_id"),
                      ("ev.direction", "direction"), ("ev.result", "result"), ("ev.method", "method")):
        vals = ctx.qlist(name)
        if vals:
            where.append(f"{col} IN ({','.join('?' * len(vals))})")
            p += vals
    if ctx.q("review") == "pending":
        where.append("ev.result = 'review' AND r.decision IS NULL")
    q = (ctx.q("q") or "").strip().lower()
    if q:
        where.append("(lower(e.last_name) LIKE ? OR lower(e.personnel_no) LIKE ?)")
        p += [f"%{q}%", f"%{q}%"]
    limit, offset = page_params(ctx, 500)
    sql_where = " AND ".join(where)
    base = ("FROM attendance_events ev LEFT JOIN employees e ON e.id = ev.employee_id "
            "LEFT JOIN event_reviews r ON r.event_id = ev.id ")
    total = dbm.scalar(ctx.conn, f"SELECT COUNT(*) {base} WHERE {sql_where}", p)
    if total > 100_000:
        raise ApiError(413, "RESULT_TOO_LARGE", "Result is too large; narrow the filters or create a report")
    rows = dbm.all_(ctx.conn, f"{EVENT_SELECT} WHERE {sql_where} ORDER BY ev.captured_at DESC LIMIT ? OFFSET ?",
                    [*p, limit, offset])
    offline = dbm.scalar(ctx.conn, "SELECT COUNT(*) FROM devices WHERE tenant_id = ? AND status = 'offline'",
                         (ctx.tenant_id,))
    return {**paged([event_view(r, ctx) for r in rows], total, limit, offset), "offline_devices": offline}


def _get_event(ctx: Ctx, event_id: str) -> dict:
    row = dbm.one(ctx.conn, f"{EVENT_SELECT} WHERE ev.id = ? AND ev.tenant_id = ?", (event_id, ctx.tenant_id))
    if not row:
        raise not_found("Event")
    if row["employee_id"]:
        emp = dbm.one(ctx.conn, "SELECT * FROM employees WHERE id = ?", (row["employee_id"],))
        ctx.require_employee("attendance.read", emp)
    elif not (ctx.is_global("attendance.read") or ctx.can("alert.manage")):
        raise forbidden()
    return row


@route("GET", "/api/v1/attendance/events/{id}", perm="attendance.read")
def get_event(ctx: Ctx):
    row = _get_event(ctx, ctx.path["id"])
    out = event_view(row, ctx)
    related = []
    work_date = None
    if row["employee_id"]:
        emp = dbm.one(ctx.conn, "SELECT * FROM employees WHERE id = ?", (row["employee_id"],))
        wd = attendance_svc.work_date_of(ctx.conn, ctx.tenant_id, emp, parse_dt(row["captured_at"]))
        work_date = wd.isoformat()
        related = [event_view(r, ctx) for r in attendance_svc.events_for_work_date(ctx.conn, ctx.tenant_id, emp, wd)]
        summary = dbm.one(ctx.conn, "SELECT * FROM daily_summaries WHERE tenant_id = ? AND employee_id = ? AND work_date = ?",
                          (ctx.tenant_id, emp["id"], work_date))
        out["summary"] = attendance_svc.summary_view(summary) if summary else None
    out["work_date"] = work_date
    out["related"] = related
    out["corrections"] = dbm.all_(ctx.conn, "SELECT c.*, u.name AS requested_by_name FROM corrections c LEFT JOIN users u "
                                            "ON u.id = c.requested_by WHERE c.event_id = ? ORDER BY c.created_at",
                                  (row["id"],))
    out["received_delay_s"] = int((parse_dt(row["received_at"]) - parse_dt(row["captured_at"])).total_seconds())
    if ctx.can("biometric.review"):
        out["model_version"] = row["model_version"]
    return out


def _decide(ctx: Ctx, event_id: str, decision: str, comment: str | None) -> dict:
    row = _get_event(ctx, event_id)
    if row["result"] not in ("review", "pad", "unknown") and not row["clock_suspect"]:
        raise unprocessable("Only suspicious events need a decision", "NOT_SUSPICIOUS")
    if row["review_decision"]:
        raise conflict("Another user already decided on this event", "ALREADY_DECIDED",
                       decision=row["review_decision"])
    dbm.insert(ctx.conn, "event_reviews", {"id": new_id(), "tenant_id": ctx.tenant_id, "event_id": row["id"],
                                           "decision": decision, "comment": comment, "decided_by": ctx.actor,
                                           "created_at": now_iso()})
    ctx.audit(f"attendance.event_{decision}", "attendance_event", row["id"], after={"comment": comment})
    if row["employee_id"]:
        attendance_svc.on_event(ctx.conn, ctx.tenant_id, row)
    return row


@route("POST", "/api/v1/attendance/events/{id}/verify", perm="attendance.verify")
def verify(ctx: Ctx, body: ReviewIn):
    _decide(ctx, ctx.path["id"], "verified", body.comment)
    return {"ok": True, "review_status": "verified"}


@route("POST", "/api/v1/attendance/events/{id}/reject", perm="attendance.verify")
def reject(ctx: Ctx, body: RejectIn):
    row = _decide(ctx, ctx.path["id"], "rejected", body.comment)
    if body.open_incident:
        from ..services.alerts import raise_alert
        raise_alert(ctx.conn, ctx.tenant_id, "pad_attempt" if row["result"] == "pad" else "unknown_repeat", "high",
                    {"event_id": row["id"], "comment": body.comment}, device_id=row["device_id"], event_id=row["id"],
                    site_id=row["site_id"])
    return {"ok": True, "review_status": "rejected"}


@route("POST", "/api/v1/attendance/events/{id}/capture", perm="attendance.capture_view")
def view_capture(ctx: Ctx, body: CaptureIn):
    """Returns the encrypted capture of a suspicious event; every access is logged with its reason."""
    row = _get_event(ctx, ctx.path["id"])
    ref = dbm.scalar(ctx.conn, "SELECT capture_ref FROM attendance_events WHERE id = ?", (row["id"],))
    if not ref:
        raise not_found("Capture (kept only for suspicious events, 30 days)")
    dbm.insert(ctx.conn, "capture_access_log", {"id": new_id(), "tenant_id": ctx.tenant_id, "event_id": row["id"],
                                                "user_id": ctx.actor, "reason": body.reason, "created_at": now_iso()})
    ctx.audit("attendance.capture_viewed", "attendance_event", row["id"], after={"reason": body.reason})
    from ..services import captures
    return {"image_data_url": captures.load_data_url(ctx, ref)}


# ----------------------------------------------------------------- timesheet (SCR-32)

@route("GET", "/api/v1/attendance/daily-summaries", perm="attendance.read", auth="user_or_api")
def summaries(ctx: Ctx):
    frm = date.fromisoformat(ctx.q("from", date.today().replace(day=1).isoformat()))
    to = date.fromisoformat(ctx.q("to", date.today().isoformat()))
    if (to - frm).days > 62:
        raise unprocessable("At most 62 days per request", "RANGE_TOO_LARGE")
    scope_sql, params = ctx.employee_filter("attendance.read")
    where = ["e.tenant_id = ?", scope_sql, "(e.status = 'active' OR e.deactivated_at >= ?)"]
    p = [ctx.tenant_id, *params, frm.isoformat()]
    for col, name in (("e.department_id", "department_id"), ("e.site_id", "site_id"), ("e.team", "team"),
                      ("e.id", "employee_id")):
        vals = ctx.qlist(name)
        if vals:
            where.append(f"{col} IN ({','.join('?' * len(vals))})")
            p += vals
    limit, offset = page_params(ctx, 500)
    total = dbm.scalar(ctx.conn, f"SELECT COUNT(*) FROM employees e WHERE {' AND '.join(where)}", p)
    emps = dbm.all_(ctx.conn, f"SELECT e.id, e.personnel_no, e.last_name, e.first_name, e.department_id, e.site_id, e.team, "
                              f"d.name AS department_name FROM employees e LEFT JOIN departments d ON d.id = e.department_id "
                              f"WHERE {' AND '.join(where)} ORDER BY d.name, e.last_name LIMIT ? OFFSET ?",
                    [*p, limit, offset])
    ids = [e["id"] for e in emps]
    days: dict[str, dict] = {e["id"]: {} for e in emps}
    if ids:
        for s in dbm.all_(ctx.conn, f"SELECT * FROM daily_summaries WHERE tenant_id = ? AND work_date BETWEEN ? AND ? "
                                    f"AND employee_id IN ({','.join('?' * len(ids))})",
                          [ctx.tenant_id, frm.isoformat(), to.isoformat(), *ids]):
            days[s["employee_id"]][s["work_date"]] = attendance_svc.summary_view(s)
    totals = {}
    for e in emps:
        rows = days[e["id"]].values()
        totals[e["id"]] = {"worked_min": sum(r["worked_min"] for r in rows),
                           "overtime_min": sum(r["overtime_min"] for r in rows),
                           "late_count": sum(1 for r in rows if r["late_min"] > 0),
                           "absent_count": sum(1 for r in rows if r["status"] == "absent")}
    closed = dbm.all_(ctx.conn, "SELECT site_id, start_date, end_date FROM periods WHERE tenant_id = ? AND status = 'closed' "
                                "AND end_date >= ? AND start_date <= ?", (ctx.tenant_id, frm.isoformat(), to.isoformat()))
    return {"from": frm.isoformat(), "to": to.isoformat(), "employees": emps, "days": days, "totals": totals,
            "total": total, "limit": limit, "offset": offset, "closed_periods": closed}


@route("POST", "/api/v1/attendance/recompute", perm="correction.approve")
def recompute(ctx: Ctx):
    emp_id = ctx.q("employee_id")
    day = date.fromisoformat(ctx.q("date", date.today().isoformat()))
    emp = dbm.one(ctx.conn, "SELECT * FROM employees WHERE id = ? AND tenant_id = ?", (emp_id, ctx.tenant_id))
    if not emp:
        raise not_found("Employee")
    ctx.require_employee("attendance.read", emp)
    row = attendance_svc.recompute(ctx.conn, ctx.tenant_id, emp_id, day)
    return attendance_svc.summary_view(row) if row else {}


# ----------------------------------------------------------------- anomalies (SCR-33)

@route("GET", "/api/v1/attendance/anomalies", perm="attendance.read")
def anomalies(ctx: Ctx):
    scope_sql, params = ctx.employee_filter("attendance.read")
    status = ctx.q("status", "open")
    where = ["a.tenant_id = ?", scope_sql, "a.status = ?"]
    p = [ctx.tenant_id, *params, status]
    kinds = ctx.qlist("kind")
    if kinds:
        where.append(f"a.kind IN ({','.join('?' * len(kinds))})")
        p += kinds
    limit, offset = page_params(ctx)
    total = dbm.scalar(ctx.conn, f"SELECT COUNT(*) FROM anomalies a JOIN employees e ON e.id = a.employee_id "
                                 f"WHERE {' AND '.join(where)}", p)
    rows = dbm.all_(ctx.conn, f"SELECT a.*, e.personnel_no, e.last_name, e.first_name, d.name AS department_name "
                              f"FROM anomalies a JOIN employees e ON e.id = a.employee_id LEFT JOIN departments d "
                              f"ON d.id = e.department_id WHERE {' AND '.join(where)} ORDER BY a.work_date DESC "
                              f"LIMIT ? OFFSET ?", [*p, limit, offset])
    for r in rows:
        r["details"] = loads(r["details"], {})
    return paged(rows, total, limit, offset)


@route("POST", "/api/v1/attendance/anomalies/{id}/resolve", perm="correction.request")
def resolve_anomaly(ctx: Ctx, body: ReviewIn):
    row = dbm.one(ctx.conn, "SELECT a.*, e.site_id, e.department_id, e.team FROM anomalies a JOIN employees e "
                            "ON e.id = a.employee_id WHERE a.id = ? AND a.tenant_id = ?", (ctx.path["id"], ctx.tenant_id))
    if not row:
        raise not_found("Anomaly")
    ctx.require_employee("correction.request", {"id": row["employee_id"]})
    if row["kind"] in ("missing_out", "missing_in", "review_required"):
        raise unprocessable("Resolve this anomaly with a correction or an event review", "USE_CORRECTION")
    ctx.conn.execute("UPDATE anomalies SET status = 'resolved', resolved_at = ? WHERE id = ?", (now_iso(), row["id"]))
    ctx.audit("attendance.anomaly_resolved", "anomaly", row["id"], after={"comment": body.comment})
    return {"ok": True}


# ----------------------------------------------------------------- periods (SCR-36)

@route("GET", "/api/v1/attendance/periods", perm="attendance.read")
def periods(ctx: Ctx):
    allowed = ctx.site_ids("attendance.read")
    rows = dbm.all_(ctx.conn, "SELECT p.*, s.name AS site_name, u.name AS closed_by_name FROM periods p "
                              "JOIN sites s ON s.id = p.site_id LEFT JOIN users u ON u.id = p.closed_by "
                              "WHERE p.tenant_id = ? ORDER BY p.start_date DESC", (ctx.tenant_id,))
    return {"items": [r for r in rows if allowed is None or r["site_id"] in allowed]}


@route("POST", "/api/v1/attendance/periods", perm="period.close")
def create_period(ctx: Ctx, body: PeriodIn):
    ctx.require_site("period.close", body.site_id)
    if body.end_date < body.start_date or (body.end_date - body.start_date).days > 31:
        raise unprocessable("A period is 1–31 days", "PERIOD_RANGE")
    overlap = dbm.one(ctx.conn, "SELECT id FROM periods WHERE tenant_id = ? AND site_id = ? AND start_date <= ? AND "
                                "end_date >= ?", (ctx.tenant_id, body.site_id, body.end_date.isoformat(),
                                                  body.start_date.isoformat()))
    if overlap:
        raise conflict("Period overlaps an existing one", "PERIOD_OVERLAP")
    row = {"id": new_id(), "tenant_id": ctx.tenant_id, "site_id": body.site_id, "start_date": body.start_date.isoformat(),
           "end_date": body.end_date.isoformat(), "status": "open", "created_at": now_iso()}
    dbm.insert(ctx.conn, "periods", row)
    ctx.audit("period.created", "period", row["id"], after=row)
    return 201, row


def period_checklist(ctx: Ctx, period: dict) -> dict:
    t, s = ctx.tenant_id, period["site_id"]
    rng = (period["start_date"], period["end_date"])
    return {
        "open_anomalies": dbm.scalar(ctx.conn, "SELECT COUNT(*) FROM anomalies a JOIN employees e ON e.id = a.employee_id "
                                               "WHERE a.tenant_id = ? AND e.site_id = ? AND a.status = 'open' AND "
                                               "a.work_date BETWEEN ? AND ?", (t, s, *rng)),
        "pending_corrections": dbm.scalar(ctx.conn, "SELECT COUNT(*) FROM corrections c JOIN employees e ON e.id = "
                                                    "c.employee_id WHERE c.tenant_id = ? AND e.site_id = ? AND c.status = "
                                                    "'pending' AND c.work_date BETWEEN ? AND ?", (t, s, *rng)),
        "pending_leaves": dbm.scalar(ctx.conn, "SELECT COUNT(*) FROM leave_requests l JOIN employees e ON e.id = "
                                               "l.employee_id WHERE l.tenant_id = ? AND e.site_id = ? AND l.status = "
                                               "'pending' AND l.start_date <= ? AND l.end_date >= ?", (t, s, rng[1], rng[0])),
        "pending_reviews": dbm.scalar(ctx.conn, "SELECT COUNT(*) FROM attendance_events ev LEFT JOIN event_reviews r ON "
                                                "r.event_id = ev.id WHERE ev.tenant_id = ? AND ev.site_id = ? AND "
                                                "ev.result = 'review' AND r.id IS NULL AND ev.captured_at BETWEEN ? AND ?",
                                      (t, s, rng[0], rng[1] + "T23:59:59Z")),
        "offline_devices": dbm.scalar(ctx.conn, "SELECT COUNT(*) FROM devices WHERE tenant_id = ? AND site_id = ? AND "
                                                "status = 'offline'", (t, s)),
    }


def _get_period(ctx: Ctx) -> dict:
    p = dbm.one(ctx.conn, "SELECT * FROM periods WHERE id = ? AND tenant_id = ?", (ctx.path["id"], ctx.tenant_id))
    if not p:
        raise not_found("Period")
    return p


@route("GET", "/api/v1/attendance/periods/{id}/checklist", perm="period.close")
def checklist(ctx: Ctx):
    p = _get_period(ctx)
    return {"period": p, "checklist": period_checklist(ctx, p)}


@route("POST", "/api/v1/attendance/periods/{id}/close", perm="period.close")
def close_period(ctx: Ctx, body: CloseIn):
    p = _get_period(ctx)
    ctx.require_site("period.close", p["site_id"])
    if p["status"] == "closed":
        raise conflict("Period is already closed", "PERIOD_ALREADY_CLOSED")
    if date.fromisoformat(p["end_date"]) >= date.today():
        raise unprocessable("A period can be closed only after its last day", "PERIOD_NOT_FINISHED")
    cl = period_checklist(ctx, p)
    blocking = {k: v for k, v in cl.items() if v}
    if blocking and not body.force:
        raise conflict("There are open items for this period", "PERIOD_HAS_OPEN_ITEMS", checklist=cl)
    if blocking and not (body.note and len(body.note) >= 10):
        raise unprocessable("Closing with open items needs a note (min 10 characters)", "NOTE_REQUIRED")
    # final recalculation, then freeze
    for e in dbm.all_(ctx.conn, "SELECT id FROM employees WHERE tenant_id = ? AND site_id = ?", (ctx.tenant_id, p["site_id"])):
        d = date.fromisoformat(p["start_date"])
        while d <= date.fromisoformat(p["end_date"]):
            attendance_svc.recompute(ctx.conn, ctx.tenant_id, e["id"], d)
            d += timedelta(days=1)
    dbm.update(ctx.conn, "periods", {"id": p["id"]}, {"status": "closed", "closed_by": ctx.actor, "closed_at": now_iso(),
                                                     "close_note": body.note})
    ctx.audit("period.closed", "period", p["id"], after={"checklist": cl, "note": body.note})
    return {"ok": True, "status": "closed", "checklist": cl}


@route("POST", "/api/v1/attendance/periods/{id}/reopen-request", perm="period.reopen")
def reopen_request(ctx: Ctx, body: ReopenIn):
    p = _get_period(ctx)
    if p["status"] != "closed":
        raise conflict("Only closed periods can be reopened", "PERIOD_NOT_CLOSED")
    dbm.update(ctx.conn, "periods", {"id": p["id"]}, {"status": "reopen_requested", "reopen_requested_by": ctx.actor,
                                                     "reopen_reason": body.reason})
    notify.notify_permission(ctx.conn, ctx.tenant_id, "period.reopen", "period_reopen",
                             "Davrni qayta ochish so'rovi", body.reason, "/app/attendance/periods",
                             site_id=p["site_id"], exclude_user=ctx.actor)
    ctx.audit("period.reopen_requested", "period", p["id"], after={"reason": body.reason})
    return {"ok": True, "status": "reopen_requested", "message": "Ikkinchi HR Manager tasdig'i kutilmoqda"}


@route("POST", "/api/v1/attendance/periods/{id}/reopen-approve", perm="period.reopen")
def reopen_approve(ctx: Ctx):
    p = _get_period(ctx)
    if p["status"] != "reopen_requested":
        raise conflict("No reopen request pending", "NO_REOPEN_REQUEST")
    if p["reopen_requested_by"] == ctx.actor:
        raise forbidden("A second HR Manager must approve reopening", "SELF_APPROVAL_FORBIDDEN")
    dbm.update(ctx.conn, "periods", {"id": p["id"]}, {"status": "open", "closed_at": None})
    ctx.audit("period.reopened", "period", p["id"], after={"requested_by": p["reopen_requested_by"],
                                                           "reason": p["reopen_reason"]})
    broker.publish(f"tenant:{ctx.tenant_id}", {"type": "period", "id": p["id"], "status": "open"})
    return {"ok": True, "status": "open", "payroll_note": "Payroll tizimiga 'tuzatilgan' belgisi bilan qayta eksport qiling"}


@route("POST", "/api/v1/attendance/periods/{id}/reopen-cancel", perm="period.reopen")
def reopen_cancel(ctx: Ctx):
    p = _get_period(ctx)
    if p["status"] != "reopen_requested":
        raise conflict("No reopen request pending", "NO_REOPEN_REQUEST")
    dbm.update(ctx.conn, "periods", {"id": p["id"]}, {"status": "closed"})
    ctx.audit("period.reopen_cancelled", "period", p["id"])
    return {"ok": True, "status": "closed"}
