"""Shift templates (versioned), rotations, schedule grid, bulk assignment, calendar (SCR-40 … SCR-45)."""

from __future__ import annotations

from datetime import date, timedelta

from pydantic import BaseModel, Field, field_validator, model_validator

from .. import db as dbm
from ..engine.attendance import Shift
from ..errors import conflict, locked, not_found, unprocessable
from ..http import Ctx, route
from ..services import attendance_svc, settings_svc
from ..util import daterange, dumps, loads, local_today, new_id, now_iso

HHMM = r"^([01]\d|2[0-3]):[0-5]\d$"


class BreakIn(BaseModel):
    start: str | None = Field(default=None, pattern=HHMM)
    end: str | None = Field(default=None, pattern=HHMM)
    floating_min: int | None = Field(default=None, ge=5, le=120)
    paid: bool = False

    @model_validator(mode="after")
    def one_kind(self):
        if (self.start is None) == (self.floating_min is None):
            raise ValueError("a break is either fixed (start/end) or floating (floating_min)")
        if self.start is not None and self.end is None:
            raise ValueError("fixed break needs end")
        return self


class TemplateIn(BaseModel):
    code: str = Field(min_length=2, max_length=12, pattern=r"^[A-Za-z0-9\-]+$")
    name: str = Field(min_length=2, max_length=80)
    start_time: str = Field(pattern=HHMM)
    end_time: str = Field(pattern=HHMM)
    breaks: list[BreakIn] = []
    window_before_min: int = Field(default=120, ge=0, le=360)
    window_after_min: int = Field(default=240, ge=0, le=600)
    grace_min: int = Field(default=5, ge=0, le=60)
    early_leave_min: int = Field(default=5, ge=0, le=60)
    overtime_min: int = Field(default=30, ge=0, le=240)
    overtime_round_min: int = Field(default=15, ge=1, le=60)
    overtime_requires_approval: bool = False
    count_early_arrival: bool = False
    color: str = Field(default="blue", pattern="^(blue|green|amber|purple|teal|rose|slate|indigo)$")
    valid_from: date | None = None

    @field_validator("code")
    @classmethod
    def up(cls, v):
        return v.upper()

    @model_validator(mode="after")
    def duration(self):
        s = int(self.start_time[:2]) * 60 + int(self.start_time[3:])
        e = int(self.end_time[:2]) * 60 + int(self.end_time[3:])
        minutes = (e - s) % 1440
        if not 60 <= minutes <= 16 * 60:
            raise ValueError("shift duration must be between 1 and 16 hours")
        for b in self.breaks:
            if b.start:
                bs = (int(b.start[:2]) * 60 + int(b.start[3:]) - s) % 1440
                be = (int(b.end[:2]) * 60 + int(b.end[3:]) - s) % 1440
                if not (0 <= bs < be <= minutes):
                    raise ValueError("fixed breaks must lie inside the shift")
        return self


