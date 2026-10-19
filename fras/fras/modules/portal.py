"""Employee self-service portal (SCR-P0 … SCR-P8)."""

from __future__ import annotations

from calendar import monthrange
from datetime import date, datetime, timedelta

from pydantic import BaseModel, Field
from starlette.responses import Response

from .. import db as dbm
from ..errors import conflict, forbidden, locked, not_found, unprocessable
from ..http import Ctx, route
from ..security import tokens
from ..services import attendance_svc, biometric_svc, notify, report_svc
from ..util import iso, local_today, new_id, now_iso, token, utcnow
from .corrections import CorrectionIn, create_correction
from .leaves import TYPES, LeaveIn, create_leave, used_vacation_days, ANNUAL_VACATION_DAYS


class SelfLeaveIn(BaseModel):
    type: str = Field(pattern="^(vacation|sick|business_trip|unpaid|permission)$")
    start_date: date
    end_date: date
    start_time: str | None = None
    end_time: str | None = None
    reason: str = Field(min_length=3, max_length=1000)


class DisputeIn(BaseModel):
    work_date: date
    kind: str = Field(pattern="^(add_event|change_time|set_day_status)$")
    event_id: str | None = None
    new_time: datetime | None = None
    direction: str | None = Field(default=None, pattern="^(in|out)$")
    day_status: str | None = Field(default=None, pattern="^(business_trip|remote)$")
    comment: str = Field(min_length=10, max_length=1000)


class WithdrawIn(BaseModel):
    understood: bool


def _me(ctx: Ctx) -> dict:
    ctx.require("self.read")
    if not ctx.p.employee_id:
        raise forbidden("This account is not linked to an employee", "NOT_AN_EMPLOYEE")
    emp = dbm.one(ctx.conn, "SELECT e.*, d.name AS department_name, s.timezone, s.name AS site_name FROM employees e "
                            "JOIN departments d ON d.id = e.department_id JOIN sites s ON s.id = e.site_id WHERE e.id = ?",
                  (ctx.p.employee_id,))
    if not emp:
        raise not_found("Employee")
    return emp


def _shift_view(ctx: Ctx, emp: dict, d: date) -> dict | None:
    code = dbm.scalar(ctx.conn, "SELECT shift_code FROM shift_assignments WHERE tenant_id = ? AND employee_id = ? AND "
                                "work_date = ?", (ctx.tenant_id, emp["id"], d.isoformat()))
    if not code:
        return None
    t = attendance_svc.template_for(ctx.conn, ctx.tenant_id, code, d)
    return {"date": d.isoformat(), "code": code, "name": t["name"], "start": t["start_time"], "end": t["end_time"]}


