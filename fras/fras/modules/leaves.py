"""Leave and absence requests (vacation, sick leave, business trip, hourly permission) — SCR-46, LEV-01/02."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field, model_validator

from .. import db as dbm
from ..errors import conflict, forbidden, not_found, unprocessable
from ..http import Ctx, page_params, paged, route
from ..services import attendance_svc, notify
from ..util import daterange, local_today, new_id, now_iso

TYPES = {"vacation": "Mehnat ta'tili", "sick": "Kasallik varaqasi", "business_trip": "Xizmat safari",
         "unpaid": "O'z hisobidan ta'til", "permission": "Soatbay ruxsat"}
ANNUAL_VACATION_DAYS = 21   # default entitlement; per-employee overrides are a later feature


class LeaveIn(BaseModel):
    employee_id: str
    type: str = Field(pattern="^(vacation|sick|business_trip|unpaid|permission)$")
    start_date: date
    end_date: date
    start_time: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    end_time: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    reason: str = Field(min_length=3, max_length=1000)

    @model_validator(mode="after")
    def check(self):
        if self.end_date < self.start_date:
            raise ValueError("end_date before start_date")
        if (self.end_date - self.start_date).days > 180:
            raise ValueError("at most 180 days per request")
        if self.type == "permission":
            if not (self.start_time and self.end_time) or self.start_date != self.end_date:
                raise ValueError("hourly permission needs one date and start/end time")
        return self


class DecisionIn(BaseModel):
    comment: str | None = Field(default=None, max_length=500)


class RejectIn(BaseModel):
    comment: str = Field(min_length=10, max_length=500)


def used_vacation_days(conn, tenant_id: str, employee_id: str, year: int) -> int:
    used = 0
    for lv in dbm.all_(conn, "SELECT start_date, end_date FROM leave_requests WHERE tenant_id = ? AND employee_id = ? "
                             "AND type = 'vacation' AND status IN ('approved','pending') AND start_date <= ? AND "
                             "end_date >= ?", (tenant_id, employee_id, f"{year}-12-31", f"{year}-01-01")):
        for d in daterange(date.fromisoformat(lv["start_date"]), date.fromisoformat(lv["end_date"])):
            if d.year == year:
                used += 1
    return used


def create_leave(ctx: Ctx, body: LeaveIn, self_service: bool = False) -> dict:
    emp = dbm.one(ctx.conn, "SELECT * FROM employees WHERE id = ? AND tenant_id = ?", (body.employee_id, ctx.tenant_id))
    if not emp:
        raise not_found("Employee")
    if not self_service:
        ctx.require_employee("leave.request", emp)
    overlap = dbm.one(ctx.conn, "SELECT id, type, start_date, end_date FROM leave_requests WHERE tenant_id = ? AND "
                                "employee_id = ? AND status IN ('pending','approved') AND start_date <= ? AND end_date >= ?",
                      (ctx.tenant_id, emp["id"], body.end_date.isoformat(), body.start_date.isoformat()))
    if overlap:
        raise conflict("Overlaps another request", "LEAVE_OVERLAP", existing=overlap)
    if body.type == "vacation":
        days = (body.end_date - body.start_date).days + 1
        used = used_vacation_days(ctx.conn, ctx.tenant_id, emp["id"], body.start_date.year)
        if used + days > ANNUAL_VACATION_DAYS:
            raise unprocessable(f"Not enough vacation balance: {ANNUAL_VACATION_DAYS - used} days left",
                                "LEAVE_BALANCE", remaining=ANNUAL_VACATION_DAYS - used)
    row = {"id": new_id(), "tenant_id": ctx.tenant_id, "employee_id": emp["id"], "type": body.type,
           "start_date": body.start_date.isoformat(), "end_date": body.end_date.isoformat(),
           "start_time": body.start_time, "end_time": body.end_time, "reason": body.reason, "status": "pending",
           "requested_by": ctx.actor, "decided_by": None, "decided_at": None, "decision_comment": None,
           "created_at": now_iso()}
    dbm.insert(ctx.conn, "leave_requests", row)
    notify.notify_permission(ctx.conn, ctx.tenant_id, "leave.approve", "leave_pending", "Ta'til so'rovi",
                             f"{emp['last_name']} {emp['first_name']}: {TYPES[body.type]} "
                             f"{body.start_date.strftime('%d.%m')}–{body.end_date.strftime('%d.%m')}",
                             "/app/approvals", site_id=emp["site_id"], exclude_user=ctx.actor)
    ctx.audit("leave.requested", "leave", row["id"], after=row)
    return row


@route("GET", "/api/v1/leaves/types", perm="org.read")
def types(ctx: Ctx):
    return {"items": [{"code": k, "name": v} for k, v in TYPES.items()], "annual_vacation_days": ANNUAL_VACATION_DAYS}


@route("GET", "/api/v1/leaves", perm="attendance.read")
def list_leaves(ctx: Ctx):
    scope_sql, params = ctx.employee_filter("attendance.read")
    where = ["l.tenant_id = ?", scope_sql]
    p = [ctx.tenant_id, *params]
    for col, name in (("l.status", "status"), ("l.type", "type"), ("l.employee_id", "employee_id")):
        if ctx.q(name):
            where.append(f"{col} = ?")
            p.append(ctx.q(name))
    if ctx.q("from"):
        where.append("l.end_date >= ?")
        p.append(ctx.q("from"))
    if ctx.q("to"):
        where.append("l.start_date <= ?")
        p.append(ctx.q("to"))
    limit, offset = page_params(ctx)
    total = dbm.scalar(ctx.conn, f"SELECT COUNT(*) FROM leave_requests l JOIN employees e ON e.id = l.employee_id "
                                 f"WHERE {' AND '.join(where)}", p)
    rows = dbm.all_(ctx.conn, f"SELECT l.*, e.personnel_no, e.last_name, e.first_name, d.name AS department_name "
                              f"FROM leave_requests l JOIN employees e ON e.id = l.employee_id LEFT JOIN departments d "
                              f"ON d.id = e.department_id WHERE {' AND '.join(where)} ORDER BY l.start_date DESC "
                              f"LIMIT ? OFFSET ?", [*p, limit, offset])
    return paged(rows, total, limit, offset)


@route("POST", "/api/v1/leaves", perm="leave.request")
def create(ctx: Ctx, body: LeaveIn):
    return 201, create_leave(ctx, body)


def _pending(ctx: Ctx) -> tuple[dict, dict]:
    lv = dbm.one(ctx.conn, "SELECT * FROM leave_requests WHERE id = ? AND tenant_id = ?", (ctx.path["id"], ctx.tenant_id))
    if not lv:
        raise not_found("Leave request")
    if lv["status"] != "pending":
        raise conflict("Request was already decided", "ALREADY_DECIDED")
    if lv["requested_by"] == ctx.actor:
        raise forbidden("You cannot approve your own request", "SELF_APPROVAL_FORBIDDEN")
    emp = dbm.one(ctx.conn, "SELECT * FROM employees WHERE id = ?", (lv["employee_id"],))
    if ctx.p.employee_id == emp["id"]:
        raise forbidden("You cannot approve your own leave", "SELF_APPROVAL_FORBIDDEN")
    ctx.require_employee("leave.approve", emp)
    return lv, emp


def _recompute_range(ctx: Ctx, lv: dict) -> None:
    for d in daterange(date.fromisoformat(lv["start_date"]), min(date.fromisoformat(lv["end_date"]), local_today())):
        attendance_svc.recompute(ctx.conn, ctx.tenant_id, lv["employee_id"], d)


@route("POST", "/api/v1/leaves/{id}/approve", perm="leave.approve")
def approve(ctx: Ctx, body: DecisionIn):
    lv, emp = _pending(ctx)
    dbm.update(ctx.conn, "leave_requests", {"id": lv["id"]}, {"status": "approved", "decided_by": ctx.actor,
                                                             "decided_at": now_iso(), "decision_comment": body.comment})
    _recompute_range(ctx, lv)
    notify.notify_employee(ctx.conn, ctx.tenant_id, emp["id"], "leave_decided", "So'rovingiz tasdiqlandi",
                           f"{TYPES[lv['type']]}: {lv['start_date']} – {lv['end_date']}", "/me/requests")
    ctx.audit("leave.approved", "leave", lv["id"], after={"comment": body.comment})
    return {"ok": True, "status": "approved"}


@route("POST", "/api/v1/leaves/{id}/reject", perm="leave.approve")
def reject(ctx: Ctx, body: RejectIn):
    lv, emp = _pending(ctx)
    dbm.update(ctx.conn, "leave_requests", {"id": lv["id"]}, {"status": "rejected", "decided_by": ctx.actor,
                                                             "decided_at": now_iso(), "decision_comment": body.comment})
    notify.notify_employee(ctx.conn, ctx.tenant_id, emp["id"], "leave_decided", "So'rovingiz rad etildi", body.comment,
                           "/me/requests")
    ctx.audit("leave.rejected", "leave", lv["id"], after={"comment": body.comment})
    return {"ok": True, "status": "rejected"}


@route("POST", "/api/v1/leaves/{id}/cancel", perm="leave.request")
def cancel(ctx: Ctx):
    lv = dbm.one(ctx.conn, "SELECT * FROM leave_requests WHERE id = ? AND tenant_id = ?", (ctx.path["id"], ctx.tenant_id))
    if not lv:
        raise not_found("Leave request")
    if lv["status"] not in ("pending", "approved"):
        raise conflict("Request cannot be cancelled", "NOT_CANCELLABLE")
    emp = dbm.one(ctx.conn, "SELECT * FROM employees WHERE id = ?", (lv["employee_id"],))
    ctx.require_employee("leave.request", emp)
    dbm.update(ctx.conn, "leave_requests", {"id": lv["id"]}, {"status": "cancelled"})
    if lv["status"] == "approved":
        _recompute_range(ctx, lv)
    ctx.audit("leave.cancelled", "leave", lv["id"])
    return {"ok": True}


@route("GET", "/api/v1/leaves/balance/{employee_id}", perm="attendance.read")
def balance(ctx: Ctx):
    emp = dbm.one(ctx.conn, "SELECT * FROM employees WHERE id = ? AND tenant_id = ?", (ctx.path["employee_id"], ctx.tenant_id))
    if not emp:
        raise not_found("Employee")
    ctx.require_employee("attendance.read", emp)
    year = ctx.q("year", local_today().year, int)
    used = used_vacation_days(ctx.conn, ctx.tenant_id, emp["id"], year)
    return {"year": year, "entitled": ANNUAL_VACATION_DAYS, "used_or_pending": used,
            "remaining": ANNUAL_VACATION_DAYS - used}
