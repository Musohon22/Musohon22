"""Background scheduler: device liveness, attendance sweeps, notification delivery,
retention purge, billing, backups. Runs inside the app process (single node).
Each job opens its own transaction and never raises into the loop."""

from __future__ import annotations

import asyncio
import json
import logging
import smtplib
import ssl
import time
import urllib.request
from datetime import date, timedelta
from email.message import EmailMessage
from pathlib import Path

from . import db as dbm
from .live import broker
from .security import crypto
from .services import attendance_svc, billing_svc, biometric_svc, captures, notify, settings_svc
from .services.alerts import raise_alert
from .util import iso, local_today, now_iso, parse_dt, utcnow

log = logging.getLogger("fras.jobs")


def device_liveness(state) -> int:
    cutoff = iso(utcnow() - timedelta(seconds=state.settings.heartbeat_offline_s))
    changed = 0
    with state.db.tx() as conn:
        for d in dbm.all_(conn, "SELECT * FROM devices WHERE status IN ('online','degraded') AND last_seen_at < ?", (cutoff,)):
            conn.execute("UPDATE devices SET status = 'offline' WHERE id = ?", (d["id"],))
            changed += 1
            broker.publish(f"tenant:{d['tenant_id']}", {"type": "device", "id": d["id"], "status": "offline"})
        # notify at most once per device per 15 minutes
        for d in dbm.all_(conn, "SELECT * FROM devices WHERE status = 'offline' AND (offline_notified_at IS NULL OR "
                                "offline_notified_at < ?)", (iso(utcnow() - timedelta(minutes=15)),)):
            if d["offline_notified_at"] is None:
                raise_alert(conn, d["tenant_id"], "device_offline", "medium",
                            {"device": d["name"], "last_seen_at": d["last_seen_at"]}, device_id=d["id"],
                            site_id=d["site_id"])
                notify.notify_permission(conn, d["tenant_id"], "device.manage", "device_offline",
                                         f"Qurilma offline: {d['name']}", f"Oxirgi aloqa: {d['last_seen_at']}",
                                         f"/app/devices/{d['id']}", site_id=d["site_id"])
            conn.execute("UPDATE devices SET offline_notified_at = ? WHERE id = ?", (now_iso(), d["id"]))
    return changed


def attendance_sweep(state, days: tuple[int, ...] = (0, 1)) -> int:
    """Materialise today's/yesterday's summaries so absences and missing check-outs appear without new events."""
    n = 0
    with state.db.tx() as conn:
        for t in dbm.all_(conn, "SELECT id FROM tenants WHERE status = 'active'"):
            for back in days:
                d = local_today() - timedelta(days=back)
                emps = dbm.all_(conn, "SELECT DISTINCT e.id FROM employees e LEFT JOIN shift_assignments a ON "
                                      "a.employee_id = e.id AND a.work_date = ? WHERE e.tenant_id = ? AND e.status = 'active' "
                                      "AND (a.shift_code IS NOT NULL OR EXISTS (SELECT 1 FROM daily_summaries s WHERE "
                                      "s.employee_id = e.id AND s.work_date = ?))", (d.isoformat(), t["id"], d.isoformat()))
                for e in emps:
                    attendance_svc.recompute(conn, t["id"], e["id"], d)
                    n += 1
    return n


def absence_notifications(state) -> int:
    sent = 0
    today = local_today().isoformat()
    with state.db.tx() as conn:
        for t in dbm.all_(conn, "SELECT id FROM tenants WHERE status = 'active'"):
            rows = dbm.all_(conn, "SELECT s.employee_id, e.last_name, e.first_name, e.site_id, e.department_id, e.team FROM "
                                  "daily_summaries s JOIN employees e ON e.id = s.employee_id WHERE s.tenant_id = ? AND "
                                  "s.work_date = ? AND s.status = 'absent' AND NOT EXISTS (SELECT 1 FROM anomalies a WHERE "
                                  "a.employee_id = s.employee_id AND a.work_date = s.work_date AND a.kind = 'absent_notified')",
                            (t["id"], today))
            if not rows:
                continue
            for r in rows:
                attendance_svc.add_anomaly(conn, t["id"], r["employee_id"], today, "absent_notified", {})
                conn.execute("UPDATE anomalies SET status = 'resolved' WHERE employee_id = ? AND work_date = ? AND kind = "
                             "'absent_notified'", (r["employee_id"], today))
            names = ", ".join(f"{r['last_name']} {r['first_name'][:1]}." for r in rows[:10])
            notify.notify_permission(conn, t["id"], "correction.request", "absent_today",
                                     f"Bugun kelmaganlar: {len(rows)}", names + ("…" if len(rows) > 10 else ""),
                                     "/app/dashboard")
            sent += 1
    return sent


