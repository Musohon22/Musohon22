"""Device gateway: activation, heartbeat, signed event ingest with dedup, gallery, config, command acks.

All endpoints except /activate authenticate the device with an Ed25519
signature over method, path, timestamp and body hash (replay window 5 min).
Idempotency: (device_id, device_seq) and event_id are both unique, so a batch
re-sent after a lost ACK inserts nothing twice.
"""

from __future__ import annotations

import base64
import json
from datetime import timedelta

from pydantic import BaseModel, Field, ValidationError

from .. import db as dbm
from ..errors import ApiError, conflict, unauthorized, unprocessable
from ..http import Ctx, route
from ..live import broker
from ..security import tokens
from ..services import attendance_svc, biometric_svc, captures, gallery
from ..services.alerts import raise_alert
from ..util import dumps, loads, now_iso, parse_dt, utcnow
from .devices import effective_config, status_from_health

MAX_BATCH = 500
LATE_AFTER_S = 120
FUTURE_TOLERANCE_S = 120


class ActivateIn(BaseModel):
    code: str = Field(min_length=8, max_length=8)
    serial: str | None = Field(default=None, max_length=64)
    public_key: str          # base64 raw Ed25519
    enc_public_key: str      # base64 raw X25519
    firmware: str | None = Field(default=None, max_length=32)


class HeartbeatIn(BaseModel):
    firmware: str | None = None
    health: dict = {}
    outbox_size: int = Field(default=0, ge=0)
    gallery_version: int = 0
    applied_config_version: int = 0
    device_time: str


class EventIn(BaseModel):
    event_id: str = Field(min_length=36, max_length=36)
    seq: int = Field(ge=1)
    employee_id: str | None = None
    direction: str = Field(pattern="^(in|out)$")
    method: str = Field(pattern="^(face|card_pin|qr|guard_override|manual)$")
    result: str = Field(pattern="^(accepted|denied|unknown|pad|duplicate|review)$")
    score: float | None = Field(default=None, ge=-1, le=1)
    liveness_score: float | None = Field(default=None, ge=0, le=1)
    model_version: str | None = Field(default=None, max_length=64)
    captured_at: str
    flags: list[str] = []
    capture_jpeg: str | None = Field(default=None, max_length=600_000)   # base64, suspicious events only


class AckIn(BaseModel):
    status: str = Field(pattern="^(acked|failed)$")
    result: dict = {}


def _json(raw: bytes, model):
    try:
        return model.model_validate(json.loads(raw or b"{}"))
    except (json.JSONDecodeError, ValidationError) as e:
        raise unprocessable("Invalid payload", "VALIDATION_ERROR", detail=str(e)[:500])


@route("POST", "/api/v1/gateway/activate", auth="public", rate="login")
def activate(ctx: Ctx, body: ActivateIn):
    ctx.keep_on_error = False
    dev = dbm.one(ctx.conn, "SELECT * FROM devices WHERE activation_code_hash = ?",
                  (tokens.hash_token(body.code.strip().upper()),))
    if not dev or dev["public_key"] or dev["status"] == "decommissioned":
        raise unauthorized("Activation code is invalid", "DEV-E01")
    if parse_dt(dev["activation_expires_at"]) < utcnow():
        raise unauthorized("Activation code has expired", "DEV-E01")
    try:
        pub = base64.b64decode(body.public_key)
        enc = base64.b64decode(body.enc_public_key)
        assert len(pub) == 32 and len(enc) == 32
    except Exception:  # noqa: BLE001
        raise unprocessable("Keys must be 32-byte base64 values", "DEV-E02")
    if body.serial and dev["serial"] and body.serial != dev["serial"]:
        raise conflict("Serial number does not match the registration", "DEV-E02")
    dbm.update(ctx.conn, "devices", {"id": dev["id"]},
               {"public_key": pub, "enc_public_key": enc, "activation_code_hash": None, "activation_expires_at": None,
                "status": "online", "last_seen_at": now_iso(), "serial": body.serial or dev["serial"],
                "firmware": body.firmware})
    ctx.p.tenant_id = dev["tenant_id"]
    ctx.p.kind, ctx.p.id = "device", dev["id"]
    ctx.audit("device.activated", "device", dev["id"], after={"serial": body.serial, "firmware": body.firmware})
    site = dbm.one(ctx.conn, "SELECT name, timezone FROM sites WHERE id = ?", (dev["site_id"],))
    tenant = dbm.one(ctx.conn, "SELECT slug, name FROM tenants WHERE id = ?", (dev["tenant_id"],))
    ap = dbm.one(ctx.conn, "SELECT name, direction FROM access_points WHERE id = ?", (dev["access_point_id"],)) \
        if dev["access_point_id"] else None
    broker.publish(f"tenant:{dev['tenant_id']}", {"type": "device", "id": dev["id"], "status": "online"})
    return {"device_id": dev["id"], "tenant": tenant, "site": site, "access_point": ap, "direction": dev["direction"],
            "config": effective_config(ctx.conn, dev)}