@route("GET", "/api/v1/portal/home", perm="self.read", mfa_exempt=True)
def home(ctx: Ctx):
    emp = _me(ctx)
    today = local_today(emp["timezone"])
    s = dbm.one(ctx.conn, "SELECT * FROM daily_summaries WHERE employee_id = ? AND work_date = ?", (emp["id"], today.isoformat()))
    month_start = today.replace(day=1)
    rows = dbm.all_(ctx.conn, "SELECT * FROM daily_summaries WHERE employee_id = ? AND work_date BETWEEN ? AND ?",
                    (emp["id"], month_start.isoformat(), today.isoformat()))
    planned = 0
    for d in (month_start + timedelta(days=i) for i in range((today - month_start).days + 1)):
        sh = attendance_svc.shift_for(ctx.conn, ctx.tenant_id, emp["id"], d)
        if sh:
            a, b = sh.planned(d, emp["timezone"])
            planned += int((b - a).total_seconds() // 60)
    next_shift = None
    for i in range(0, 14):
        v = _shift_view(ctx, emp, today + timedelta(days=i))
        if v:
            next_shift = v
            break
    open_requests = dbm.scalar(ctx.conn, "SELECT COUNT(*) FROM leave_requests WHERE employee_id = ? AND status = 'pending'",
                               (emp["id"],)) + dbm.scalar(ctx.conn, "SELECT COUNT(*) FROM corrections WHERE employee_id = ? "
                                                                    "AND status = 'pending'", (emp["id"],))
    return {"employee": {"name": f"{emp['first_name']} {emp['last_name']}", "personnel_no": emp["personnel_no"],
                         "department": emp["department_name"], "site": emp["site_name"],
                         "biometric_status": emp["biometric_status"], "timezone": emp["timezone"]},
            "today": attendance_svc.summary_view(s) if s else None, "next_shift": next_shift,
            "month": {"worked_min": sum(r["worked_min"] for r in rows), "planned_min": planned,
                      "late_count": sum(1 for r in rows if r["late_min"]),
                      "overtime_min": sum(r["overtime_min"] for r in rows)},
            "open_requests": open_requests}


@route("GET", "/api/v1/portal/attendance", perm="self.read", mfa_exempt=True)
def attendance(ctx: Ctx):
    emp = _me(ctx)
    month = ctx.q("month", local_today(emp["timezone"]).strftime("%Y-%m"))
    y, m = map(int, month.split("-"))
    start, end = date(y, m, 1), date(y, m, monthrange(y, m)[1])
    sums = {r["work_date"]: attendance_svc.summary_view(r) for r in dbm.all_(
        ctx.conn, "SELECT * FROM daily_summaries WHERE employee_id = ? AND work_date BETWEEN ? AND ? ORDER BY work_date",
        (emp["id"], start.isoformat(), end.isoformat()))}
    events = dbm.all_(ctx.conn, "SELECT ev.id, ev.captured_at, ev.direction, ev.method, ev.result, ap.name AS gate "
                                "FROM attendance_events ev LEFT JOIN access_points ap ON ap.id = ev.access_point_id WHERE "
                                "ev.employee_id = ? AND ev.captured_at >= ? AND ev.captured_at < ? ORDER BY ev.captured_at",
                      (emp["id"], (start - timedelta(days=1)).isoformat(), (end + timedelta(days=2)).isoformat()))
    disputes = dbm.all_(ctx.conn, "SELECT work_date, status FROM corrections WHERE employee_id = ? AND source = "
                                  "'employee_dispute' AND work_date BETWEEN ? AND ?", (emp["id"], start.isoformat(),
                                                                                       end.isoformat()))
    closed = attendance_svc.period_closed
    days = []
    for d in (start + timedelta(days=i) for i in range((end - start).days + 1)):
        days.append({"date": d.isoformat(), "summary": sums.get(d.isoformat()),
                     "can_dispute": d <= local_today(emp["timezone"]) and (local_today(emp["timezone"]) - d).days <= 30 and
                     not closed(ctx.conn, ctx.tenant_id, emp["site_id"], d),
                     "dispute": next((x["status"] for x in disputes if x["work_date"] == d.isoformat()), None)})
    return {"month": month, "timezone": emp["timezone"], "days": days, "events": events}


@route("GET", "/api/v1/portal/schedule", perm="self.read", mfa_exempt=True)
def schedule(ctx: Ctx):
    emp = _me(ctx)
    start = date.fromisoformat(ctx.q("from", local_today(emp["timezone"]).isoformat()))
    days = []
    for i in range(min(ctx.q("days", 28, int), 62)):
        d = start + timedelta(days=i)
        days.append({"date": d.isoformat(), "shift": _shift_view(ctx, emp, d),
                     "holiday": attendance_svc.is_holiday(ctx.conn, ctx.tenant_id, emp["site_id"], d)})
    return {"days": days}


@route("GET", "/api/v1/portal/hours", perm="self.read", mfa_exempt=True)
def hours(ctx: Ctx):
    emp = _me(ctx)
    year = ctx.q("year", local_today(emp["timezone"]).year, int)
    rows = dbm.all_(ctx.conn, "SELECT substr(work_date, 1, 7) AS month, SUM(worked_min) AS worked_min, SUM(overtime_min) "
                              "AS overtime_min, SUM(CASE WHEN late_min > 0 THEN 1 ELSE 0 END) AS late_count, "
                              "SUM(CASE WHEN worked_min > 0 THEN 1 ELSE 0 END) AS days FROM daily_summaries WHERE "
                              "employee_id = ? AND work_date LIKE ? GROUP BY month ORDER BY month", (emp["id"], f"{year}-%"))
    return {"year": year, "months": rows,
            "vacation": {"entitled": ANNUAL_VACATION_DAYS,
                         "used_or_pending": used_vacation_days(ctx.conn, ctx.tenant_id, emp["id"], year)}}


@route("GET", "/api/v1/portal/hours.pdf", perm="self.read", mfa_exempt=True)
def hours_pdf(ctx: Ctx):
    emp = _me(ctx)
    month = ctx.q("month", local_today(emp["timezone"]).strftime("%Y-%m"))
    report = report_svc.run(ctx.conn, ctx.tenant_id, "timesheet", {"month": month}, ("e.id = ?", [emp["id"]]),
                            emp["timezone"])
    data, mime, _ = report_svc.render(report, "pdf", f"{emp['last_name']} {emp['first_name']} · {now_iso()}")
    return Response(data, media_type=mime, headers={"Content-Disposition": f"attachment; filename=tabel-{month}.pdf"})


@route("GET", "/api/v1/portal/requests", perm="self.read", mfa_exempt=True)
def requests(ctx: Ctx):
    emp = _me(ctx)
    leaves = dbm.all_(ctx.conn, "SELECT id, type, start_date, end_date, start_time, end_time, reason, status, "
                                "decision_comment, created_at FROM leave_requests WHERE employee_id = ? ORDER BY created_at "
                                "DESC LIMIT 100", (emp["id"],))
    for lv in leaves:
        lv["type_name"] = TYPES.get(lv["type"], lv["type"])
    disputes = dbm.all_(ctx.conn, "SELECT id, work_date, kind, new_time, direction, comment, status, decision_comment, "
                                  "created_at FROM corrections WHERE employee_id = ? AND source = 'employee_dispute' ORDER BY "
                                  "created_at DESC LIMIT 100", (emp["id"],))
    return {"leaves": leaves, "disputes": disputes, "types": TYPES}


@route("POST", "/api/v1/portal/leaves", perm="self.request", mfa_exempt=True)
def request_leave(ctx: Ctx, body: SelfLeaveIn):
    emp = _me(ctx)
    row = create_leave(ctx, LeaveIn(employee_id=emp["id"], **body.model_dump()), self_service=True)
    return 201, row


@route("POST", "/api/v1/portal/disputes", perm="self.request", mfa_exempt=True)
def dispute(ctx: Ctx, body: DisputeIn):
    emp = _me(ctx)
    if (local_today(emp["timezone"]) - body.work_date).days > 30:
        raise unprocessable("Disputes are possible for the last 30 days; contact HR", "DISPUTE_TOO_OLD")
    if attendance_svc.period_closed(ctx.conn, ctx.tenant_id, emp["site_id"], body.work_date):
        raise locked("This period is closed. Contact HR.", "PERIOD_LOCKED")
    corr = CorrectionIn(employee_id=emp["id"], work_date=body.work_date, kind=body.kind, event_id=body.event_id,
                        new_time=body.new_time, direction=body.direction, day_status=body.day_status,
                        reason_code="other", comment=f"[xodim e'tirozi] {body.comment}".ljust(15, "."))
    row = create_correction(ctx, corr, source="employee_dispute")
    return 201, {"id": row["id"], "status": "pending", "sla_due": iso(utcnow() + timedelta(days=3))}


@route("POST", "/api/v1/portal/consent/withdraw", perm="self.request", mfa_exempt=True)
def withdraw(ctx: Ctx, body: WithdrawIn):
    emp = _me(ctx)
    if not body.understood:
        raise unprocessable("Confirm that you understand the consequences", "NOT_CONFIRMED")
    if emp["biometric_status"] in ("none", "declined", "revoked"):
        raise conflict("There is no active biometric profile", "NO_PROFILE")
    biometric_svc.revoke(ctx.conn, ctx.tenant_id, emp["id"], "consent_withdrawn")
    dbm.insert(ctx.conn, "biometric_consents", {"id": new_id(), "tenant_id": ctx.tenant_id, "employee_id": emp["id"],
                                                "decision": "withdrawn", "policy_version": "-", "method": "portal",
                                                "document_hash": None, "recorded_by": ctx.actor, "created_at": now_iso()})
    notify.notify_permission(ctx.conn, ctx.tenant_id, "biometric.enroll", "consent_withdrawn",
                             "Xodim biometrik rozilikni qaytarib oldi",
                             f"{emp['last_name']} {emp['first_name']} ({emp['personnel_no']}): muqobil usul bering",
                             f"/app/employees/{emp['id']}", site_id=emp["site_id"])
    ctx.audit("consent.withdrawn", "employee", emp["id"], after={"via": "portal"})
    return {"ok": True, "message": "Biometrik profilingiz o'chirildi. HR sizga karta/PIN beradi."}


# ----------------------------------------------------------------- HR grants portal access

@route("POST", "/api/v1/employees/{id}/portal-access", perm="employee.write")
def grant_portal(ctx: Ctx):
    emp = dbm.one(ctx.conn, "SELECT * FROM employees WHERE id = ? AND tenant_id = ?", (ctx.path["id"], ctx.tenant_id))
    if not emp:
        raise not_found("Employee")
    ctx.require_employee("employee.write", emp)
    login = emp["personnel_no"].lower()
    existing = dbm.one(ctx.conn, "SELECT id, employee_id FROM users WHERE tenant_id = ? AND login = ?", (ctx.tenant_id, login))
    if existing and existing["employee_id"] != emp["id"]:
        raise conflict("Login is used by another account", "LOGIN_TAKEN")
    t = token(24)
    if existing:
        dbm.update(ctx.conn, "users", {"id": existing["id"]}, {"invite_token_hash": tokens.hash_token(t),
                                                              "invite_expires_at": iso(utcnow() + timedelta(days=7))})
        user_id = existing["id"]
    else:
        user_id = new_id()
        dbm.insert(ctx.conn, "users", {"id": user_id, "tenant_id": ctx.tenant_id, "login": login, "email": None,
                                       "name": f"{emp['last_name']} {emp['first_name']}", "status": "invited",
                                       "mfa_enabled": 0, "employee_id": emp["id"], "language": emp["language"],
                                       "invite_token_hash": tokens.hash_token(t),
                                       "invite_expires_at": iso(utcnow() + timedelta(days=7)), "created_at": now_iso()})
        dbm.insert(ctx.conn, "user_roles", {"id": new_id(), "tenant_id": ctx.tenant_id, "user_id": user_id,
                                            "role_code": "employee", "scope_type": "self", "scope_id": emp["id"],
                                            "valid_until": None, "created_by": ctx.actor, "created_at": now_iso()})
    tenant = dbm.one(ctx.conn, "SELECT slug FROM tenants WHERE id = ?", (ctx.tenant_id,))
    ctx.audit("employee.portal_access_granted", "employee", emp["id"], after={"user_id": user_id})
    return 201, {"login": login, "org": tenant["slug"],
                 "activation_link": f"{ctx.settings.public_base_url}/me/activate?org={tenant['slug']}&token={t}",
                 "expires_in_days": 7}