def deliver_outbox(state, limit: int = 50) -> int:
    done = 0
    with state.db.tx() as conn:
        items = dbm.all_(conn, "SELECT * FROM notification_outbox WHERE status = 'pending' AND next_attempt_at <= ? "
                               "ORDER BY created_at LIMIT ?", (now_iso(), limit))
    for item in items:
        error = None
        try:
            payload = json.loads(item["payload"])
            if item["channel"] == "email":
                if not state.settings.smtp_host:
                    raise RuntimeError("SMTP not configured")
                msg = EmailMessage()
                msg["From"] = "fras@localhost"
                msg["To"] = item["recipient"]
                msg["Subject"] = payload.get("subject", "FRAS")
                msg.set_content(f"{payload.get('body', '')}\n\n{payload.get('link') or ''}")
                host, _, port = state.settings.smtp_host.partition(":")
                with smtplib.SMTP(host, int(port or 587), timeout=10) as s:
                    s.starttls(context=ssl.create_default_context())
                    s.send_message(msg)
            elif item["channel"] == "telegram":
                if not state.settings.telegram_bot_token:
                    raise RuntimeError("Telegram bot not configured")
                body = json.dumps({"chat_id": item["recipient"], "text": payload["text"]}).encode()
                req = urllib.request.Request(f"https://api.telegram.org/bot{state.settings.telegram_bot_token}/sendMessage",
                                             data=body, headers={"Content-Type": "application/json"})
                urllib.request.urlopen(req, timeout=10).read()
            elif item["channel"] == "webhook":
                with state.db.tx(write=False) as conn:
                    hook = dbm.one(conn, "SELECT * FROM webhooks WHERE id = ?", (item["recipient"],))
                    secret = crypto.open_sealed(_dek(conn, state, hook["tenant_id"]), hook["secret_enc"], b"webhook").decode() \
                        if hook else None
                if not hook or hook["status"] != "active":
                    raise RuntimeError("webhook removed")
                from .modules.integrations import sign_webhook
                raw = json.dumps(payload).encode()
                ts, sig = sign_webhook(secret, raw)
                req = urllib.request.Request(hook["url"], data=raw, headers={
                    "Content-Type": "application/json", "X-FRAS-Timestamp": ts, "X-FRAS-Signature": sig})
                urllib.request.urlopen(req, timeout=10).read()
        except Exception as e:  # noqa: BLE001 - recorded with retry/backoff
            error = str(e)[:300]
        with state.db.tx() as conn:
            if error is None:
                conn.execute("UPDATE notification_outbox SET status = 'sent', attempts = attempts + 1 WHERE id = ?", (item["id"],))
                done += 1
            else:
                attempts = item["attempts"] + 1
                status = "dead" if attempts >= 8 or "not configured" in error else "pending"
                conn.execute("UPDATE notification_outbox SET status = ?, attempts = ?, last_error = ?, next_attempt_at = ? "
                             "WHERE id = ?", (status, attempts, error, notify.backoff(attempts), item["id"]))
    return done


def _dek(conn, state, tenant_id: str) -> bytes:
    row = dbm.one(conn, "SELECT dek_wrapped FROM tenants WHERE id = ?", (tenant_id,))
    return crypto.unwrap_dek(state.settings.master_key, row["dek_wrapped"], tenant_id)