@route("POST", "/api/v1/gateway/heartbeat", auth="device", rate="device")
def heartbeat(ctx: Ctx, raw: bytes):
    body = _json(raw, HeartbeatIn)
    dev = ctx.p.device
    if dev["status"] == "decommissioned":
        raise unauthorized("Device decommissioned", "DEVICE_UNKNOWN")
    device_time = parse_dt(body.device_time)
    skew_ms = int((device_time - utcnow()).total_seconds() * 1000) if device_time else None
    cfg = effective_config(ctx.conn, dev)
    status = status_from_health(body.health, body.outbox_size, skew_ms, cfg)
    was_offline = dev["status"] == "offline"
    dbm.update(ctx.conn, "devices", {"id": dev["id"]},
               {"last_seen_at": now_iso(), "status": status, "firmware": body.firmware or dev["firmware"],
                "health": dumps(body.health), "outbox_size": body.outbox_size, "clock_skew_ms": skew_ms,
                "gallery_version": body.gallery_version, "applied_config_version": body.applied_config_version,
                "offline_notified_at": None})
    commands = dbm.all_(ctx.conn, "SELECT id, type, payload FROM device_commands WHERE device_id = ? AND status = 'queued' "
                                  "ORDER BY created_at", (dev["id"],))
    for c in commands:
        ctx.conn.execute("UPDATE device_commands SET status = 'sent', sent_at = ? WHERE id = ?", (now_iso(), c["id"]))
        c["payload"] = loads(c["payload"], {})
    if was_offline or status != dev["status"]:
        broker.publish(f"tenant:{dev['tenant_id']}", {"type": "device", "id": dev["id"], "status": status})
    return {"server_time": now_iso(), "gallery_version": gallery.current(ctx.conn, dev["tenant_id"]),
            "config_version": dev["config_version"], "config": cfg if body.applied_config_version != dev["config_version"]
            else None, "commands": commands, "status": status}


def ingest_event(ctx: Ctx, dev: dict, ev: EventIn) -> tuple[str, dict | None]:
    """Returns (outcome, stored_row). outcome: accepted | duplicate | rejected:<reason>."""
    captured = parse_dt(ev.captured_at)
    if captured is None:
        return "rejected:bad_time", None
    now = utcnow()
    flags = list(ev.flags)
    clock_suspect = captured > now + timedelta(seconds=FUTURE_TOLERANCE_S) or \
        (dev["clock_skew_ms"] is not None and abs(dev["clock_skew_ms"]) > 60_000)
    if clock_suspect:
        flags.append("clock_suspect")
    if ev.employee_id:
        emp = dbm.one(ctx.conn, "SELECT id, site_id, status FROM employees WHERE id = ? AND tenant_id = ?",
                      (ev.employee_id, dev["tenant_id"]))
        if not emp:
            return "rejected:unknown_employee", None
    late = (now - captured).total_seconds() > LATE_AFTER_S
    capture_ref = None
    if ev.capture_jpeg and ev.result in ("pad", "unknown", "review", "denied"):
        try:
            capture_ref = captures.store(ctx.settings.data_dir, dev["tenant_id"], ctx.dek(dev["tenant_id"]),
                                         base64.b64decode(ev.capture_jpeg))
        except Exception:  # noqa: BLE001 - a bad capture must not drop the event
            flags.append("capture_invalid")
    row = {"id": ev.event_id, "tenant_id": dev["tenant_id"], "device_id": dev["id"], "device_seq": ev.seq,
           "employee_id": ev.employee_id, "access_point_id": dev["access_point_id"], "site_id": dev["site_id"],
           "direction": ev.direction, "method": ev.method, "result": ev.result, "score": ev.score,
           "liveness_score": ev.liveness_score, "model_version": ev.model_version,
           "captured_at": parse_dt(ev.captured_at).isoformat(timespec="seconds").replace("+00:00", "Z"),
           "received_at": now_iso(), "clock_suspect": 1 if clock_suspect else 0, "late_arrival": 1 if late else 0,
           "flags": dumps(sorted(set(flags))), "capture_ref": capture_ref, "signature": None}
    cur = ctx.conn.execute(
        "INSERT INTO attendance_events (id, tenant_id, device_id, device_seq, employee_id, access_point_id, site_id, "
        "direction, method, result, score, liveness_score, model_version, captured_at, received_at, clock_suspect, "
        "late_arrival, flags, capture_ref, signature) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT DO NOTHING", tuple(row.values()))
    if cur.rowcount == 0:
        if capture_ref:
            captures.delete(ctx.settings.data_dir, dev["tenant_id"], capture_ref)
        return "duplicate", None
    return "accepted", row


