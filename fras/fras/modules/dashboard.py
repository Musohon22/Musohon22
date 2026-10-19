"""Admin dashboard (SCR-01): KPIs, arrivals histogram, department breakdown, attention items."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from .. import db as dbm
from ..http import Ctx, route
from ..util import iso, parse_dt, utcnow


def _employee_scope(ctx: Ctx) -> tuple[str, list]:
    where = ["e.tenant_id = ?", "e.status = 'active'"]
    sql, params = ctx.employee_filter("attendance.read")
    where.append(sql)
    p = [ctx.tenant_id, *params]
    for col, name in (("e.site_id", "site_id"), ("e.department_id", "department_id"), ("e.team", "team")):
        vals = ctx.qlist(name)
        if vals:
            where.append(f"{col} IN ({','.join('?' * len(vals))})")
            p += vals
    if ctx.q("building_id"):
        where.append("EXISTS (SELECT 1 FROM employee_access_points x JOIN access_points ap ON ap.id = x.access_point_id "
                     "JOIN zones z ON z.id = ap.zone_id WHERE x.employee_id = e.id AND z.building_id = ?)")
        p.append(ctx.q("building_id"))
    return " AND ".join(where), p


@route("GET", "/api/v1/dashboard/summary", perm="attendance.read")
def summary(ctx: Ctx):
    day = ctx.q("date", date.today().isoformat())
    where, p = _employee_scope(ctx)
    shift_codes = ctx.qlist("shift_code")
    shift_filter = ""
    if shift_codes:
        shift_filter = f" AND s.shift_code IN ({','.join('?' * len(shift_codes))})"
    rows = dbm.all_(ctx.conn, f"SELECT e.id, e.department_id, s.status, s.shift_code, s.late_min, s.first_in, s.last_out "
                              f"FROM employees e LEFT JOIN daily_summaries s ON s.employee_id = e.id AND s.work_date = ? "
                              f"WHERE {where}{shift_filter}", [day, *p, *shift_codes])
    expected = sum(1 for r in rows if r["shift_code"])
    arrived = sum(1 for r in rows if r["first_in"])
    late = sum(1 for r in rows if (r["late_min"] or 0) > 0)
    absent = sum(1 for r in rows if r["status"] == "absent")
    leave = sum(1 for r in rows if r["status"] == "leave")
    in_now = 0
    if day == date.today().isoformat():
        scope_ids = [r["id"] for r in rows]
        if scope_ids:
            since = iso(utcnow() - timedelta(hours=20))
            # SQLite returns the row holding MAX(captured_at) for bare columns in a grouped query.
            last = dbm.all_(ctx.conn, f"SELECT employee_id, direction, MAX(captured_at) AS at FROM attendance_events "
                                      f"WHERE tenant_id = ? AND captured_at >= ? AND result IN ('accepted','review') "
                                      f"AND employee_id IN ({','.join('?' * len(scope_ids))}) GROUP BY employee_id",
                            [ctx.tenant_id, since, *scope_ids])
            in_now = sum(1 for r in last if r["direction"] == "in")
    yesterday = (date.fromisoformat(day) - timedelta(days=1)).isoformat()
    prev = dbm.all_(ctx.conn, f"SELECT s.status, s.late_min, s.first_in FROM employees e JOIN daily_summaries s ON "
                              f"s.employee_id = e.id AND s.work_date = ? WHERE {where}", [yesterday, *p])
    devices = dbm.all_(ctx.conn, "SELECT status FROM devices WHERE tenant_id = ? AND status <> 'decommissioned'",
                       (ctx.tenant_id,))
    offline = sum(1 for d in devices if d["status"] == "offline")
    return {
        "date": day,
        "kpi": {
            "arrived": {"value": arrived, "expected": expected, "yesterday": sum(1 for r in prev if r["first_in"])},
            "late": {"value": late, "yesterday": sum(1 for r in prev if (r["late_min"] or 0) > 0)},
            "in_now": {"value": in_now},
            "absent": {"value": absent, "yesterday": sum(1 for r in prev if r["status"] == "absent"),
                       "approximate": offline > 0},
            "leave": {"value": leave},
            "devices": {"online": sum(1 for d in devices if d["status"] in ("online", "degraded")), "total": len(devices),
                        "offline": offline},
        },
    }


@route("GET", "/api/v1/dashboard/arrivals", perm="attendance.read")
def arrivals(ctx: Ctx):
    day = date.fromisoformat(ctx.q("date", date.today().isoformat()))
    where, p = _employee_scope(ctx)
    site_tz = "Asia/Tashkent"
    sites = ctx.qlist("site_id")
    if sites:
        site_tz = dbm.scalar(ctx.conn, "SELECT timezone FROM sites WHERE id = ?", (sites[0],)) or site_tz
    tz = ZoneInfo(site_tz)
    start = datetime(day.year, day.month, day.day, tzinfo=tz)
    rows = dbm.all_(ctx.conn, f"SELECT ev.captured_at, ev.direction FROM attendance_events ev JOIN employees e ON e.id = "
                              f"ev.employee_id WHERE {where} AND ev.result IN ('accepted','review') AND ev.captured_at >= ? "
                              f"AND ev.captured_at < ?", [*p, iso(start), iso(start + timedelta(days=1))])
    hours = [{"hour": h, "in": 0, "out": 0} for h in range(24)]
    for r in rows:
        h = parse_dt(r["captured_at"]).astimezone(tz).hour
        hours[h][r["direction"]] += 1
    starts = dbm.all_(ctx.conn, "SELECT DISTINCT t.code, t.start_time FROM shift_templates t WHERE t.tenant_id = ?",
                      (ctx.tenant_id,))
    return {"date": day.isoformat(), "timezone": site_tz, "hours": hours, "shift_starts": starts}


@route("GET", "/api/v1/dashboard/departments", perm="attendance.read")
def departments(ctx: Ctx):
    day = ctx.q("date", date.today().isoformat())
    where, p = _employee_scope(ctx)
    rows = dbm.all_(ctx.conn, f"SELECT d.id, d.name, COUNT(e.id) AS employees, "
                              f"SUM(CASE WHEN s.shift_code IS NOT NULL THEN 1 ELSE 0 END) AS expected, "
                              f"SUM(CASE WHEN s.first_in IS NOT NULL THEN 1 ELSE 0 END) AS arrived, "
                              f"SUM(CASE WHEN s.late_min > 0 THEN 1 ELSE 0 END) AS late, "
                              f"SUM(CASE WHEN s.status = 'absent' THEN 1 ELSE 0 END) AS absent "
                              f"FROM employees e JOIN departments d ON d.id = e.department_id LEFT JOIN daily_summaries s "
                              f"ON s.employee_id = e.id AND s.work_date = ? WHERE {where} GROUP BY d.id, d.name "
                              f"ORDER BY d.name", [day, *p])
    return {"items": rows}


@route("GET", "/api/v1/dashboard/attention", perm="attendance.read")
def attention(ctx: Ctx):
    t = ctx.tenant_id
    sql, params = ctx.employee_filter("attendance.read")
    out = {"anomalies": dbm.scalar(ctx.conn, f"SELECT COUNT(*) FROM anomalies a JOIN employees e ON e.id = a.employee_id "
                                             f"WHERE a.tenant_id = ? AND a.status = 'open' AND {sql}", [t, *params])}
    if ctx.can("correction.approve"):
        s2, p2 = ctx.employee_filter("correction.approve")
        out["approvals"] = dbm.scalar(ctx.conn, f"SELECT COUNT(*) FROM corrections c JOIN employees e ON e.id = "
                                                f"c.employee_id WHERE c.tenant_id = ? AND c.status = 'pending' AND "
                                                f"c.requested_by <> ? AND {s2}", [t, ctx.actor, *p2])
    if ctx.can("leave.approve"):
        s3, p3 = ctx.employee_filter("leave.approve")
        out["leaves"] = dbm.scalar(ctx.conn, f"SELECT COUNT(*) FROM leave_requests l JOIN employees e ON e.id = "
                                             f"l.employee_id WHERE l.tenant_id = ? AND l.status = 'pending' AND {s3}",
                                   [t, *p3])
    if ctx.can("biometric.review"):
        out["duplicate_faces"] = dbm.scalar(ctx.conn, "SELECT COUNT(*) FROM biometric_reviews WHERE tenant_id = ? AND "
                                                      "status = 'open'", (t,))
    if ctx.can("alert.read"):
        out["alerts"] = dbm.scalar(ctx.conn, "SELECT COUNT(*) FROM security_alerts WHERE tenant_id = ? AND status = 'new'",
                                   (t,))
    if ctx.can("device.read"):
        out["offline_devices"] = dbm.all_(ctx.conn, "SELECT id, name, last_seen_at, outbox_size FROM devices WHERE "
                                                    "tenant_id = ? AND status = 'offline' ORDER BY last_seen_at", (t,))
    return out


@route("GET", "/api/v1/dashboard/feed", perm="attendance.read")
def feed(ctx: Ctx):
    """Initial content of the live feed (last 50 events); the SSE stream appends to it."""
    from .attendance import _event_scope
    scope_sql, params = _event_scope(ctx)
    rows = dbm.all_(ctx.conn, f"SELECT ev.id, ev.captured_at, ev.direction, ev.result, ev.method, ev.late_arrival, "
                              f"ev.employee_id, e.last_name, e.first_name, ap.name AS access_point FROM attendance_events ev "
                              f"LEFT JOIN employees e ON e.id = ev.employee_id LEFT JOIN access_points ap ON "
                              f"ap.id = ev.access_point_id WHERE ev.tenant_id = ? AND {scope_sql} "
                              f"ORDER BY ev.captured_at DESC LIMIT 50", [ctx.tenant_id, *params])
    masked = not ctx.can("employee.read_sensitive") and not ctx.is_global("attendance.read")
    for r in rows:
        r["name"] = (f"{r['last_name']} {r['first_name'][:1]}." if masked else f"{r['last_name']} {r['first_name']}") \
            if r["last_name"] else None
        r.pop("last_name")
        r.pop("first_name")
    return {"items": rows}
