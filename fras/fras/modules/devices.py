"""Device registry, groups, remote commands, firmware rollouts (SCR-60 … SCR-65)."""

from __future__ import annotations

import secrets
from datetime import timedelta

from pydantic import BaseModel, Field

from .. import db as dbm
from ..errors import conflict, forbidden, not_found, unprocessable
from ..http import Ctx, route
from ..security import crypto, tokens, totp
from ..services import tenancy
from ..util import dumps, iso, loads, new_id, now_iso, utcnow

DEFAULT_CONFIG = {
    "relay_open_ms": 3000,
    "success_screen_ms": 2000,
    "max_attempts": 3,
    "idle_dim_s": 60,
    "volume": 60,
    "voice": False,
    "camera_fps_min": 10,
    "heartbeat_s": 30,
    "outbox_alert_pct": 80,
    "capture_suspicious": True,
    "kiosk_language": "uz",
    "alt_methods": ["card_pin", "qr"],
}
# Changing these weakens security and needs a super admin.
DANGEROUS_KEYS = {"liveness_required", "threshold_override", "capture_suspicious"}
ACTIVATION_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


class DeviceIn(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    type: str = Field(pattern="^(terminal|camera|controller|site_server)$")
    site_id: str
    access_point_id: str | None = None
    direction: str = Field(default="in", pattern="^(in|out|both)$")
    group_id: str | None = None
    serial: str | None = Field(default=None, max_length=64)


class DevicePatch(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=80)
    access_point_id: str | None = None
    direction: str | None = Field(default=None, pattern="^(in|out|both)$")
    group_id: str | None = None
    config_override: dict | None = None


class CommandIn(BaseModel):
    type: str = Field(pattern="^(restart|diagnostic|open_gate|gallery_sync)$")
    reason: str | None = Field(default=None, max_length=300)
    test: str | None = Field(default=None, pattern="^(camera|relay|network|gallery)$")
    mfa_code: str | None = None


class DecommissionIn(BaseModel):
    confirm_name: str


class GroupIn(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    config: dict = {}


class ReleaseIn(BaseModel):
    version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    notes: str | None = Field(default=None, max_length=2000)


class RolloutIn(BaseModel):
    release_id: str
    group_id: str
    window_from: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    window_to: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")


def device_view(d: dict) -> dict:
    out = {k: v for k, v in d.items() if k not in ("public_key", "enc_public_key", "activation_code_hash")}
    out["health"] = loads(d.get("health"), {})
    out["config_override"] = loads(d.get("config_override"), {})
    out["config_drift"] = d.get("applied_config_version", 0) != d.get("config_version", 0)
    out["activated"] = bool(d.get("public_key"))
    return out


def effective_config(conn, device: dict) -> dict:
    cfg = dict(DEFAULT_CONFIG)
    if device.get("group_id"):
        g = dbm.one(conn, "SELECT config FROM device_groups WHERE id = ?", (device["group_id"],))
        if g:
            cfg.update(loads(g["config"], {}))
    cfg.update(loads(device.get("config_override"), {}))
    return cfg


def _get(ctx: Ctx, device_id: str, perm: str = "device.read") -> dict:
    d = dbm.one(ctx.conn, "SELECT * FROM devices WHERE id = ? AND tenant_id = ?", (device_id, ctx.tenant_id))
    if not d:
        raise not_found("Device")
    ctx.require_site(perm, d["site_id"])
    return d


def _activation_code() -> str:
    return "".join(secrets.choice(ACTIVATION_ALPHABET) for _ in range(8))


@route("GET", "/api/v1/devices", perm="device.read")
def list_devices(ctx: Ctx):
    allowed = ctx.site_ids("device.read")
    where, params = ["d.tenant_id = ?"], [ctx.tenant_id]
    if allowed is not None:
        where.append(f"d.site_id IN ({','.join('?' * len(allowed)) or 'NULL'})")
        params += list(allowed)
    for col, name in (("d.status", "status"), ("d.type", "type"), ("d.site_id", "site_id"), ("d.group_id", "group_id")):
        vals = ctx.qlist(name)
        if vals:
            where.append(f"{col} IN ({','.join('?' * len(vals))})")
            params += vals
    rows = dbm.all_(ctx.conn, f"SELECT d.*, s.name AS site_name, ap.name AS access_point_name, g.name AS group_name "
                              f"FROM devices d JOIN sites s ON s.id = d.site_id LEFT JOIN access_points ap "
                              f"ON ap.id = d.access_point_id LEFT JOIN device_groups g ON g.id = d.group_id "
                              f"WHERE {' AND '.join(where)} ORDER BY s.name, d.name", params)
    items = [device_view(r) for r in rows]
    summary = {s: sum(1 for r in items if r["status"] == s) for s in ("online", "degraded", "offline", "pending")}
    summary["updates_pending"] = sum(1 for r in items if r["config_drift"])
    return {"items": items, "summary": summary}


@route("GET", "/api/v1/devices/{id}", perm="device.read")
def get_device(ctx: Ctx):
    d = _get(ctx, ctx.path["id"])
    out = device_view(d)
    out["effective_config"] = effective_config(ctx.conn, d)
    out["commands"] = dbm.all_(ctx.conn, "SELECT c.*, u.name AS created_by_name FROM device_commands c LEFT JOIN users u "
                                         "ON u.id = c.created_by WHERE c.device_id = ? ORDER BY c.created_at DESC LIMIT 50",
                               (d["id"],))
    for c in out["commands"]:
        c["payload"] = loads(c["payload"], {})
        c["result"] = loads(c["result"], None)
    out["events_today"] = dbm.scalar(ctx.conn, "SELECT COUNT(*) FROM attendance_events WHERE device_id = ? AND "
                                               "captured_at >= date('now')", (d["id"],))
    out["rejected_today"] = dbm.scalar(ctx.conn, "SELECT COUNT(*) FROM attendance_events WHERE device_id = ? AND "
                                                 "captured_at >= date('now') AND result IN ('unknown','pad','denied')",
                                       (d["id"],))
    out["history"] = dbm.all_(ctx.conn, "SELECT a.action, a.created_at, u.name AS actor_name, a.after_json FROM audit_logs a "
                                        "LEFT JOIN users u ON u.id = a.actor_id WHERE a.tenant_id = ? AND a.object_type = "
                                        "'device' AND a.object_id = ? ORDER BY a.seq DESC LIMIT 50",
                              (ctx.tenant_id, d["id"]))
    return out


@route("POST", "/api/v1/devices", perm="device.manage", billing="grow")
def register(ctx: Ctx, body: DeviceIn):
    ctx.require_site("device.manage", body.site_id)
    if not dbm.one(ctx.conn, "SELECT 1 AS x FROM sites WHERE id = ? AND tenant_id = ?", (body.site_id, ctx.tenant_id)):
        raise unprocessable("Unknown site", "SITE_UNKNOWN")
    if body.type == "terminal" and not body.access_point_id:
        raise unprocessable("A terminal must be bound to an access point (gate)", "ACCESS_POINT_REQUIRED",
                            field="access_point_id")
    if body.access_point_id:
        ap = dbm.one(ctx.conn, "SELECT site_id FROM access_points WHERE id = ? AND tenant_id = ?",
                     (body.access_point_id, ctx.tenant_id))
        if not ap or ap["site_id"] != body.site_id:
            raise unprocessable("Access point does not belong to the site", "ACCESS_POINT_INVALID")
    tenancy.check_limit(ctx.conn, ctx.tenant_id, "devices")
    code = _activation_code()
    row = {"id": new_id(), "tenant_id": ctx.tenant_id, **body.model_dump(), "status": "pending",
           "activation_code_hash": tokens.hash_token(code),
           "activation_expires_at": iso(utcnow() + timedelta(hours=24)), "config_override": "{}",
           "config_version": 1, "applied_config_version": 0, "health": "{}", "created_at": now_iso()}
    dbm.insert(ctx.conn, "devices", row)
    ctx.audit("device.registered", "device", row["id"], after=device_view(row))
    return 201, {**device_view(row), "activation_code": code,
                 "qr_payload": dumps({"server": ctx.settings.public_base_url, "code": code}),
                 "expires_at": row["activation_expires_at"]}


@route("POST", "/api/v1/devices/{id}/activation-code", perm="device.manage")
def new_code(ctx: Ctx):
    d = _get(ctx, ctx.path["id"], "device.manage")
    if d["public_key"]:
        raise conflict("Device is already activated", "ALREADY_ACTIVATED")
    code = _activation_code()
    exp = iso(utcnow() + timedelta(hours=24))
    dbm.update(ctx.conn, "devices", {"id": d["id"]}, {"activation_code_hash": tokens.hash_token(code),
                                                     "activation_expires_at": exp})
    ctx.audit("device.activation_code_issued", "device", d["id"])
    return {"activation_code": code, "expires_at": exp,
            "qr_payload": dumps({"server": ctx.settings.public_base_url, "code": code})}


def queue_command(ctx: Ctx, device: dict, type_: str, payload: dict, reason: str | None) -> dict:
    cmd = {"id": new_id(), "tenant_id": ctx.tenant_id, "device_id": device["id"], "type": type_,
           "payload": dumps(payload), "reason": reason, "status": "queued", "result": None, "created_by": ctx.actor,
           "created_at": now_iso(), "sent_at": None, "acked_at": None}
    dbm.insert(ctx.conn, "device_commands", cmd)
    return cmd


@route("PATCH", "/api/v1/devices/{id}", perm="device.manage")
def patch(ctx: Ctx, body: DevicePatch):
    d = _get(ctx, ctx.path["id"], "device.manage")
    changes = body.model_dump(exclude_unset=True)
    if "config_override" in changes:
        if DANGEROUS_KEYS & set(changes["config_override"]) and not ctx.is_global("device.manage"):
            raise forbidden("Changing security parameters needs an organisation-wide admin", "DANGEROUS_CONFIG")
        changes["config_override"] = dumps(changes["config_override"])
    if changes.get("access_point_id"):
        ap = dbm.one(ctx.conn, "SELECT site_id FROM access_points WHERE id = ? AND tenant_id = ?",
                     (changes["access_point_id"], ctx.tenant_id))
        if not ap or ap["site_id"] != d["site_id"]:
            raise unprocessable("Access point does not belong to the device site", "ACCESS_POINT_INVALID")
    changes["config_version"] = d["config_version"] + 1
    dbm.update(ctx.conn, "devices", {"id": d["id"]}, changes)
    updated = dbm.one(ctx.conn, "SELECT * FROM devices WHERE id = ?", (d["id"],))
    queue_command(ctx, updated, "apply_config", {"config_version": changes["config_version"],
                                                 "config": effective_config(ctx.conn, updated)}, "config change")
    ctx.audit("device.config_changed", "device", d["id"], before=device_view(d), after=changes)
    return device_view(updated)


@route("POST", "/api/v1/devices/{id}/commands", perm="device.read")
def command(ctx: Ctx, body: CommandIn):
    d = _get(ctx, ctx.path["id"])
    if d["status"] in ("pending", "decommissioned"):
        raise conflict("Device is not active", "DEVICE_INACTIVE")
    perm = {"restart": "device.restart", "diagnostic": "device.manage", "open_gate": "device.open_gate",
            "gallery_sync": "device.manage"}[body.type]
    ctx.require(perm)
    if body.type in ("restart", "open_gate") and not (body.reason and len(body.reason) >= 10):
        raise unprocessable("A reason of at least 10 characters is required", "REASON_REQUIRED", field="reason")
    if body.type == "open_gate":
        user = dbm.one(ctx.conn, "SELECT mfa_enabled, totp_secret_enc FROM users WHERE id = ?", (ctx.actor,))
        if user and user["mfa_enabled"]:
            secret = crypto.open_sealed(ctx.dek(), user["totp_secret_enc"], b"totp").decode()
            if not (body.mfa_code and totp.verify(secret, body.mfa_code)):
                raise unprocessable("Confirm with your MFA code", "MFA_REQUIRED", field="mfa_code")
    if body.type == "diagnostic" and not body.test:
        raise unprocessable("Choose a diagnostic test", "TEST_REQUIRED", field="test")
    cmd = queue_command(ctx, d, body.type, {"test": body.test} if body.test else {}, body.reason)
    ctx.audit(f"device.command_{body.type}", "device", d["id"], after={"command_id": cmd["id"], "reason": body.reason})
    if body.type == "open_gate":
        from ..services.alerts import raise_alert
        raise_alert(ctx.conn, ctx.tenant_id, "gate_opened", "medium",
                    {"device_id": d["id"], "by": ctx.actor, "reason": body.reason}, device_id=d["id"], site_id=d["site_id"])
    return 202, {"command_id": cmd["id"], "status": "queued",
                 "note": "Qurilma keyingi aloqada (≤ 30 s) buyruqni oladi" if d["status"] == "online" else
                 "Qurilma offline: buyruq aloqa tiklanganda bajariladi"}


@route("POST", "/api/v1/devices/{id}/decommission", perm="device.manage")
def decommission(ctx: Ctx, body: DecommissionIn):
    d = _get(ctx, ctx.path["id"], "device.manage")
    if body.confirm_name.strip() != d["name"]:
        raise unprocessable("Type the device name to confirm", "CONFIRMATION_REQUIRED", field="confirm_name")
    queue_command(ctx, d, "decommission", {"crypto_erase": True}, "decommission")
    dbm.update(ctx.conn, "devices", {"id": d["id"]}, {"status": "decommissioned"})
    ctx.audit("device.decommissioned", "device", d["id"])
    online = d["status"] == "online"
    return {"ok": True, "note": None if online else "Qurilma offline: lokal ma'lumot keyingi ulanishda o'chiriladi"}


# ----------------------------------------------------------------- groups

@route("GET", "/api/v1/device-groups", perm="device.read")
def groups(ctx: Ctx):
    rows = dbm.all_(ctx.conn, "SELECT g.*, (SELECT COUNT(*) FROM devices d WHERE d.group_id = g.id) AS devices "
                              "FROM device_groups g WHERE g.tenant_id = ? ORDER BY g.name", (ctx.tenant_id,))
    for r in rows:
        r["config"] = loads(r["config"], {})
    return {"items": rows, "defaults": DEFAULT_CONFIG}


@route("POST", "/api/v1/device-groups", perm="device.manage")
def create_group(ctx: Ctx, body: GroupIn):
    if DANGEROUS_KEYS & set(body.config) and not ctx.is_global("device.manage"):
        raise forbidden("Changing security parameters needs an organisation-wide admin", "DANGEROUS_CONFIG")
    row = {"id": new_id(), "tenant_id": ctx.tenant_id, "name": body.name, "config": dumps(body.config),
           "config_version": 1, "created_at": now_iso()}
    dbm.insert(ctx.conn, "device_groups", row)
    ctx.audit("device.group_created", "device_group", row["id"], after=row)
    return 201, {**row, "config": body.config}


@route("PUT", "/api/v1/device-groups/{id}", perm="device.manage")
def update_group(ctx: Ctx, body: GroupIn):
    g = dbm.one(ctx.conn, "SELECT * FROM device_groups WHERE id = ? AND tenant_id = ?", (ctx.path["id"], ctx.tenant_id))
    if not g:
        raise not_found("Device group")
    if DANGEROUS_KEYS & set(body.config) and not ctx.is_global("device.manage"):
        raise forbidden("Changing security parameters needs an organisation-wide admin", "DANGEROUS_CONFIG")
    dbm.update(ctx.conn, "device_groups", {"id": g["id"]}, {"name": body.name, "config": dumps(body.config),
                                                           "config_version": g["config_version"] + 1})
    pushed = 0
    for d in dbm.all_(ctx.conn, "SELECT * FROM devices WHERE group_id = ? AND status <> 'decommissioned'", (g["id"],)):
        dbm.update(ctx.conn, "devices", {"id": d["id"]}, {"config_version": d["config_version"] + 1})
        d = dbm.one(ctx.conn, "SELECT * FROM devices WHERE id = ?", (d["id"],))
        queue_command(ctx, d, "apply_config", {"config_version": d["config_version"],
                                               "config": effective_config(ctx.conn, d)}, "group profile change")
        pushed += 1
    ctx.audit("device.group_updated", "device_group", g["id"], before={"config": loads(g["config"])},
              after={"config": body.config})
    return {"ok": True, "devices_updated": pushed}


# ----------------------------------------------------------------- firmware (SCR-64)

@route("GET", "/api/v1/firmware", perm="device.read")
def firmware(ctx: Ctx):
    releases = dbm.all_(ctx.conn, "SELECT * FROM firmware_releases WHERE tenant_id = ? ORDER BY created_at DESC",
                        (ctx.tenant_id,))
    rollouts = dbm.all_(ctx.conn, "SELECT r.*, f.version, g.name AS group_name FROM firmware_rollouts r JOIN "
                                  "firmware_releases f ON f.id = r.release_id JOIN device_groups g ON g.id = r.group_id "
                                  "WHERE r.tenant_id = ? ORDER BY r.created_at DESC", (ctx.tenant_id,))
    for r in rollouts:
        devices = dbm.all_(ctx.conn, "SELECT firmware FROM devices WHERE group_id = ? AND status <> 'decommissioned'",
                           (r["group_id"],))
        r["devices"] = len(devices)
        r["updated"] = sum(1 for d in devices if d["firmware"] == r["version"])
    return {"releases": releases, "rollouts": rollouts}


@route("POST", "/api/v1/firmware", perm="device.manage")
def add_release(ctx: Ctx, body: ReleaseIn):
    if not ctx.is_global("device.manage"):
        raise forbidden("Only organisation-wide admins publish firmware", "SCOPE_TOO_NARROW")
    row = {"id": new_id(), "tenant_id": ctx.tenant_id, **body.model_dump(), "created_at": now_iso()}
    dbm.insert(ctx.conn, "firmware_releases", row)
    ctx.audit("firmware.release_added", "firmware", row["id"], after=row)
    return 201, row


@route("POST", "/api/v1/firmware/rollouts", perm="device.manage")
def start_rollout(ctx: Ctx, body: RolloutIn):
    rel = dbm.one(ctx.conn, "SELECT * FROM firmware_releases WHERE id = ? AND tenant_id = ?", (body.release_id, ctx.tenant_id))
    grp = dbm.one(ctx.conn, "SELECT * FROM device_groups WHERE id = ? AND tenant_id = ?", (body.group_id, ctx.tenant_id))
    if not rel or not grp:
        raise not_found("Release or group")
    if dbm.one(ctx.conn, "SELECT 1 AS x FROM firmware_rollouts WHERE group_id = ? AND status IN ('running','paused')",
               (grp["id"],)):
        raise conflict("A rollout is already active for this group", "ROLLOUT_ACTIVE")
    row = {"id": new_id(), "tenant_id": ctx.tenant_id, "release_id": rel["id"], "group_id": grp["id"], "stage_pct": 5,
           "status": "running", "window_from": body.window_from, "window_to": body.window_to,
           "created_by": ctx.actor, "created_at": now_iso()}
    dbm.insert(ctx.conn, "firmware_rollouts", row)
    _push_stage(ctx, row, rel)
    ctx.audit("firmware.rollout_started", "firmware_rollout", row["id"], after=row)
    return 201, row


def _push_stage(ctx: Ctx, rollout: dict, release: dict) -> int:
    devices = dbm.all_(ctx.conn, "SELECT * FROM devices WHERE group_id = ? AND status <> 'decommissioned' ORDER BY id",
                       (rollout["group_id"],))
    target = max(1, round(len(devices) * rollout["stage_pct"] / 100)) if devices else 0
    n = 0
    for d in devices[:target]:
        if d["firmware"] == release["version"]:
            continue
        if dbm.one(ctx.conn, "SELECT 1 AS x FROM device_commands WHERE device_id = ? AND type = 'ota' AND status IN "
                             "('queued','sent')", (d["id"],)):
            continue
        dbm.insert(ctx.conn, "device_commands", {"id": new_id(), "tenant_id": ctx.tenant_id, "device_id": d["id"],
                                                 "type": "ota", "payload": dumps({"version": release["version"],
                                                                                  "sha256": release["sha256"],
                                                                                  "window": [rollout["window_from"],
                                                                                             rollout["window_to"]]}),
                                                 "reason": "rollout", "status": "queued", "result": None,
                                                 "created_by": ctx.actor, "created_at": now_iso(), "sent_at": None,
                                                 "acked_at": None})
        n += 1
    return n


@route("POST", "/api/v1/firmware/rollouts/{id}/{action}", perm="device.manage")
def rollout_action(ctx: Ctx):
    r = dbm.one(ctx.conn, "SELECT * FROM firmware_rollouts WHERE id = ? AND tenant_id = ?", (ctx.path["id"], ctx.tenant_id))
    if not r:
        raise not_found("Rollout")
    action = ctx.path["action"]
    rel = dbm.one(ctx.conn, "SELECT * FROM firmware_releases WHERE id = ?", (r["release_id"],))
    if action == "advance":
        if r["status"] != "running":
            raise conflict("Rollout is not running", "ROLLOUT_NOT_RUNNING")
        nxt = {5: 25, 25: 100}.get(r["stage_pct"])
        if nxt is None:
            dbm.update(ctx.conn, "firmware_rollouts", {"id": r["id"]}, {"status": "completed"})
        else:
            failed = dbm.scalar(ctx.conn, "SELECT COUNT(*) FROM device_commands c JOIN devices d ON d.id = c.device_id "
                                          "WHERE d.group_id = ? AND c.type = 'ota' AND c.status = 'failed' AND "
                                          "c.created_at >= ?", (r["group_id"], r["created_at"]))
            total = dbm.scalar(ctx.conn, "SELECT COUNT(*) FROM device_commands c JOIN devices d ON d.id = c.device_id "
                                         "WHERE d.group_id = ? AND c.type = 'ota' AND c.created_at >= ?",
                               (r["group_id"], r["created_at"]))
            if total and failed / total > 0.02:
                dbm.update(ctx.conn, "firmware_rollouts", {"id": r["id"]}, {"status": "paused"})
                raise conflict("Failure rate above 2%: rollout paused", "ROLLOUT_FAILURES", failed=failed, total=total)
            dbm.update(ctx.conn, "firmware_rollouts", {"id": r["id"]}, {"stage_pct": nxt})
            r["stage_pct"] = nxt
            _push_stage(ctx, r, rel)
    elif action == "pause":
        dbm.update(ctx.conn, "firmware_rollouts", {"id": r["id"]}, {"status": "paused"})
    elif action == "resume":
        dbm.update(ctx.conn, "firmware_rollouts", {"id": r["id"]}, {"status": "running"})
    elif action == "rollback":
        dbm.update(ctx.conn, "firmware_rollouts", {"id": r["id"]}, {"status": "rolled_back"})
        ctx.conn.execute("UPDATE device_commands SET status = 'failed', result = '{\"cancelled\":true}' WHERE type = 'ota' "
                         "AND status = 'queued' AND device_id IN (SELECT id FROM devices WHERE group_id = ?)",
                         (r["group_id"],))
    else:
        raise not_found("Action")
    ctx.audit(f"firmware.rollout_{action}", "firmware_rollout", r["id"])
    return dbm.one(ctx.conn, "SELECT * FROM firmware_rollouts WHERE id = ?", (r["id"],))


def status_from_health(health: dict, outbox: int, skew_ms: int | None, cfg: dict) -> str:
    degraded = (health.get("camera_fps", 30) < cfg.get("camera_fps_min", 10) or health.get("disk_pct", 0) > 85
                or (skew_ms is not None and abs(skew_ms) > 2000) or outbox > 1000 or health.get("camera_ok") is False)
    return "degraded" if degraded else "online"