class RotationIn(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    pattern: list[str] = Field(min_length=2, max_length=56)


class RotationApplyIn(BaseModel):
    employee_ids: list[str] = []
    department_id: str | None = None
    team_offsets: dict[str, int] = {}
    start_date: date
    end_date: date
    preview: bool = True


class CellIn(BaseModel):
    employee_id: str
    work_date: date
    shift_code: str | None = None
    reason: str | None = Field(default=None, max_length=300)


class BulkAssignIn(BaseModel):
    employee_ids: list[str] = []
    department_id: str | None = None
    shift_code: str | None = None
    start_date: date
    end_date: date
    weekdays: list[int] = Field(default=[0, 1, 2, 3, 4])
    preview: bool = True


class CopyWeekIn(BaseModel):
    source_monday: date
    target_monday: date
    employee_ids: list[str] = []
    department_id: str | None = None


class CalendarIn(BaseModel):
    site_id: str
    day: date
    kind: str = Field(pattern="^(holiday|transfer_workday|exception)$")
    name: str = Field(min_length=2, max_length=120)


class CalendarImportIn(BaseModel):
    site_id: str
    days: list[CalendarIn] = Field(max_length=400)


def _latest_templates(ctx: Ctx) -> list[dict]:
    rows = dbm.all_(ctx.conn, "SELECT t.* FROM shift_templates t WHERE t.tenant_id = ? AND t.version = "
                              "(SELECT max(version) FROM shift_templates x WHERE x.tenant_id = t.tenant_id "
                              "AND x.code = t.code) ORDER BY t.code", (ctx.tenant_id,))
    for r in rows:
        r["breaks"] = loads(r["breaks"], [])
        r["assigned_days"] = dbm.scalar(ctx.conn, "SELECT COUNT(*) FROM shift_assignments WHERE tenant_id = ? AND "
                                                  "shift_code = ? AND work_date >= date('now')", (ctx.tenant_id, r["code"]))
    return rows


@route("GET", "/api/v1/shifts/templates", perm="org.read")
def list_templates(ctx: Ctx):
    return {"items": _latest_templates(ctx)}


def _template_row(ctx: Ctx, body: TemplateIn, version: int, valid_from: date) -> dict:
    data = body.model_dump(exclude={"valid_from"})
    crosses = data["end_time"] <= data["start_time"]
    return {"id": new_id(), "tenant_id": ctx.tenant_id, "code": body.code, "version": version,
            "valid_from": valid_from.isoformat(), "name": data["name"], "start_time": data["start_time"],
            "end_time": data["end_time"], "crosses_midnight": 1 if crosses else 0,
            "breaks": dumps([b for b in data["breaks"]]), "window_before_min": data["window_before_min"],
            "window_after_min": data["window_after_min"], "grace_min": data["grace_min"],
            "early_leave_min": data["early_leave_min"], "overtime_min": data["overtime_min"],
            "overtime_round_min": data["overtime_round_min"],
            "overtime_requires_approval": 1 if data["overtime_requires_approval"] else 0,
            "count_early_arrival": 1 if data["count_early_arrival"] else 0, "color": data["color"],
            "status": "active", "created_by": ctx.actor, "created_at": now_iso()}


@route("POST", "/api/v1/shifts/templates", perm="shift.manage")
def create_template(ctx: Ctx, body: TemplateIn):
    if dbm.one(ctx.conn, "SELECT 1 AS x FROM shift_templates WHERE tenant_id = ? AND code = ?", (ctx.tenant_id, body.code)):
        raise conflict("Shift code already exists", "SHIFT_CODE_TAKEN", field="code")
    row = _template_row(ctx, body, 1, date(2000, 1, 1))
    dbm.insert(ctx.conn, "shift_templates", row)
    ctx.audit("shift.template_created", "shift_template", body.code, after=row)
    return 201, {**row, "breaks": loads(row["breaks"])}


@route("PUT", "/api/v1/shifts/templates/{code}", perm="shift.manage")
def new_version(ctx: Ctx, body: TemplateIn):
    code = ctx.path["code"].upper()
    if body.code != code:
        raise unprocessable("Code in body must match URL", "CODE_MISMATCH")
    prev = dbm.one(ctx.conn, "SELECT * FROM shift_templates WHERE tenant_id = ? AND code = ? ORDER BY version DESC LIMIT 1",
                   (ctx.tenant_id, code))
    if not prev:
        raise not_found("Shift template")
    valid_from = body.valid_from or local_today()
    if valid_from < local_today():
        raise unprocessable("A new version can only take effect from today or later", "VALID_FROM_PAST")
    row = _template_row(ctx, body, prev["version"] + 1, valid_from)
    dbm.insert(ctx.conn, "shift_templates", row)
    ctx.audit("shift.template_versioned", "shift_template", code, before=prev, after=row)
    return {**row, "breaks": loads(row["breaks"]), "message": f"Yangi versiya {valid_from.strftime('%d.%m.%Y')} dan amal qiladi"}


@route("GET", "/api/v1/shifts/templates/{code}/versions", perm="org.read")
def versions(ctx: Ctx):
    rows = dbm.all_(ctx.conn, "SELECT * FROM shift_templates WHERE tenant_id = ? AND code = ? ORDER BY version DESC",
                    (ctx.tenant_id, ctx.path["code"].upper()))
    for r in rows:
        r["breaks"] = loads(r["breaks"], [])
    return {"items": rows}


@route("GET", "/api/v1/shifts/rotations", perm="org.read")
def list_rotations(ctx: Ctx):
    rows = dbm.all_(ctx.conn, "SELECT * FROM rotations WHERE tenant_id = ? ORDER BY name", (ctx.tenant_id,))
    for r in rows:
        r["pattern"] = loads(r["pattern"], [])
    return {"items": rows}


@route("POST", "/api/v1/shifts/rotations", perm="shift.manage")
def create_rotation(ctx: Ctx, body: RotationIn):
    codes = {t["code"] for t in _latest_templates(ctx)}
    bad = [p for p in body.pattern if p.upper() != "OFF" and p.upper() not in codes]
    if bad:
        raise unprocessable("Unknown shift codes in pattern", "PATTERN_INVALID", codes=bad)
    row = {"id": new_id(), "tenant_id": ctx.tenant_id, "name": body.name,
           "pattern": dumps([p.upper() for p in body.pattern]), "created_by": ctx.actor, "created_at": now_iso()}
    dbm.insert(ctx.conn, "rotations", row)
    ctx.audit("shift.rotation_created", "rotation", row["id"], after=row)
    return 201, {**row, "pattern": loads(row["pattern"])}


def _target_employees(ctx: Ctx, employee_ids: list[str], department_id: str | None) -> list[dict]:
    scope_sql, params = ctx.employee_filter("shift.assign")
    if employee_ids:
        rows = dbm.all_(ctx.conn, f"SELECT e.* FROM employees e WHERE e.tenant_id = ? AND e.status = 'active' AND "
                                  f"e.id IN ({','.join('?' * len(employee_ids))}) AND {scope_sql}",
                        [ctx.tenant_id, *employee_ids, *params])
    elif department_id:
        rows = dbm.all_(ctx.conn, f"SELECT e.* FROM employees e WHERE e.tenant_id = ? AND e.status = 'active' AND "
                                  f"e.department_id = ? AND {scope_sql}", [ctx.tenant_id, department_id, *params])
    else:
        raise unprocessable("Choose employees or a department", "TARGET_REQUIRED")
    if not rows:
        raise unprocessable("No employees in your scope match", "TARGET_EMPTY")
    return rows


def _rest_conflicts(ctx: Ctx, plan: dict[tuple[str, str], str | None], employees: list[dict]) -> list[dict]:
    """Shifts closer than min_rest_hours (or overlapping) for the same employee."""
    rules = settings_svc.get(ctx.conn, ctx.tenant_id, "attendance_rules")
    min_rest = timedelta(hours=rules.get("min_rest_hours", 12))
    out = []
    zones = {e["id"]: attendance_svc.site_zone(ctx.conn, e["site_id"]) for e in employees}
    by_emp: dict[str, list[tuple[date, str]]] = {}
    for (emp_id, day), code in plan.items():
        if code:
            by_emp.setdefault(emp_id, []).append((date.fromisoformat(day), code))
    for emp_id, items in by_emp.items():
        items.sort()
        prev_end = None
        for day, code in items:
            t = attendance_svc.template_for(ctx.conn, ctx.tenant_id, code, day)
            if not t:
                continue
            s, e = Shift.from_row(t, []).planned(day, zones[emp_id])
            if prev_end and s - prev_end < min_rest:
                out.append({"employee_id": emp_id, "work_date": day.isoformat(),
                            "kind": "overlap" if s < prev_end else "short_rest",
                            "rest_hours": round((s - prev_end).total_seconds() / 3600, 1)})
            prev_end = e
    return out


def _write_plan(ctx: Ctx, plan: dict[tuple[str, str], str | None], source: str) -> tuple[int, str]:
    batch = new_id()
    today = local_today().isoformat()
    touched_past = set()
    for (emp_id, day), code in plan.items():
        ctx.conn.execute("INSERT INTO shift_assignments (id, tenant_id, employee_id, work_date, shift_code, source, "
                         "batch_id, created_by, created_at) VALUES (?,?,?,?,?,?,?,?,?) "
                         "ON CONFLICT(tenant_id, employee_id, work_date) DO UPDATE SET shift_code = excluded.shift_code, "
                         "source = excluded.source, batch_id = excluded.batch_id, created_by = excluded.created_by, "
                         "created_at = excluded.created_at",
                         (new_id(), ctx.tenant_id, emp_id, day, code, source, batch, ctx.actor, now_iso()))
        if day <= today:
            touched_past.add((emp_id, day))
    for emp_id, day in touched_past:
        attendance_svc.recompute(ctx.conn, ctx.tenant_id, emp_id, date.fromisoformat(day))
    return len(plan), batch


def _check_period(ctx: Ctx, employees: list[dict], start: date, end: date) -> None:
    for site_id in {e["site_id"] for e in employees}:
        p = dbm.one(ctx.conn, "SELECT start_date, end_date FROM periods WHERE tenant_id = ? AND site_id = ? AND "
                              "status = 'closed' AND start_date <= ? AND end_date >= ?",
                    (ctx.tenant_id, site_id, end.isoformat(), start.isoformat()))
        if p:
            raise locked("Schedule overlaps a closed period", "PERIOD_LOCKED", period=p)


@route("POST", "/api/v1/shifts/rotations/{id}/apply", perm="shift.assign")
def apply_rotation(ctx: Ctx, body: RotationApplyIn):
    rot = dbm.one(ctx.conn, "SELECT * FROM rotations WHERE id = ? AND tenant_id = ?", (ctx.path["id"], ctx.tenant_id))
    if not rot:
        raise not_found("Rotation")
    if body.end_date < body.start_date or (body.end_date - body.start_date).days > 366:
        raise unprocessable("Range must be 1 day to 12 months", "RANGE_INVALID")
    employees = _target_employees(ctx, body.employee_ids, body.department_id)
    _check_period(ctx, employees, body.start_date, body.end_date)
    pattern = loads(rot["pattern"])
    plan = {}
    for e in employees:
        offset = body.team_offsets.get(e["team"] or "", 0)
        for d in daterange(body.start_date, body.end_date):
            code = pattern[((d - body.start_date).days + offset) % len(pattern)]
            plan[(e["id"], d.isoformat())] = None if code == "OFF" else code
    conflicts = _rest_conflicts(ctx, plan, employees)
    if body.preview:
        sample = sorted(plan.items())[:28]
        return {"preview": True, "assignments": len(plan), "employees": len(employees), "conflicts": conflicts,
                "sample": [{"employee_id": k[0], "work_date": k[1], "shift_code": v} for k, v in sample]}
    n, batch = _write_plan(ctx, plan, "rotation")
    ctx.audit("shift.rotation_applied", "rotation", rot["id"],
              after={"batch": batch, "assignments": n, "employees": len(employees),
                     "range": [body.start_date.isoformat(), body.end_date.isoformat()]})
    return {"preview": False, "assignments": n, "batch_id": batch, "conflicts": conflicts}


@route("POST", "/api/v1/shifts/schedule/bulk", perm="shift.assign")
def bulk_assign(ctx: Ctx, body: BulkAssignIn):
    if body.end_date < body.start_date or (body.end_date - body.start_date).days > 366:
        raise unprocessable("Range must be 1 day to 12 months", "RANGE_INVALID")
    if body.shift_code and not attendance_svc.template_for(ctx.conn, ctx.tenant_id, body.shift_code.upper(), body.start_date):
        raise unprocessable("Unknown shift code", "SHIFT_UNKNOWN")
    employees = _target_employees(ctx, body.employee_ids, body.department_id)
    _check_period(ctx, employees, body.start_date, body.end_date)
    plan = {}
    for e in employees:
        for d in daterange(body.start_date, body.end_date):
            plan[(e["id"], d.isoformat())] = (body.shift_code.upper() if body.shift_code else None) \
                if d.weekday() in body.weekdays else None
    conflicts = _rest_conflicts(ctx, plan, employees)
    if body.preview:
        return {"preview": True, "assignments": len(plan), "employees": len(employees), "conflicts": conflicts}
    n, batch = _write_plan(ctx, plan, "bulk")
    ctx.audit("shift.bulk_assigned", "schedule", batch, after={"assignments": n, "shift_code": body.shift_code})
    return {"preview": False, "assignments": n, "batch_id": batch, "conflicts": conflicts}


@route("POST", "/api/v1/shifts/schedule/copy-week", perm="shift.assign")
def copy_week(ctx: Ctx, body: CopyWeekIn):
    if body.source_monday.weekday() != 0 or body.target_monday.weekday() != 0:
        raise unprocessable("Dates must be Mondays", "NOT_MONDAY")
    employees = _target_employees(ctx, body.employee_ids, body.department_id)
    _check_period(ctx, employees, body.target_monday, body.target_monday + timedelta(days=6))
    plan = {}
    for e in employees:
        for i in range(7):
            src = (body.source_monday + timedelta(days=i)).isoformat()
            a = dbm.one(ctx.conn, "SELECT shift_code FROM shift_assignments WHERE tenant_id = ? AND employee_id = ? AND "
                                  "work_date = ?", (ctx.tenant_id, e["id"], src))
            plan[(e["id"], (body.target_monday + timedelta(days=i)).isoformat())] = a["shift_code"] if a else None
    n, batch = _write_plan(ctx, plan, "bulk")
    ctx.audit("shift.week_copied", "schedule", batch, after={"from": body.source_monday.isoformat(),
                                                            "to": body.target_monday.isoformat(), "assignments": n})
    return {"assignments": n}


@route("PUT", "/api/v1/shifts/schedule/cell", perm="shift.assign")
def set_cell(ctx: Ctx, body: CellIn):
    emp = dbm.one(ctx.conn, "SELECT * FROM employees WHERE id = ? AND tenant_id = ?", (body.employee_id, ctx.tenant_id))
    if not emp:
        raise not_found("Employee")
    ctx.require_employee("shift.assign", emp)
    _check_period(ctx, [emp], body.work_date, body.work_date)
    if body.work_date < local_today() and not (body.reason and len(body.reason) >= 10):
        raise unprocessable("Changing a past day needs a reason (min 10 characters)", "REASON_REQUIRED", field="reason")
    code = body.shift_code.upper() if body.shift_code else None
    if code and not attendance_svc.template_for(ctx.conn, ctx.tenant_id, code, body.work_date):
        raise unprocessable("Unknown shift code", "SHIFT_UNKNOWN")
    before = dbm.one(ctx.conn, "SELECT shift_code FROM shift_assignments WHERE tenant_id = ? AND employee_id = ? AND "
                               "work_date = ?", (ctx.tenant_id, emp["id"], body.work_date.isoformat()))
    plan = {(emp["id"], body.work_date.isoformat()): code}
    conflicts = _rest_conflicts(ctx, {**{(emp["id"], (body.work_date + timedelta(days=k)).isoformat()): (
        dbm.scalar(ctx.conn, "SELECT shift_code FROM shift_assignments WHERE tenant_id = ? AND employee_id = ? AND "
                             "work_date = ?", (ctx.tenant_id, emp["id"], (body.work_date + timedelta(days=k)).isoformat())))
        for k in (-1, 1)}, **plan}, [emp])
    _write_plan(ctx, plan, "manual")
    ctx.audit("shift.cell_changed", "employee", emp["id"],
              before={"work_date": body.work_date.isoformat(), "shift_code": before["shift_code"] if before else None},
              after={"shift_code": code, "reason": body.reason})
    return {"ok": True, "conflicts": conflicts}


@route("GET", "/api/v1/shifts/schedule", perm="attendance.read")
def schedule(ctx: Ctx):
    start = date.fromisoformat(ctx.q("from", local_today().isoformat()))
    end = date.fromisoformat(ctx.q("to", (start + timedelta(days=13)).isoformat()))
    if (end - start).days > 62:
        raise unprocessable("At most 62 days per view", "RANGE_TOO_LARGE")
    scope_sql, params = ctx.employee_filter("attendance.read")
    where = ["e.tenant_id = ?", "e.status = 'active'", scope_sql]
    p = [ctx.tenant_id, *params]
    if ctx.q("department_id"):
        where.append("e.department_id = ?")
        p.append(ctx.q("department_id"))
    if ctx.q("site_id"):
        where.append("e.site_id = ?")
        p.append(ctx.q("site_id"))
    if ctx.q("team"):
        where.append("e.team = ?")
        p.append(ctx.q("team"))
    emps = dbm.all_(ctx.conn, f"SELECT e.id, e.personnel_no, e.last_name, e.first_name, e.team, e.site_id, "
                              f"e.department_id FROM employees e WHERE {' AND '.join(where)} "
                              f"ORDER BY e.team, e.last_name LIMIT 500", p)
    ids = [e["id"] for e in emps]
    cells: dict[str, dict] = {e["id"]: {} for e in emps}
    if ids:
        for a in dbm.all_(ctx.conn, f"SELECT employee_id, work_date, shift_code, source FROM shift_assignments "
                                    f"WHERE tenant_id = ? AND work_date BETWEEN ? AND ? AND employee_id IN "
                                    f"({','.join('?' * len(ids))})", [ctx.tenant_id, start.isoformat(), end.isoformat(), *ids]):
            cells[a["employee_id"]][a["work_date"]] = {"code": a["shift_code"], "source": a["source"]}
    plan = {(eid, d): c["code"] for eid, row in cells.items() for d, c in row.items()}
    conflicts = _rest_conflicts(ctx, plan, emps) if emps else []
    sites = {e["site_id"] for e in emps}
    holidays = dbm.all_(ctx.conn, f"SELECT site_id, day, kind, name FROM calendar_days WHERE tenant_id = ? AND day BETWEEN "
                                  f"? AND ? AND site_id IN ({','.join('?' * len(sites)) or 'NULL'})",
                        [ctx.tenant_id, start.isoformat(), end.isoformat(), *sites])
    closed = dbm.all_(ctx.conn, "SELECT site_id, start_date, end_date FROM periods WHERE tenant_id = ? AND status = 'closed' "
                                "AND end_date >= ? AND start_date <= ?", (ctx.tenant_id, start.isoformat(), end.isoformat()))
    return {"from": start.isoformat(), "to": end.isoformat(), "employees": emps, "cells": cells,
            "conflicts": conflicts, "holidays": holidays, "closed_periods": closed,
            "templates": [{"code": t["code"], "name": t["name"], "start_time": t["start_time"],
                           "end_time": t["end_time"], "color": t["color"]} for t in _latest_templates(ctx)]}


# ----------------------------------------------------------------- calendar (SCR-44)

@route("GET", "/api/v1/calendar", perm="org.read")
def calendar(ctx: Ctx):
    year = ctx.q("year", local_today().year, int)
    where = ["tenant_id = ?", "day BETWEEN ? AND ?"]
    params = [ctx.tenant_id, f"{year}-01-01", f"{year}-12-31"]
    if ctx.q("site_id"):
        where.append("site_id = ?")
        params.append(ctx.q("site_id"))
    return {"items": dbm.all_(ctx.conn, f"SELECT * FROM calendar_days WHERE {' AND '.join(where)} ORDER BY day", params)}


def _add_day(ctx: Ctx, body: CalendarIn) -> dict:
    ctx.require_site("calendar.manage", body.site_id)
    if dbm.one(ctx.conn, "SELECT 1 AS x FROM calendar_days WHERE tenant_id = ? AND site_id = ? AND day = ?",
               (ctx.tenant_id, body.site_id, body.day.isoformat())):
        raise conflict("This day is already in the calendar", "CALENDAR_DAY_EXISTS")
    row = {"id": new_id(), "tenant_id": ctx.tenant_id, "site_id": body.site_id, "day": body.day.isoformat(),
           "kind": body.kind, "name": body.name, "created_at": now_iso()}
    dbm.insert(ctx.conn, "calendar_days", row)
    return row


def _recompute_site_day(ctx: Ctx, site_id: str, day: date) -> int:
    if day > local_today():
        return 0
    n = 0
    for e in dbm.all_(ctx.conn, "SELECT id FROM employees WHERE tenant_id = ? AND site_id = ? AND status = 'active'",
                      (ctx.tenant_id, site_id)):
        attendance_svc.recompute(ctx.conn, ctx.tenant_id, e["id"], day)
        n += 1
    return n


@route("POST", "/api/v1/calendar", perm="calendar.manage")
def add_day(ctx: Ctx, body: CalendarIn):
    row = _add_day(ctx, body)
    _recompute_site_day(ctx, body.site_id, body.day)
    ctx.audit("calendar.day_added", "calendar_day", row["id"], after=row)
    return 201, row


@route("POST", "/api/v1/calendar/import", perm="calendar.manage")
def import_days(ctx: Ctx, body: CalendarImportIn):
    added, skipped = 0, 0
    for d in body.days:
        d.site_id = body.site_id
        try:
            _add_day(ctx, d)
            added += 1
        except Exception:  # noqa: BLE001 - duplicates are skipped
            skipped += 1
    ctx.audit("calendar.imported", "site", body.site_id, after={"added": added, "skipped": skipped})
    return {"added": added, "skipped": skipped}


@route("DELETE", "/api/v1/calendar/{id}", perm="calendar.manage")
def delete_day(ctx: Ctx):
    row = dbm.one(ctx.conn, "SELECT * FROM calendar_days WHERE id = ? AND tenant_id = ?", (ctx.path["id"], ctx.tenant_id))
    if not row:
        raise not_found("Calendar day")
    ctx.require_site("calendar.manage", row["site_id"])
    ctx.conn.execute("DELETE FROM calendar_days WHERE id = ?", (row["id"],))
    _recompute_site_day(ctx, row["site_id"], date.fromisoformat(row["day"]))
    ctx.audit("calendar.day_removed", "calendar_day", row["id"], before=row)
    return {"ok": True}


@route("GET", "/api/v1/shifts/history", perm="audit.read")
def schedule_history(ctx: Ctx):
    rows = dbm.all_(ctx.conn, "SELECT a.seq, a.action, a.object_type, a.object_id, a.before_json, a.after_json, "
                              "a.created_at, u.name AS actor_name FROM audit_logs a LEFT JOIN users u ON u.id = a.actor_id "
                              "WHERE a.tenant_id = ? AND (a.action LIKE 'shift.%' OR a.action LIKE 'calendar.%') "
                              "ORDER BY a.seq DESC LIMIT 300", (ctx.tenant_id,))
    return {"items": rows}
