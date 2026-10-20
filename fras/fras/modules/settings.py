"""Tenant settings (SCR-81 … SCR-85): versioned, with a rules simulator and legal floors."""

from __future__ import annotations

from datetime import date, timedelta

from pydantic import BaseModel

from .. import db as dbm
from ..engine.attendance import Correction, Event, compute_day
from ..errors import forbidden, not_found, unprocessable
from ..http import Ctx, route
from ..services import attendance_svc, settings_svc
from ..util import daterange, local_today, parse_dt

PERM_BY_KEY = {
    "attendance_rules": "settings.attendance_rules",
    "biometric_policy": "settings.biometric_policy",
    "retention": "settings.retention",
    "notifications": "settings.notifications",
    "locale": "org.manage",
    "self_checkin": "settings.attendance_rules",
}


class SettingsIn(BaseModel):
    value: dict
    valid_from: date | None = None


class SimulateIn(BaseModel):
    value: dict
    days: int = 30


def _validate(key: str, value: dict) -> dict:
    base = settings_svc.DEFAULTS.get(key)
    if base is None:
        raise not_found("Settings key")
    unknown = set(value) - set(base)
    if unknown:
        raise unprocessable("Unknown setting fields", "SETTINGS_UNKNOWN_FIELDS", fields=sorted(unknown))
    merged = {**base, **value}
    if key == "attendance_rules":
        if not 0 <= int(merged["debounce_min"]) <= 30:
            raise unprocessable("debounce_min must be 0–30", "SETTINGS_INVALID", field="debounce_min")
        if not 0 <= int(merged["missing_out_after_min"]) <= 720:
            raise unprocessable("missing_out_after_min must be 0–720", "SETTINGS_INVALID")
        if merged["anti_passback"] not in ("off", "soft", "hard"):
            raise unprocessable("anti_passback must be off/soft/hard", "SETTINGS_INVALID")
    if key == "biometric_policy":
        for name, t in merged["thresholds"].items():
            if not 0 < t["review"] < t["accept"] < 1:
                raise unprocessable(f"Threshold profile {name}: 0 < review < accept < 1", "SETTINGS_INVALID")
        if merged["profile"] not in merged["thresholds"]:
            raise unprocessable("Unknown threshold profile", "SETTINGS_INVALID")
    if key == "retention":
        for k, floor in settings_svc.RETENTION_FLOORS.items():
            if int(merged[k]) < floor:
                raise unprocessable(f"{k} cannot be below the legal minimum ({floor} days)", "RETENTION_BELOW_FLOOR",
                                    field=k, minimum=floor)
        if int(merged["capture_days"]) > 90 or int(merged["enrollment_images_days"]) > 30:
            raise unprocessable("Captures are kept at most 90 days, enrolment images at most 30", "RETENTION_TOO_LONG")
    if key == "self_checkin":
        import ipaddress
        nets = merged["allowed_networks"]
        if not isinstance(nets, list) or len(nets) > 50:
            raise unprocessable("allowed_networks must be a list (max 50)", "SETTINGS_INVALID", field="allowed_networks")
        try:
            merged["allowed_networks"] = [str(ipaddress.ip_network(n.strip(), strict=False)) for n in nets if n.strip()]
        except (ValueError, AttributeError) as e:
            raise unprocessable(f"Invalid network: {e}", "SETTINGS_INVALID", field="allowed_networks") from e
        if merged["outside_network"] not in ("deny", "review"):
            raise unprocessable("outside_network must be deny/review", "SETTINGS_INVALID")
        if not 1 <= int(merged["max_per_employee"]) <= 5:
            raise unprocessable("max_per_employee must be 1–5", "SETTINGS_INVALID")
    return merged


@route("GET", "/api/v1/settings/{key}", perm="settings.read")
def get_settings(ctx: Ctx):
    key = ctx.path["key"]
    if key not in settings_svc.DEFAULTS:
        raise not_found("Settings key")
    return {"key": key, "value": settings_svc.get(ctx.conn, ctx.tenant_id, key),
            "version": settings_svc.current_version(ctx.conn, ctx.tenant_id, key),
            "editable": ctx.can(PERM_BY_KEY[key])}


@route("GET", "/api/v1/settings/{key}/history", perm="settings.read")
def history(ctx: Ctx):
    return {"items": settings_svc.history(ctx.conn, ctx.tenant_id, ctx.path["key"])}


