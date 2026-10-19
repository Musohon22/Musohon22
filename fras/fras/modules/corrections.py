"""Attendance corrections with maker-checker approval, disputes, bulk corrections (SCR-34, SCR-35)."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field, model_validator

from .. import db as dbm
from ..errors import conflict, forbidden, locked, not_found, unprocessable
from ..http import Ctx, page_params, paged, route
from ..services import attendance_svc, notify, settings_svc
from ..util import iso, new_id, now_iso, parse_dt

REASONS = ("device_failure", "card_forgotten", "business_task", "missed_checkout", "other")


class CorrectionIn(BaseModel):
    employee_id: str
    work_date: date
    kind: str = Field(pattern="^(add_event|void_event|change_time|set_day_status)$")
    event_id: str | None = None
    new_time: datetime | None = None
    direction: str | None = Field(default=None, pattern="^(in|out)$")
    day_status: str | None = Field(default=None, pattern="^(present|business_trip|remote|absent|leave)$")
    reason_code: str = Field(pattern="^(" + "|".join(REASONS) + ")$")
    comment: str = Field(min_length=15, max_length=1000)

    @model_validator(mode="after")
    def by_kind(self):
        if self.kind == "add_event" and not (self.new_time and self.direction):
            raise ValueError("add_event needs new_time and direction")
        if self.kind in ("void_event", "change_time") and not self.event_id:
            raise ValueError(f"{self.kind} needs event_id")
        if self.kind == "change_time" and not self.new_time:
            raise ValueError("change_time needs new_time")
        if self.kind == "set_day_status" and not self.day_status:
            raise ValueError("set_day_status needs day_status")
        return self


class DecisionIn(BaseModel):
    comment: str | None = Field(default=None, max_length=500)


class RejectIn(BaseModel):
    comment: str = Field(min_length=10, max_length=500)


class BulkDecisionIn(BaseModel):
    ids: list[str] = Field(min_length=1, max_length=100)


class BulkCorrectionIn(BaseModel):
    """COR-03: e.g. a device failure day — add the planned check-in/out for many employees."""
    employee_ids: list[str] = Field(min_length=1, max_length=500)
    work_date: date
    add_planned_in: bool = True
    add_planned_out: bool = True
    reason_code: str = Field(pattern="^(" + "|".join(REASONS) + ")$")
    comment: str = Field(min_length=15, max_length=1000)


def create_correction(ctx: Ctx, body: CorrectionIn, source: str = "hr") -> dict:
    emp = dbm.one(ctx.conn, "SELECT * FROM employees WHERE id = ? AND tenant_id = ?", (body.employee_id, ctx.tenant_id))
    if not emp:
        raise not_found("Employee")
    if source == "hr":
        ctx.require_employee("correction.request", emp)
    if body.work_date > date.today():
        raise unprocessable("Cannot correct a future day", "FUTURE_DATE")
    if attendance_svc.period_closed(ctx.conn, ctx.tenant_id, emp["site_id"], body.work_date):
        raise locked("This day belongs to a closed period. Ask HR Manager to reopen it.", "PERIOD_LOCKED")
    if body.event_id:
        ev = dbm.one(ctx.conn, "SELECT * FROM attendance_events WHERE id = ? AND tenant_id = ? AND employee_id = ?",
                     (body.event_id, ctx.tenant_id, emp["id"]))
        if not ev:
            raise unprocessable("Event does not belong to this employee", "EVENT_INVALID")
    if body.new_time:
        nt = body.new_time if body.new_time.tzinfo else body.new_time.replace(
            tzinfo=ZoneInfo(attendance_svc.site_zone(ctx.conn, emp["site_id"])))
        anchor = datetime(body.work_date.year, body.work_date.month, body.work_date.day, 12, tzinfo=nt.tzinfo)
        if abs(nt - anchor) > timedelta(hours=36):
            raise unprocessable("New time must be within the work day window (±36 h)", "TIME_OUT_OF_WINDOW")
        body.new_time = nt
    clash = dbm.one(ctx.conn, "SELECT id FROM corrections WHERE tenant_id = ? AND employee_id = ? AND work_date = ? AND "
                              "status = 'pending' AND kind = ? AND COALESCE(event_id, '') = COALESCE(?, '')",
                    (ctx.tenant_id, emp["id"], body.work_date.isoformat(), body.kind, body.event_id))
    if clash:
        raise conflict("An identical correction is already pending", "CORRECTION_CONFLICT", id=clash["id"])
    row = {"id": new_id(), "tenant_id": ctx.tenant_id, "employee_id": emp["id"], "work_date": body.work_date.isoformat(),
           "kind": body.kind, "event_id": body.event_id, "new_time": iso(body.new_time) if body.new_time else None,
           "direction": body.direction, "day_status": body.day_status, "reason_code": body.reason_code,
           "comment": body.comment, "source": source, "status": "pending", "requested_by": ctx.actor,
           "decided_by": None, "decided_at": None, "decision_comment": None, "created_at": now_iso()}
    dbm.insert(ctx.conn, "corrections", row)
    n = notify.notify_permission(ctx.conn, ctx.tenant_id, "correction.approve", "correction_pending",
                                 "Tuzatish tasdiqlashni kutmoqda",
                                 f"{emp['last_name']} {emp['first_name']}, {body.work_date.strftime('%d.%m.%Y')}",
                                 "/app/approvals", site_id=emp["site_id"], exclude_user=ctx.actor)
    ctx.audit("correction.requested", "correction", row["id"], after=row)
    row["approvers_notified"] = n
    return row


def preview(ctx: Ctx, body: CorrectionIn) -> dict:
    """What the day would look like if this correction were approved (computed, not stored)."""
    from ..engine.attendance import Correction, Event, compute_day
    emp = dbm.one(ctx.conn, "SELECT * FROM employees WHERE id = ? AND tenant_id = ?", (body.employee_id, ctx.tenant_id))
    if not emp:
        raise not_found("Employee")
    zone = attendance_svc.site_zone(ctx.conn, emp["site_id"])
    rules = settings_svc.get(ctx.conn, ctx.tenant_id, "attendance_rules")
    raw = attendance_svc.events_for_work_date(ctx.conn, ctx.tenant_id, emp, body.work_date)
    events = [Event(id=e["id"], at=parse_dt(e["captured_at"]), direction=e["direction"], result=e["result"],
                    review=e["review"]) for e in raw]
    approved = [Correction(kind=c["kind"], event_id=c["event_id"], at=parse_dt(c["new_time"]), direction=c["direction"],
                           day_status=c["day_status"])
                for c in dbm.all_(ctx.conn, "SELECT * FROM corrections WHERE tenant_id = ? AND employee_id = ? AND "
                                            "work_date = ? AND status = 'approved'",
                                  (ctx.tenant_id, emp["id"], body.work_date.isoformat()))]
    new_time = body.new_time
    if new_time and not new_time.tzinfo:
        new_time = new_time.replace(tzinfo=ZoneInfo(zone))
    proposed = Correction(kind=body.kind, event_id=body.event_id, at=new_time, direction=body.direction,
                          day_status=body.day_status)
    shift = attendance_svc.shift_for(ctx.conn, ctx.tenant_id, emp["id"], body.work_date)
    kwargs = dict(work_date=body.work_date, zone=zone, shift=shift,
                  holiday=attendance_svc.is_holiday(ctx.conn, ctx.tenant_id, emp["site_id"], body.work_date),
                  events=events, leave=attendance_svc.leave_on(ctx.conn, ctx.tenant_id, emp["id"], body.work_date),
                  debounce_min=rules["debounce_min"], missing_out_after_min=rules["missing_out_after_min"],
                  now=datetime.now().astimezone())
    before = compute_day(corrections=approved, **kwargs)
    after = compute_day(corrections=approved + [proposed], **kwargs)
    pick = lambda s: {"status": s.status, "worked_min": s.worked_min, "late_min": s.late_min,  # noqa: E731
                      "overtime_min": s.overtime_min, "explanation": s.explanation}
    return {"before": pick(before), "after": pick(after)}


@route("POST", "/api/v1/attendance/corrections/preview", perm="correction.request")
def preview_route(ctx: Ctx, body: CorrectionIn):
    return preview(ctx, body)


@route("POST", "/api/v1/attendance/corrections", perm="correction.request")
def create(ctx: Ctx, body: CorrectionIn):
    row = create_correction(ctx, body)
    return 201, row


@route("GET", "/api/v1/attendance/corrections", perm="attendance.read")
def list_corrections(ctx: Ctx):
    scope_sql, params = ctx.employee_filter("attendance.read")
    where = ["c.tenant_id = ?", scope_sql]
    p = [ctx.tenant_id, *params]
    if ctx.q("status"):
        where.append("c.status = ?")
        p.append(ctx.q("status"))
    if ctx.q("employee_id"):
        where.append("c.employee_id = ?")
        p.append(ctx.q("employee_id"))
    limit, offset = page_params(ctx)
    total = dbm.scalar(ctx.conn, f"SELECT COUNT(*) FROM corrections c JOIN employees e ON e.id = c.employee_id "
                                 f"WHERE {' AND '.join(where)}", p)
    rows = dbm.all_(ctx.conn, f"SELECT c.*, e.personnel_no, e.last_name, e.first_name, u.name AS requested_by_name, "
                              f"v.name AS decided_by_name FROM corrections c JOIN employees e ON e.id = c.employee_id "
                              f"LEFT JOIN users u ON u.id = c.requested_by LEFT JOIN users v ON v.id = c.decided_by "
                              f"WHERE {' AND '.join(where)} ORDER BY c.created_at DESC LIMIT ? OFFSET ?",
                    [*p, limit, offset])
    return paged(rows, total, limit, offset)


def _load_pending(ctx: Ctx, corr_id: str) -> tuple[dict, dict]:
    c = dbm.one(ctx.conn, "SELECT * FROM corrections WHERE id = ? AND tenant_id = ?", (corr_id, ctx.tenant_id))
    if not c:
        raise not_found("Correction")
    if c["status"] != "pending":
        raise conflict("Correction was already decided", "ALREADY_DECIDED", status=c["status"])
    if c["requested_by"] == ctx.actor:
        raise forbidden("You cannot approve your own request", "SELF_APPROVAL_FORBIDDEN")
    emp = dbm.one(ctx.conn, "SELECT * FROM employees WHERE id = ?", (c["employee_id"],))
    if ctx.p.employee_id and ctx.p.employee_id == emp["id"]:
        raise forbidden("You cannot approve corrections of your own attendance", "SELF_APPROVAL_FORBIDDEN")
    ctx.require_employee("correction.approve", emp)
    return c, emp


def approve_one(ctx: Ctx, corr_id: str, comment: str | None) -> dict:
    c, emp = _load_pending(ctx, corr_id)
    if attendance_svc.period_closed(ctx.conn, ctx.tenant_id, emp["site_id"], date.fromisoformat(c["work_date"])):
        raise locked("The period was closed meanwhile; reopen it first", "PERIOD_LOCKED")
    dbm.update(ctx.conn, "corrections", {"id": c["id"]}, {"status": "approved", "decided_by": ctx.actor,
                                                         "decided_at": now_iso(), "decision_comment": comment})
    summary = attendance_svc.recompute(ctx.conn, ctx.tenant_id, emp["id"], date.fromisoformat(c["work_date"]))
    if c["requested_by"]:
        notify.notify_user(ctx.conn, ctx.tenant_id, c["requested_by"], "correction_decided", "Tuzatish tasdiqlandi",
                           f"{emp['last_name']} {emp['first_name']}, {c['work_date']}", "/app/attendance/corrections")
    if c["source"] == "employee_dispute":
        notify.notify_employee(ctx.conn, ctx.tenant_id, emp["id"], "dispute_decided", "E'tirozingiz qabul qilindi",
                               f"{c['work_date']}: davomat tuzatildi", "/me/attendance")
    ctx.audit("correction.approved", "correction", c["id"], before={"status": "pending"},
              after={"status": "approved", "comment": comment})
    return {"ok": True, "status": "approved", "summary": attendance_svc.summary_view(summary) if summary else None}


@route("POST", "/api/v1/attendance/corrections/{id}/approve", perm="correction.approve")
def approve(ctx: Ctx, body: DecisionIn):
    return approve_one(ctx, ctx.path["id"], body.comment)


@route("POST", "/api/v1/attendance/corrections/{id}/reject", perm="correction.approve")
def reject(ctx: Ctx, body: RejectIn):
    c, emp = _load_pending(ctx, ctx.path["id"])
    dbm.update(ctx.conn, "corrections", {"id": c["id"]}, {"status": "rejected", "decided_by": ctx.actor,
                                                         "decided_at": now_iso(), "decision_comment": body.comment})
    if c["requested_by"]:
        notify.notify_user(ctx.conn, ctx.tenant_id, c["requested_by"], "correction_decided", "Tuzatish rad etildi",
                           body.comment, "/app/attendance/corrections")
    if c["source"] == "employee_dispute":
        notify.notify_employee(ctx.conn, ctx.tenant_id, emp["id"], "dispute_decided", "E'tirozingiz rad etildi",
                               body.comment, "/me/requests")
    ctx.audit("correction.rejected", "correction", c["id"], after={"comment": body.comment})
    return {"ok": True, "status": "rejected"}


@route("POST", "/api/v1/attendance/corrections/bulk-approve", perm="correction.approve")
def bulk_approve(ctx: Ctx, body: BulkDecisionIn):
    approved, skipped = 0, []
    for cid in body.ids:
        try:
            ctx.conn.execute("SAVEPOINT one")
            approve_one(ctx, cid, "bulk")
            ctx.conn.execute("RELEASE one")
            approved += 1
        except Exception as e:  # noqa: BLE001 - report per-item outcome
            ctx.conn.execute("ROLLBACK TO one")
            ctx.conn.execute("RELEASE one")
            skipped.append({"id": cid, "reason": getattr(e, "code", "error")})
    return {"approved": approved, "skipped": skipped}


@route("POST", "/api/v1/attendance/corrections/bulk", perm="correction.request")
def bulk_correction(ctx: Ctx, body: BulkCorrectionIn):
    created, skipped = 0, []
    for emp_id in body.employee_ids:
        emp = dbm.one(ctx.conn, "SELECT * FROM employees WHERE id = ? AND tenant_id = ?", (emp_id, ctx.tenant_id))
        if not emp:
            skipped.append({"id": emp_id, "reason": "not_found"})
            continue
        shift = attendance_svc.shift_for(ctx.conn, ctx.tenant_id, emp_id, body.work_date)
        if not shift:
            skipped.append({"id": emp_id, "reason": "no_shift"})
            continue
        start, end = shift.planned(body.work_date, attendance_svc.site_zone(ctx.conn, emp["site_id"]))
        for flag, direction, at in ((body.add_planned_in, "in", start), (body.add_planned_out, "out", end)):
            if not flag:
                continue
            try:
                ctx.conn.execute("SAVEPOINT one")
                create_correction(ctx, CorrectionIn(employee_id=emp_id, work_date=body.work_date, kind="add_event",
                                                    new_time=at, direction=direction, reason_code=body.reason_code,
                                                    comment=f"[bulk] {body.comment}"))
                ctx.conn.execute("RELEASE one")
                created += 1
            except Exception as e:  # noqa: BLE001
                ctx.conn.execute("ROLLBACK TO one")
                ctx.conn.execute("RELEASE one")
                skipped.append({"id": emp_id, "reason": getattr(e, "code", "error")})
    ctx.audit("correction.bulk_requested", "correction", None, after={"created": created, "skipped": len(skipped),
                                                                      "work_date": body.work_date.isoformat()})
    return {"created": created, "skipped": skipped, "note": "Ikki bosqichli tasdiq: har bir so'rov alohida tasdiqlanadi"}


# ----------------------------------------------------------------- approvals queue (SCR-35)

@route("GET", "/api/v1/approvals", perm="attendance.read")
def approvals(ctx: Ctx):
    items = []
    if ctx.can("correction.approve"):
        scope_sql, params = ctx.employee_filter("correction.approve")
        for c in dbm.all_(ctx.conn, f"SELECT c.*, e.personnel_no, e.last_name, e.first_name, u.name AS requested_by_name "
                                    f"FROM corrections c JOIN employees e ON e.id = c.employee_id LEFT JOIN users u "
                                    f"ON u.id = c.requested_by WHERE c.tenant_id = ? AND c.status = 'pending' AND "
                                    f"{scope_sql} ORDER BY c.created_at", [ctx.tenant_id, *params]):
            items.append({"type": "dispute" if c["source"] == "employee_dispute" else "correction", "id": c["id"],
                          "employee_id": c["employee_id"], "employee": f"{c['last_name']} {c['first_name']}",
                          "personnel_no": c["personnel_no"], "date": c["work_date"], "kind": c["kind"],
                          "comment": c["comment"], "reason_code": c["reason_code"],
                          "requested_by": c["requested_by_name"], "created_at": c["created_at"],
                          "own": c["requested_by"] == ctx.actor,
                          "sla_due": iso(parse_dt(c["created_at"]) + timedelta(days=3))})
    if ctx.can("leave.approve"):
        scope_sql, params = ctx.employee_filter("leave.approve")
        for lv in dbm.all_(ctx.conn, f"SELECT l.*, e.personnel_no, e.last_name, e.first_name, u.name AS requested_by_name "
                                     f"FROM leave_requests l JOIN employees e ON e.id = l.employee_id LEFT JOIN users u "
                                     f"ON u.id = l.requested_by WHERE l.tenant_id = ? AND l.status = 'pending' AND "
                                     f"{scope_sql} ORDER BY l.created_at", [ctx.tenant_id, *params]):
            items.append({"type": "leave", "id": lv["id"], "employee_id": lv["employee_id"],
                          "employee": f"{lv['last_name']} {lv['first_name']}", "personnel_no": lv["personnel_no"],
                          "date": lv["start_date"], "end_date": lv["end_date"], "kind": lv["type"],
                          "comment": lv["reason"], "requested_by": lv["requested_by_name"],
                          "created_at": lv["created_at"], "own": lv["requested_by"] == ctx.actor})
    items.sort(key=lambda x: x["created_at"])
    return {"items": items, "counts": {t: sum(1 for i in items if i["type"] == t) for t in ("correction", "dispute", "leave")}}
