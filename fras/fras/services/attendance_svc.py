"""Glue between the database and the pure attendance engine."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from .. import db as dbm
from ..engine.attendance import Correction, Event, Shift, assign_work_date, compute_day
from ..util import dumps, iso, loads, new_id, now_iso, parse_dt, utcnow
from . import settings_svc


def site_zone(conn, site_id: str) -> str:
    return dbm.scalar(conn, "SELECT timezone FROM sites WHERE id = ?", (site_id,)) or "Asia/Tashkent"


def template_for(conn, tenant_id: str, code: str, day: date) -> dict | None:
    return dbm.one(conn, "SELECT * FROM shift_templates WHERE tenant_id = ? AND code = ? AND valid_from <= ? "
                         "ORDER BY version DESC LIMIT 1", (tenant_id, code, day.isoformat())) or \
        dbm.one(conn, "SELECT * FROM shift_templates WHERE tenant_id = ? AND code = ? ORDER BY version ASC LIMIT 1",
                (tenant_id, code))


def shift_for(conn, tenant_id: str, employee_id: str, day: date) -> Shift | None:
    a = dbm.one(conn, "SELECT shift_code FROM shift_assignments WHERE tenant_id = ? AND employee_id = ? AND work_date = ?",
                (tenant_id, employee_id, day.isoformat()))
    if not a or not a["shift_code"]:
        return None
    t = template_for(conn, tenant_id, a["shift_code"], day)
    if not t:
        return None
    return Shift.from_row(t, loads(t["breaks"], []))


def is_holiday(conn, tenant_id: str, site_id: str, day: date) -> bool:
    return dbm.one(conn, "SELECT 1 AS x FROM calendar_days WHERE tenant_id = ? AND site_id = ? AND day = ? "
                         "AND kind = 'holiday'", (tenant_id, site_id, day.isoformat())) is not None


def work_date_of(conn, tenant_id: str, employee: dict, at: datetime) -> date:
    zone = site_zone(conn, employee["site_id"])
    local_day = at.astimezone(ZoneInfo(zone)).date()
    shifts = {d: shift_for(conn, tenant_id, employee["id"], d)
              for d in (local_day - timedelta(days=1), local_day, local_day + timedelta(days=1))}
    return assign_work_date(at, zone, shifts)


def _events_near(conn, tenant_id: str, employee_id: str, day: date, zone: str) -> list[dict]:
    tz = ZoneInfo(zone)
    lo = datetime(day.year, day.month, day.day, tzinfo=tz) - timedelta(hours=14)
    hi = datetime(day.year, day.month, day.day, tzinfo=tz) + timedelta(hours=48)
    return dbm.all_(conn, "SELECT ev.*, r.decision AS review FROM attendance_events ev "
                          "LEFT JOIN event_reviews r ON r.event_id = ev.id "
                          "WHERE ev.tenant_id = ? AND ev.employee_id = ? AND ev.captured_at >= ? AND ev.captured_at < ? "
                          "ORDER BY ev.captured_at", (tenant_id, employee_id, iso(lo), iso(hi)))


def events_for_work_date(conn, tenant_id: str, employee: dict, day: date) -> list[dict]:
    zone = site_zone(conn, employee["site_id"])
    shifts = {d: shift_for(conn, tenant_id, employee["id"], d)
              for d in (day - timedelta(days=2), day - timedelta(days=1), day, day + timedelta(days=1),
                        day + timedelta(days=2))}
    out = []
    for ev in _events_near(conn, tenant_id, employee["id"], day, zone):
        at = parse_dt(ev["captured_at"])
        local_day = at.astimezone(ZoneInfo(zone)).date()
        candidates = {d: shifts.get(d) for d in (local_day - timedelta(days=1), local_day, local_day + timedelta(days=1))}
        if assign_work_date(at, zone, candidates) == day:
            out.append(ev)
    return out


def period_closed(conn, tenant_id: str, site_id: str, day: date) -> dict | None:
    return dbm.one(conn, "SELECT * FROM periods WHERE tenant_id = ? AND site_id = ? AND status = 'closed' "
                         "AND start_date <= ? AND end_date >= ?", (tenant_id, site_id, day.isoformat(), day.isoformat()))


def leave_on(conn, tenant_id: str, employee_id: str, day: date) -> dict | None:
    row = dbm.one(conn, "SELECT type, start_time, end_time FROM leave_requests WHERE tenant_id = ? AND employee_id = ? "
                        "AND status = 'approved' AND start_date <= ? AND end_date >= ? LIMIT 1",
                  (tenant_id, employee_id, day.isoformat(), day.isoformat()))
    if not row:
        return None
    return {"type": row["type"], "full_day": not row["start_time"]}


def recompute(conn, tenant_id: str, employee_id: str, day: date, now: datetime | None = None,
              force: bool = False) -> dict | None:
    """Recalculate one employee-day. Closed periods are frozen unless force=True (period reopen)."""
    employee = dbm.one(conn, "SELECT * FROM employees WHERE id = ? AND tenant_id = ?", (employee_id, tenant_id))
    if not employee:
        return None
    if not force and period_closed(conn, tenant_id, employee["site_id"], day):
        return dbm.one(conn, "SELECT * FROM daily_summaries WHERE tenant_id = ? AND employee_id = ? AND work_date = ?",
                       (tenant_id, employee_id, day.isoformat()))
    now = now or utcnow()
    zone = site_zone(conn, employee["site_id"])
    rules = settings_svc.get(conn, tenant_id, "attendance_rules")
    raw = events_for_work_date(conn, tenant_id, employee, day)
    events = [Event(id=e["id"], at=parse_dt(e["captured_at"]), direction=e["direction"], result=e["result"],
                    review=e["review"], method=e["method"]) for e in raw]
    corr_rows = dbm.all_(conn, "SELECT * FROM corrections WHERE tenant_id = ? AND employee_id = ? AND work_date = ? "
                               "AND status = 'approved' ORDER BY decided_at", (tenant_id, employee_id, day.isoformat()))
    corrections = [Correction(kind=c["kind"], event_id=c["event_id"], at=parse_dt(c["new_time"]),
                              direction=c["direction"], day_status=c["day_status"]) for c in corr_rows]
    shift = shift_for(conn, tenant_id, employee_id, day)
    summary = compute_day(work_date=day, zone=zone, shift=shift,
                          holiday=is_holiday(conn, tenant_id, employee["site_id"], day), events=events,
                          corrections=corrections, leave=leave_on(conn, tenant_id, employee_id, day),
                          debounce_min=rules["debounce_min"], missing_out_after_min=rules["missing_out_after_min"],
                          now=now)
    row = {
        "tenant_id": tenant_id, "employee_id": employee_id, "work_date": summary.work_date,
        "shift_code": summary.shift_code, "planned_start": iso(summary.planned_start),
        "planned_end": iso(summary.planned_end), "first_in": iso(summary.first_in), "last_out": iso(summary.last_out),
        "worked_min": summary.worked_min, "break_min": summary.break_min, "late_min": summary.late_min,
        "early_leave_min": summary.early_leave_min, "overtime_min": summary.overtime_min, "status": summary.status,
        "anomalies": dumps(summary.anomalies), "explanation": summary.explanation,
        "corrected": 1 if summary.corrected else 0, "rule_version": 1, "computed_at": now_iso(),
    }
    existing = dbm.one(conn, "SELECT id FROM daily_summaries WHERE tenant_id = ? AND employee_id = ? AND work_date = ?",
                       (tenant_id, employee_id, summary.work_date))
    if existing:
        dbm.update(conn, "daily_summaries", {"id": existing["id"]}, row)
        row["id"] = existing["id"]
    else:
        row["id"] = new_id()
        dbm.insert(conn, "daily_summaries", row)
    sync_anomalies(conn, tenant_id, employee_id, summary.work_date, summary.anomalies)
    return row


def sync_anomalies(conn, tenant_id: str, employee_id: str, work_date: str, kinds: list[str]) -> None:
    open_rows = dbm.all_(conn, "SELECT id, kind FROM anomalies WHERE tenant_id = ? AND employee_id = ? AND work_date = ? "
                               "AND status = 'open' AND kind IN ('missing_out','missing_in','review_required')",
                         (tenant_id, employee_id, work_date))
    for r in open_rows:
        if r["kind"] not in kinds:
            conn.execute("UPDATE anomalies SET status = 'resolved', resolved_at = ? WHERE id = ?", (now_iso(), r["id"]))
    for kind in kinds:
        add_anomaly(conn, tenant_id, employee_id, work_date, kind, {})


def add_anomaly(conn, tenant_id: str, employee_id: str, work_date: str, kind: str, details: dict) -> bool:
    existing = dbm.one(conn, "SELECT id, status FROM anomalies WHERE tenant_id = ? AND employee_id = ? AND work_date = ? "
                             "AND kind = ?", (tenant_id, employee_id, work_date, kind))
    if existing:
        if existing["status"] != "open":
            conn.execute("UPDATE anomalies SET status = 'open', resolved_at = NULL, details = ? WHERE id = ?",
                         (dumps(details), existing["id"]))
            return True
        return False
    dbm.insert(conn, "anomalies", {"id": new_id(), "tenant_id": tenant_id, "employee_id": employee_id,
                                   "work_date": work_date, "kind": kind, "status": "open", "details": dumps(details),
                                   "created_at": now_iso(), "resolved_at": None})
    return True


def on_event(conn, tenant_id: str, event: dict) -> dict | None:
    """Recalculate after a new raw event; flag late arrivals into closed periods."""
    if not event.get("employee_id"):
        return None
    employee = dbm.one(conn, "SELECT * FROM employees WHERE id = ?", (event["employee_id"],))
    day = work_date_of(conn, tenant_id, employee, parse_dt(event["captured_at"]))
    closed = period_closed(conn, tenant_id, employee["site_id"], day)
    if closed:
        rules = settings_svc.get(conn, tenant_id, "attendance_rules")
        if rules.get("late_event_review", True):
            add_anomaly(conn, tenant_id, employee["id"], day.isoformat(), "late_event_after_close",
                        {"event_id": event["id"], "period_id": closed["id"]})
        return None
    return recompute(conn, tenant_id, employee["id"], day)


def summary_view(row: dict) -> dict:
    out = dict(row)
    out["anomalies"] = loads(row.get("anomalies"), [])
    return out