@route("PUT", "/api/v1/settings/{key}", perm="settings.read", billing="write")
def put_settings(ctx: Ctx, body: SettingsIn):
    key = ctx.path["key"]
    perm = PERM_BY_KEY.get(key)
    if not perm:
        raise not_found("Settings key")
    ctx.require(perm)
    merged = _validate(key, body.value)
    before = settings_svc.get(ctx.conn, ctx.tenant_id, key)
    if key == "biometric_policy":
        # lowering thresholds or disabling liveness needs a second person (spec SCR-83)
        prev_t = settings_svc.thresholds(before)
        new_t = settings_svc.thresholds(merged)
        weakened = new_t["accept"] < prev_t["accept"] or (before["liveness_required"] and not merged["liveness_required"])
        if weakened and not ctx.headers.get("x-second-approver"):
            raise forbidden("Weakening the biometric policy needs a second approver (security officer)",
                            "SECOND_APPROVAL_REQUIRED")
        if weakened:
            approver = dbm.one(ctx.conn, "SELECT u.id FROM users u JOIN user_roles r ON r.user_id = u.id WHERE u.id = ? "
                                         "AND u.tenant_id = ? AND r.role_code = 'security'",
                               (ctx.headers["x-second-approver"], ctx.tenant_id))
            if not approver or approver["id"] == ctx.actor:
                raise forbidden("Second approver must be a different security officer", "SECOND_APPROVAL_INVALID")
    saved = settings_svc.put(ctx.conn, ctx.tenant_id, key, merged, ctx.actor,
                             body.valid_from.isoformat() if body.valid_from else None)
    ctx.audit(f"settings.{key}_changed", "settings", key, before=before, after=merged)
    if key in ("biometric_policy", "attendance_rules"):
        from ..services import gallery
        gallery.bump(ctx.conn, ctx.tenant_id)   # devices receive thresholds with the gallery
    return {"key": key, **saved}


@route("POST", "/api/v1/settings/attendance_rules/simulate", perm="settings.attendance_rules")
def simulate(ctx: Ctx, body: SimulateIn):
    """Re-run the last N days with proposed rules without saving anything (spec SCR-82)."""
    proposed = _validate("attendance_rules", body.value)
    current = settings_svc.get(ctx.conn, ctx.tenant_id, "attendance_rules")
    days = max(1, min(body.days, 62))
    end = local_today() - timedelta(days=1)
    start = end - timedelta(days=days - 1)
    totals = {"current": {"late": 0, "overtime_min": 0, "worked_min": 0, "incomplete": 0},
              "proposed": {"late": 0, "overtime_min": 0, "worked_min": 0, "incomplete": 0}}
    emps = dbm.all_(ctx.conn, "SELECT * FROM employees WHERE tenant_id = ? AND status = 'active' LIMIT 2000", (ctx.tenant_id,))
    import datetime as _dt
    now = _dt.datetime.now(_dt.timezone.utc)
    for e in emps:
        zone = attendance_svc.site_zone(ctx.conn, e["site_id"])
        for d in daterange(start, end):
            shift = attendance_svc.shift_for(ctx.conn, ctx.tenant_id, e["id"], d)
            raw = attendance_svc.events_for_work_date(ctx.conn, ctx.tenant_id, e, d)
            if not raw and not shift:
                continue
            events = [Event(id=r["id"], at=parse_dt(r["captured_at"]), direction=r["direction"], result=r["result"],
                            review=r["review"]) for r in raw]
            corrs = [Correction(kind=c["kind"], event_id=c["event_id"], at=parse_dt(c["new_time"]),
                                direction=c["direction"], day_status=c["day_status"])
                     for c in dbm.all_(ctx.conn, "SELECT * FROM corrections WHERE tenant_id = ? AND employee_id = ? AND "
                                                 "work_date = ? AND status = 'approved'", (ctx.tenant_id, e["id"], d.isoformat()))]
            common = dict(work_date=d, zone=zone, shift=shift,
                          holiday=attendance_svc.is_holiday(ctx.conn, ctx.tenant_id, e["site_id"], d), events=events,
                          corrections=corrs, leave=attendance_svc.leave_on(ctx.conn, ctx.tenant_id, e["id"], d), now=now)
            for name, rules in (("current", current), ("proposed", proposed)):
                s = compute_day(debounce_min=rules["debounce_min"], missing_out_after_min=rules["missing_out_after_min"],
                                **common)
                t = totals[name]
                t["late"] += 1 if s.late_min else 0
                t["overtime_min"] += s.overtime_min
                t["worked_min"] += s.worked_min
                t["incomplete"] += 1 if s.status == "incomplete" else 0
    return {"from": start.isoformat(), "to": end.isoformat(), "employees": len(emps), **totals,
            "note": "Shift-template parameters (grace, overtime) are simulated via their own versions, not here"}
