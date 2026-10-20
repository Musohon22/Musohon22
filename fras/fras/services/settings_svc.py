"""Versioned tenant settings. Every change writes a new version row; reads take the latest."""

from __future__ import annotations

import copy

from .. import db as dbm
from ..util import dumps, loads, new_id, now_iso

DEFAULTS: dict[str, dict] = {
    "attendance_rules": {
        "debounce_min": 2,                 # same employee, same direction within N minutes = duplicate
        "missing_out_after_min": 120,      # after planned end + N minutes a missing check-out becomes an anomaly
        "anti_passback": "off",            # off | soft | hard
        "overtime_requires_approval": False,
        "min_rest_hours": 12,              # warning when two shifts are closer than this [TAXMIN-9]
        "late_event_review": True,         # events landing in a closed period go to HR review
        "count_unpaid_breaks": False,
    },
    "biometric_policy": {
        # Thresholds are placeholders until calibrated in the PoC (spec D-02); never treat as accuracy claims.
        "profile": "standard",
        "thresholds": {
            "strict": {"accept": 0.70, "review": 0.58},
            "standard": {"accept": 0.62, "review": 0.50},
            "lenient": {"accept": 0.56, "review": 0.45},
        },
        "duplicate_threshold": 0.68,
        "liveness_required": True,
        "liveness_min": 0.60,
        "border_action": "retry",          # retry | alternative | guard
        "mask_mode": False,
        "adaptive_update": False,
        "consent_policy_version": "v1",
        "min_frames": 3,
        "min_quality": 0.55,
    },
    "retention": {
        "events_days": 1825,
        "capture_days": 30,
        "enrollment_images_days": 0,
        "template_after_termination_days": 30,
        "audit_days": 2555,
        "logs_days": 90,
        "exports_days": 7,
    },
    "notifications": {
        "absent_after_min": 30,
        "channels": {"in_app": True, "email": True, "telegram": False},
        "quiet_hours": {"from": "22:00", "to": "07:00"},
    },
    "locale": {"default_language": "uz", "date_format": "DD.MM.YYYY", "week_start": 1},
    "self_checkin": {
        "enabled": False,                  # laptop check-in with a passkey (Windows Hello); off until HR opts in
        "allowed_networks": [],            # office CIDRs; empty = every check-in counts as "outside"
        "outside_network": "deny",         # deny | review — what happens outside those networks
        "require_approval": True,          # HR approves each newly registered laptop
        "device_bound_only": True,         # refuse synced passkeys (phone/cloud copies on other devices)
        "max_per_employee": 2,
    },
}

# Minimums that settings may not go below (legal floor) [TAXMIN-11]
RETENTION_FLOORS = {"events_days": 365 * 5, "audit_days": 365 * 3}


def get(conn, tenant_id: str, key: str) -> dict:
    row = dbm.one(conn, "SELECT value FROM settings WHERE tenant_id = ? AND key = ? ORDER BY version DESC LIMIT 1",
                  (tenant_id, key))
    base = copy.deepcopy(DEFAULTS.get(key, {}))
    if row:
        base.update(loads(row["value"], {}))
    return base


def current_version(conn, tenant_id: str, key: str) -> dict | None:
    return dbm.one(conn, "SELECT id, version, created_by, created_at, valid_from FROM settings "
                         "WHERE tenant_id = ? AND key = ? ORDER BY version DESC LIMIT 1", (tenant_id, key))


def put(conn, tenant_id: str, key: str, value: dict, actor: str, valid_from: str | None = None) -> dict:
    prev = current_version(conn, tenant_id, key)
    version = (prev["version"] if prev else 0) + 1
    row = {"id": new_id(), "tenant_id": tenant_id, "key": key, "version": version, "value": dumps(value),
           "valid_from": valid_from, "created_by": actor, "created_at": now_iso()}
    dbm.insert(conn, "settings", row)
    return {"version": version, "value": value}


def history(conn, tenant_id: str, key: str) -> list[dict]:
    rows = dbm.all_(conn, "SELECT version, value, valid_from, created_by, created_at FROM settings "
                          "WHERE tenant_id = ? AND key = ? ORDER BY version DESC", (tenant_id, key))
    for r in rows:
        r["value"] = loads(r["value"], {})
    return rows


def thresholds(policy: dict) -> dict:
    return policy["thresholds"].get(policy.get("profile", "standard"), policy["thresholds"]["standard"])