def retention_purge(state) -> dict:
    stats = {"captures": 0, "exports": 0, "templates": 0, "events": 0, "idempotency": 0, "sessions": 0}
    with state.db.tx() as conn:
        for t in dbm.all_(conn, "SELECT id FROM tenants"):
            r = settings_svc.get(conn, t["id"], "retention")
            cutoff = iso(utcnow() - timedelta(days=r["capture_days"]))
            for ev in dbm.all_(conn, "SELECT id, capture_ref FROM attendance_events WHERE tenant_id = ? AND capture_ref IS NOT "
                                     "NULL AND captured_at < ?", (t["id"], cutoff)):
                captures.delete(state.settings.data_dir, t["id"], ev["capture_ref"])
                stats["captures"] += 1
            term_cutoff = (local_today() - timedelta(days=r["template_after_termination_days"])).isoformat()
            for e in dbm.all_(conn, "SELECT id FROM employees WHERE tenant_id = ? AND status = 'deactivated' AND "
                                    "deactivated_at <= ? AND biometric_status IN ('active','review')", (t["id"], term_cutoff)):
                biometric_svc.revoke(conn, t["id"], e["id"], "retention_after_termination")
                stats["templates"] += 1
            ev_cutoff = iso(utcnow() - timedelta(days=r["events_days"]))
            old = dbm.scalar(conn, "SELECT COUNT(*) FROM attendance_events WHERE tenant_id = ? AND captured_at < ?",
                             (t["id"], ev_cutoff))
            if old:
                conn.execute("UPDATE sys_flags SET value = '1' WHERE key = 'retention_purge'")
                try:
                    conn.execute("DELETE FROM event_reviews WHERE event_id IN (SELECT id FROM attendance_events WHERE "
                                 "tenant_id = ? AND captured_at < ?)", (t["id"], ev_cutoff))
                    conn.execute("DELETE FROM capture_access_log WHERE event_id IN (SELECT id FROM attendance_events WHERE "
                                 "tenant_id = ? AND captured_at < ?)", (t["id"], ev_cutoff))
                    conn.execute("UPDATE corrections SET event_id = NULL WHERE event_id IN (SELECT id FROM attendance_events "
                                 "WHERE tenant_id = ? AND captured_at < ?)", (t["id"], ev_cutoff))
                    conn.execute("DELETE FROM attendance_events WHERE tenant_id = ? AND captured_at < ?", (t["id"], ev_cutoff))
                finally:
                    conn.execute("UPDATE sys_flags SET value = '0' WHERE key = 'retention_purge'")
                stats["events"] += old
        for e in dbm.all_(conn, "SELECT id, file_path FROM exports WHERE status = 'ready' AND expires_at < ?", (now_iso(),)):
            if e["file_path"] and Path(e["file_path"]).exists():
                Path(e["file_path"]).unlink()
            conn.execute("UPDATE exports SET status = 'expired', file_path = NULL WHERE id = ?", (e["id"],))
            stats["exports"] += 1
        stats["idempotency"] = conn.execute("DELETE FROM idempotency_keys WHERE created_at < ?",
                                            (iso(utcnow() - timedelta(hours=24)),)).rowcount
        stats["sessions"] = conn.execute("DELETE FROM sessions WHERE expires_at < ?",
                                         (iso(utcnow() - timedelta(days=30)),)).rowcount
    return stats


def billing_job(state) -> dict:
    with state.db.tx() as conn:
        return billing_svc.run_billing(conn)


def backup_job(state) -> None:
    from .modules.system import make_backup
    with state.db.tx() as conn:
        last = dbm.scalar(conn, "SELECT MAX(created_at) FROM backups WHERE kind = 'backup' AND status = 'ok'")
        if last and parse_dt(last) > utcnow() - timedelta(hours=24):
            return
    if state.settings.db_path == ":memory:":
        return
    row = make_backup(state, "system")
    with state.db.tx() as conn:
        dbm.insert(conn, "backups", row)


JOBS = [  # (name, interval seconds, function)
    ("device_liveness", 30, device_liveness),
    ("attendance_sweep", 600, attendance_sweep),
    ("absence_notifications", 900, absence_notifications),
    ("deliver_outbox", 20, deliver_outbox),
    ("retention_purge", 24 * 3600, retention_purge),
    ("billing", 6 * 3600, billing_job),
    ("backup", 3600, backup_job),
]


async def run_scheduler(state) -> None:
    last: dict[str, float] = {}
    await asyncio.sleep(2)
    while True:
        now = time.monotonic()
        for name, every, fn in JOBS:
            if now - last.get(name, 0) >= every:
                last[name] = now
                try:
                    await asyncio.to_thread(fn, state)
                except Exception:  # noqa: BLE001 - keep the scheduler alive
                    log.exception("job %s failed", name)
        await asyncio.sleep(5)

