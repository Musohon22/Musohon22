"""Security alerts (SCR-74) with notification fan-out to the security role."""

from __future__ import annotations

from .. import db as dbm
from ..live import broker
from ..util import dumps, new_id, now_iso
from . import notify

TITLES = {
    "pad_attempt": "Soxta tasvir bilan urinish",
    "unknown_repeat": "Noma'lum shaxs takroriy urinishi",
    "duplicate_face": "Dublikat yuz aniqlandi",
    "after_hours": "Ish vaqtidan tashqari kirish",
    "login_failures": "Ko'p muvaffaqiyatsiz login",
    "device_tamper": "Qurilma buzilishi",
    "device_offline": "Qurilma offline",
    "audit_chain_broken": "Audit zanjiri buzilgan",
    "gate_opened": "Turniket masofadan ochildi",
}


def raise_alert(conn, tenant_id: str, kind: str, severity: str, details: dict, device_id: str | None = None,
                event_id: str | None = None, site_id: str | None = None) -> str:
    alert_id = new_id()
    now = now_iso()
    dbm.insert(conn, "security_alerts", {"id": alert_id, "tenant_id": tenant_id, "kind": kind, "severity": severity,
                                         "status": "new", "device_id": device_id, "event_id": event_id,
                                         "details": dumps(details), "assignee": None, "resolution": None,
                                         "created_at": now, "updated_at": now})
    channels = ("in_app", "telegram", "email") if severity in ("high", "critical") else ("in_app",)
    notify.notify_permission(conn, tenant_id, "alert.manage", "security_alert", TITLES.get(kind, kind),
                             f"Jiddiylik: {severity}", f"/app/security/alerts?id={alert_id}", site_id=site_id,
                             channels=channels)
    broker.publish(f"tenant:{tenant_id}", {"type": "alert", "kind": kind, "severity": severity, "id": alert_id})
    return alert_id