@route("POST", "/api/v1/gateway/events", auth="device", rate="device")
def events(ctx: Ctx, raw: bytes):
    dev = ctx.p.device
    try:
        payload = json.loads(raw or b"{}")
    except json.JSONDecodeError:
        raise unprocessable("Invalid JSON", "INVALID_JSON")
    items = payload.get("events") or []
    if len(items) > MAX_BATCH:
        raise unprocessable(f"At most {MAX_BATCH} events per batch", "BATCH_TOO_LARGE")
    accepted, duplicates, rejected = 0, 0, []
    stored = []
    for item in items:
        try:
            ev = EventIn.model_validate(item)
        except ValidationError as e:
            rejected.append({"event_id": item.get("event_id"), "seq": item.get("seq"), "reason": "invalid",
                             "detail": str(e)[:200]})
            continue
        outcome, row = ingest_event(ctx, dev, ev)
        if outcome == "accepted":
            accepted += 1
            stored.append(row)
        elif outcome == "duplicate":
            duplicates += 1
        else:
            rejected.append({"event_id": ev.event_id, "seq": ev.seq, "reason": outcome.split(":", 1)[1]})
    # downstream processing: summaries, alerts, live feed
    for row in sorted(stored, key=lambda r: r["captured_at"]):
        if row["employee_id"]:
            attendance_svc.on_event(ctx.conn, dev["tenant_id"], row)
        if row["result"] == "pad":
            raise_alert(ctx.conn, dev["tenant_id"], "pad_attempt", "high", {"event_id": row["id"]},
                        device_id=dev["id"], event_id=row["id"], site_id=dev["site_id"])
        elif row["result"] == "unknown":
            recent = dbm.scalar(ctx.conn, "SELECT COUNT(*) FROM attendance_events WHERE device_id = ? AND result = 'unknown' "
                                          "AND captured_at >= ?", (dev["id"], (parse_dt(row["captured_at"]) -
                                                                              timedelta(minutes=5)).isoformat()))
            if recent >= 3 and not dbm.one(ctx.conn, "SELECT 1 AS x FROM security_alerts WHERE device_id = ? AND kind = "
                                                     "'unknown_repeat' AND created_at >= ?",
                                           (dev["id"], (utcnow() - timedelta(minutes=5)).isoformat())):
                raise_alert(ctx.conn, dev["tenant_id"], "unknown_repeat", "medium", {"count": recent},
                            device_id=dev["id"], event_id=row["id"], site_id=dev["site_id"])
    max_seq = dbm.scalar(ctx.conn, "SELECT max(device_seq) FROM attendance_events WHERE device_id = ?", (dev["id"],)) or 0
    dbm.update(ctx.conn, "devices", {"id": dev["id"]}, {"last_acked_seq": max_seq, "last_seen_at": now_iso()})
    if stored:
        names = {r["id"]: r for r in dbm.all_(
            ctx.conn, f"SELECT id, first_name, last_name, department_id, site_id, team FROM employees WHERE id IN "
                      f"({','.join('?' * len(stored))})", [r["employee_id"] or "-" for r in stored])}
        ap_name = dbm.scalar(ctx.conn, "SELECT name FROM access_points WHERE id = ?", (dev["access_point_id"],))
        for r in stored:
            emp = names.get(r["employee_id"])
            broker.publish(f"tenant:{dev['tenant_id']}", {
                "type": "event", "id": r["id"], "captured_at": r["captured_at"], "direction": r["direction"],
                "result": r["result"], "method": r["method"], "access_point": ap_name, "late": bool(r["late_arrival"]),
                "employee_id": r["employee_id"], "site_id": r["site_id"],
                "department_id": emp["department_id"] if emp else None, "team": emp["team"] if emp else None,
                "name": f"{emp['last_name']} {emp['first_name']}" if emp else None})
    return {"accepted": accepted, "duplicates": duplicates, "rejected": rejected, "last_acked_seq": max_seq}


@route("GET", "/api/v1/gateway/gallery", auth="device", rate="device")
def get_gallery(ctx: Ctx, raw: bytes = b""):
    dev = ctx.p.device
    return biometric_svc.sealed_gallery(ctx.conn, ctx.dek(dev["tenant_id"]), dev)


@route("GET", "/api/v1/gateway/config", auth="device", rate="device")
def get_config(ctx: Ctx, raw: bytes = b""):
    dev = ctx.p.device
    return {"config_version": dev["config_version"], "config": effective_config(ctx.conn, dev),
            "direction": dev["direction"]}


@route("POST", "/api/v1/gateway/commands/{id}/ack", auth="device", rate="device")
def ack(ctx: Ctx, raw: bytes):
    body = _json(raw, AckIn)
    dev = ctx.p.device
    cmd = dbm.one(ctx.conn, "SELECT * FROM device_commands WHERE id = ? AND device_id = ?", (ctx.path["id"], dev["id"]))
    if not cmd:
        raise ApiError(404, "NOT_FOUND", "Command not found")
    dbm.update(ctx.conn, "device_commands", {"id": cmd["id"]},
               {"status": body.status, "result": dumps(body.result), "acked_at": now_iso()})
    if cmd["type"] == "ota" and body.status == "acked" and body.result.get("version"):
        dbm.update(ctx.conn, "devices", {"id": dev["id"]}, {"firmware": body.result["version"]})
    if cmd["type"] == "apply_config" and body.status == "acked":
        dbm.update(ctx.conn, "devices", {"id": dev["id"]},
                   {"applied_config_version": loads(cmd["payload"], {}).get("config_version", dev["config_version"])})
    ctx.audit(f"device.command_{body.status}", "device", dev["id"], after={"command_id": cmd["id"], "type": cmd["type"]})
    return {"ok": True}
