"""Laptop self check-in with a passkey (Windows Hello / platform authenticator).

Windows Hello verifies the person on the laptop itself (face via the IR camera with its own
anti-spoofing, fingerprint, or the Hello PIN) and signs our challenge with a TPM-held key; the
server checks that signature. The face never reaches the server, and the protocol does not say
whether Hello used face or PIN — so the controls around it matter:
  * only device-bound credentials (no synced passkeys that could sit on someone else's phone),
  * HR approval of every registered laptop,
  * office networks: outside them a check-in is denied or sent to HR review,
  * clone detection via the signature counter, single-use challenges, append-only events.
"""

from __future__ import annotations

import ipaddress
import json
import secrets
from datetime import timedelta
from urllib.parse import urlsplit

from pydantic import BaseModel, Field

from .. import db as dbm
from ..errors import ApiError, conflict, forbidden, not_found, unprocessable
from ..http import Ctx, route
from ..live import broker
from ..security import webauthn as wa
from ..services import attendance_svc, settings_svc
from ..services.alerts import raise_alert
from ..util import dumps, iso, new_id, now_iso, parse_dt, utcnow

CHALLENGE_TTL = timedelta(minutes=5)


class RegisterIn(BaseModel):
    credential_id: str = Field(max_length=1400)
    client_data_json: str = Field(max_length=4000)
    attestation_object: str = Field(max_length=20000)
    label: str = Field(default="Noutbuk", min_length=1, max_length=60)


class CheckinOptionsIn(BaseModel):
    direction: str = Field(pattern="^(in|out)$")


class CheckinIn(BaseModel):
    credential_id: str = Field(max_length=1400)
    client_data_json: str = Field(max_length=4000)
    authenticator_data: str = Field(max_length=4000)
    signature: str = Field(max_length=2000)


class RevokeIn(BaseModel):
    reason: str = Field(min_length=3, max_length=300)


def _rp(ctx: Ctx) -> tuple[str, set[str]]:
    u = urlsplit(ctx.settings.public_base_url)
    return u.hostname or "localhost", {f"{u.scheme}://{u.netloc}"}


def _policy(ctx: Ctx) -> dict:
    return settings_svc.get(ctx.conn, ctx.tenant_id, "self_checkin")


def _inside(policy: dict, ip: str | None) -> bool:
    try:
        addr = ipaddress.ip_address(ip or "")
    except ValueError:
        return False
    return any(addr in ipaddress.ip_network(n, strict=False) for n in policy["allowed_networks"])


def _employee(ctx: Ctx) -> dict:
    ctx.require("self.request")
    if not ctx.p.employee_id:
        raise forbidden("This account is not linked to an employee", "NOT_AN_EMPLOYEE")
    emp = dbm.one(ctx.conn, "SELECT e.*, s.timezone FROM employees e JOIN sites s ON s.id = e.site_id WHERE e.id = ?",
                  (ctx.p.employee_id,))
    if not emp or emp["status"] != "active":
        raise forbidden("Employee is not active", "EMPLOYEE_INACTIVE")
    return emp


def _new_challenge(ctx: Ctx, kind: str) -> str:
    ch = wa.b64url(secrets.token_bytes(32))
    dbm.insert(ctx.conn, "webauthn_challenges", {"id": new_id(), "tenant_id": ctx.tenant_id, "user_id": ctx.p.id,
                                                  "kind": kind, "challenge": ch,
                                                  "expires_at": iso(utcnow() + CHALLENGE_TTL), "used_at": None})
    return ch


def _take_challenge(ctx: Ctx, client_data_json: bytes, kinds: tuple[str, ...]) -> dict:
    """Single use: the challenge is burned before verification, so a replay always fails."""
    try:
        ch = json.loads(client_data_json).get("challenge", "")
    except (ValueError, AttributeError):
        raise unprocessable("clientDataJSON is not JSON", "WEBAUTHN_MALFORMED")
    row = dbm.one(ctx.conn, "SELECT * FROM webauthn_challenges WHERE challenge = ? AND tenant_id = ? AND user_id = ?",
                  (ch, ctx.tenant_id, ctx.p.id))
    if not row or row["kind"] not in kinds or row["used_at"] or parse_dt(row["expires_at"]) < utcnow():
        raise unprocessable("The request expired or was already used. Try again.", "WEBAUTHN_CHALLENGE")
    ctx.conn.execute("UPDATE webauthn_challenges SET used_at = ? WHERE id = ?", (now_iso(), row["id"]))
    return row


def _cred_view(c: dict) -> dict:
    return {"id": c["id"], "label": c["label"], "status": c["status"], "created_at": c["created_at"],
            "last_used_at": c["last_used_at"], "approved_at": c["approved_at"], "revoked_at": c["revoked_at"],
            "authenticator": wa.KNOWN_AAGUIDS.get(c["aaguid"] or "", "Platforma autentifikatori"),
            "credential_id": c["credential_id"]}


def _wa_error(e: wa.WebAuthnError) -> ApiError:
    return unprocessable(str(e), e.code)


# ----------------------------------------------------------------- employee side (portal)

@route("GET", "/api/v1/portal/passkeys", perm="self.read", mfa_exempt=True)
def my_passkeys(ctx: Ctx):
    rows = dbm.all_(ctx.conn, "SELECT * FROM webauthn_credentials WHERE tenant_id = ? AND user_id = ? AND status <> 'revoked' "
                              "ORDER BY created_at", (ctx.tenant_id, ctx.p.id))
    pol = _policy(ctx)
    return {"items": [_cred_view(r) for r in rows],
            "policy": {"enabled": pol["enabled"], "require_approval": pol["require_approval"],
                       "on_office_network": _inside(pol, ctx.info.get("ip")),
                       "networks_configured": bool(pol["allowed_networks"]), "outside_network": pol["outside_network"]}}


@route("POST", "/api/v1/portal/passkeys/options", perm="self.request", mfa_exempt=True)
def register_options(ctx: Ctx):
    emp = _employee(ctx)
    pol = _policy(ctx)
    if not pol["enabled"]:
        raise forbidden("Laptop check-in is not enabled by your organisation", "SELF_CHECKIN_DISABLED")
    if pol["allowed_networks"] and not _inside(pol, ctx.info.get("ip")):
        raise forbidden("Register the laptop while connected to the office network", "OUTSIDE_OFFICE_NETWORK")
    existing = dbm.all_(ctx.conn, "SELECT credential_id FROM webauthn_credentials WHERE tenant_id = ? AND user_id = ? AND "
                                  "status <> 'revoked'", (ctx.tenant_id, ctx.p.id))
    if len(existing) >= int(pol["max_per_employee"]):
        raise conflict("Device limit reached — remove an old laptop first", "PASSKEY_LIMIT")
    rp_id, _ = _rp(ctx)
    user = dbm.one(ctx.conn, "SELECT login, name FROM users WHERE id = ?", (ctx.p.id,))
    return {"challenge": _new_challenge(ctx, "register"),
            "rp": {"id": rp_id, "name": "FRAS davomat"},
            "user": {"id": wa.b64url(ctx.p.id.encode()), "name": f"{user['login']}@{rp_id}",
                     "displayName": f"{emp['last_name']} {emp['first_name']}"},
            "pubKeyCredParams": [{"type": "public-key", "alg": a} for a in wa.SUPPORTED_ALGS],
            "authenticatorSelection": {"authenticatorAttachment": "platform", "userVerification": "required",
                                       "residentKey": "discouraged"},
            "excludeCredentials": [{"type": "public-key", "id": r["credential_id"]} for r in existing],
            "attestation": "none", "timeout": int(CHALLENGE_TTL.total_seconds() * 1000)}


@route("POST", "/api/v1/portal/passkeys", perm="self.request", mfa_exempt=True)
def register(ctx: Ctx, body: RegisterIn):
    emp = _employee(ctx)
    pol = _policy(ctx)
    if not pol["enabled"]:
        raise forbidden("Laptop check-in is not enabled by your organisation", "SELF_CHECKIN_DISABLED")
    cdj = wa.b64url_decode(body.client_data_json)
    ch = _take_challenge(ctx, cdj, ("register",))
    rp_id, origins = _rp(ctx)
    try:
        reg = wa.verify_registration(client_data_json=cdj, attestation_object=wa.b64url_decode(body.attestation_object),
                                     challenge=ch["challenge"], rp_id=rp_id, origins=origins)
    except wa.WebAuthnError as e:
        raise _wa_error(e)
    if wa.b64url(reg.credential_id) != body.credential_id:
        raise unprocessable("credential id mismatch", "WEBAUTHN_MALFORMED")
    if pol["device_bound_only"] and reg.backup_eligible:
        raise unprocessable("This passkey is synced to the cloud (phone/password manager) and could be used on other "
                            "devices. Use Windows Hello on this laptop.", "PASSKEY_SYNCED_NOT_ALLOWED")
    if dbm.one(ctx.conn, "SELECT 1 AS x FROM webauthn_credentials WHERE credential_id = ?", (body.credential_id,)):
        raise conflict("This laptop is already registered", "PASSKEY_EXISTS")
    status = "pending" if pol["require_approval"] else "active"
    row = {"id": new_id(), "tenant_id": ctx.tenant_id, "user_id": ctx.p.id, "employee_id": emp["id"],
           "credential_id": body.credential_id, "alg": reg.alg, "public_key": reg.public_key,
           "sign_count": reg.sign_count, "aaguid": reg.aaguid, "label": body.label.strip(),
           "backup_eligible": 1 if reg.backup_eligible else 0, "status": status, "created_ip": ctx.info.get("ip"),
           "created_at": now_iso(), "approved_by": None if status == "pending" else "policy",
           "approved_at": None if status == "pending" else now_iso(), "last_used_at": None, "revoked_at": None,
           "revoked_by": None, "revoke_reason": None}
    dbm.insert(ctx.conn, "webauthn_credentials", row)
    ctx.audit("passkey.registered", "employee", emp["id"],
              after={"credential": row["id"], "label": row["label"], "status": status, "aaguid": reg.aaguid, "fmt": reg.fmt})
    if status == "pending":
        from ..services import notify
        notify.notify_permission(ctx.conn, ctx.tenant_id, "employee.write", "passkey_pending",
                                 "Yangi noutbuk tasdiq kutmoqda",
                                 f"{emp['last_name']} {emp['first_name']} ({emp['personnel_no']}): {row['label']}",
                                 "/app/settings/self_checkin", site_id=emp["site_id"])
    return 201, _cred_view(row)


@route("DELETE", "/api/v1/portal/passkeys/{id}", perm="self.request", mfa_exempt=True)
def remove_mine(ctx: Ctx):
    c = dbm.one(ctx.conn, "SELECT * FROM webauthn_credentials WHERE id = ? AND tenant_id = ? AND user_id = ?",
                (ctx.path["id"], ctx.tenant_id, ctx.p.id))
    if not c or c["status"] == "revoked":
        raise not_found("Passkey")
    _revoke(ctx, c, "removed by employee")
    return {"ok": True}


@route("POST", "/api/v1/portal/checkin/options", perm="self.request", mfa_exempt=True)
def checkin_options(ctx: Ctx, body: CheckinOptionsIn):
    _employee(ctx)
    if not _policy(ctx)["enabled"]:
        raise forbidden("Laptop check-in is not enabled by your organisation", "SELF_CHECKIN_DISABLED")
    creds = dbm.all_(ctx.conn, "SELECT credential_id FROM webauthn_credentials WHERE tenant_id = ? AND user_id = ? AND "
                               "status = 'active'", (ctx.tenant_id, ctx.p.id))
    if not creds:
        raise conflict("No approved laptop yet", "NO_ACTIVE_PASSKEY")
    rp_id, _ = _rp(ctx)
    return {"challenge": _new_challenge(ctx, f"checkin:{body.direction}"), "rpId": rp_id,
            "allowCredentials": [{"type": "public-key", "id": c["credential_id"], "transports": ["internal"]} for c in creds],
            "userVerification": "required", "timeout": 60000}


@route("POST", "/api/v1/portal/checkin", perm="self.request", mfa_exempt=True)
def checkin(ctx: Ctx, body: CheckinIn):
    emp = _employee(ctx)
    pol = _policy(ctx)
    if not pol["enabled"]:
        raise forbidden("Laptop check-in is not enabled by your organisation", "SELF_CHECKIN_DISABLED")
    cdj = wa.b64url_decode(body.client_data_json)
    ch = _take_challenge(ctx, cdj, ("checkin:in", "checkin:out"))
    ctx.keep_on_error = True        # the burned challenge and any alert must survive a rejection
    cred = dbm.one(ctx.conn, "SELECT * FROM webauthn_credentials WHERE credential_id = ? AND tenant_id = ? AND user_id = ?",
                   (body.credential_id, ctx.tenant_id, ctx.p.id))
    if not cred or cred["status"] != "active":
        raise forbidden("This laptop is not approved for check-in", "PASSKEY_NOT_ACTIVE")
    rp_id, origins = _rp(ctx)
    try:
        ad = wa.verify_assertion(client_data_json=cdj, authenticator_data=wa.b64url_decode(body.authenticator_data),
                                 signature=wa.b64url_decode(body.signature), challenge=ch["challenge"], rp_id=rp_id,
                                 origins=origins, alg=cred["alg"], public_key=cred["public_key"])
    except wa.WebAuthnError as e:
        raise _wa_error(e)
    if (ad.sign_count or cred["sign_count"]) and ad.sign_count <= cred["sign_count"]:
        # A counter that goes backwards means two copies of the key exist.
        _revoke(ctx, cred, "signature counter went backwards (possible clone)", by="system")
        raise_alert(ctx.conn, ctx.tenant_id, "passkey_clone", "high",
                    {"employee_id": emp["id"], "credential": cred["id"], "stored": cred["sign_count"], "got": ad.sign_count},
                    site_id=emp["site_id"])
        raise forbidden("This laptop key was blocked for security reasons. Contact HR.", "PASSKEY_CLONED")
    ctx.conn.execute("UPDATE webauthn_credentials SET sign_count = ?, last_used_at = ? WHERE id = ?",
                     (ad.sign_count, now_iso(), cred["id"]))
    direction = ch["kind"].split(":", 1)[1]
    inside = _inside(pol, ctx.info.get("ip"))
    flags = ["self_checkin", "user_verified"] + ([] if inside else ["outside_network"])
    if not inside and pol["outside_network"] == "deny":
        result = "denied"
    elif not inside:
        result = "review"
    else:
        rules = settings_svc.get(ctx.conn, ctx.tenant_id, "attendance_rules")
        since = iso(utcnow() - timedelta(minutes=int(rules["debounce_min"])))
        dup = dbm.one(ctx.conn, "SELECT 1 AS x FROM attendance_events WHERE tenant_id = ? AND employee_id = ? AND direction = ? "
                                "AND result IN ('accepted','review') AND captured_at >= ?",
                      (ctx.tenant_id, emp["id"], direction, since))
        result = "duplicate" if dup else "accepted"
    row = {"id": new_id(), "tenant_id": ctx.tenant_id, "device_id": None, "device_seq": None, "employee_id": emp["id"],
           "access_point_id": None, "site_id": emp["site_id"], "direction": direction, "method": "passkey",
           "result": result, "score": None, "liveness_score": None, "model_version": wa.KNOWN_AAGUIDS.get(cred["aaguid"] or ""),
           "captured_at": now_iso(), "received_at": now_iso(), "clock_suspect": 0, "late_arrival": 0,
           "flags": dumps(flags), "capture_ref": None, "signature": None}
    dbm.insert(ctx.conn, "attendance_events", row)
    if result in ("accepted", "review"):
        attendance_svc.on_event(ctx.conn, ctx.tenant_id, row)
    if not inside:
        raise_alert(ctx.conn, ctx.tenant_id, "self_checkin_outside", "medium" if result == "review" else "low",
                    {"employee_id": emp["id"], "ip": ctx.info.get("ip"), "result": result}, event_id=row["id"],
                    site_id=emp["site_id"])
    broker.publish(f"tenant:{ctx.tenant_id}", {
        "type": "event", "id": row["id"], "captured_at": row["captured_at"], "direction": direction, "result": result,
        "method": "passkey", "access_point": "Noutbuk (Windows Hello)", "late": False, "employee_id": emp["id"],
        "site_id": emp["site_id"], "department_id": emp["department_id"], "team": emp["team"],
        "name": f"{emp['last_name']} {emp['first_name']}"})
    ctx.audit("attendance.self_checkin", "employee", emp["id"],
              after={"event": row["id"], "direction": direction, "result": result, "credential": cred["id"]})
    messages = {"accepted": "Kirish qayd etildi" if direction == "in" else "Chiqish qayd etildi",
                "duplicate": "Siz allaqachon qayd etilgansiz",
                "review": "Qayd yozildi, lekin korxona tarmog'idan tashqarida — HR tekshiradi",
                "denied": "Korxona tarmog'idan tashqarida qayd qilib bo'lmaydi"}
    return {"result": result, "direction": direction, "event_id": row["id"], "captured_at": row["captured_at"],
            "message": messages[result]}


# ----------------------------------------------------------------- HR side

def _revoke(ctx: Ctx, cred: dict, reason: str, by: str | None = None) -> None:
    ctx.conn.execute("UPDATE webauthn_credentials SET status = 'revoked', revoked_at = ?, revoked_by = ?, revoke_reason = ? "
                     "WHERE id = ?", (now_iso(), by or ctx.actor, reason, cred["id"]))
    ctx.audit("passkey.revoked", "employee", cred["employee_id"], after={"credential": cred["id"], "reason": reason})


@route("GET", "/api/v1/passkeys", perm="employee.read")
def list_passkeys(ctx: Ctx):
    scope_sql, params = ctx.employee_filter("employee.read")
    where, p = ["c.tenant_id = ?", scope_sql], [ctx.tenant_id, *params]
    if ctx.q("status"):
        where.append("c.status = ?")
        p.append(ctx.q("status"))
    else:
        where.append("c.status <> 'revoked'")
    rows = dbm.all_(ctx.conn, f"SELECT c.*, e.first_name, e.last_name, e.personnel_no FROM webauthn_credentials c JOIN "
                              f"employees e ON e.id = c.employee_id WHERE {' AND '.join(where)} ORDER BY "
                              f"CASE c.status WHEN 'pending' THEN 0 ELSE 1 END, c.created_at DESC", p)
    return {"items": [{**_cred_view(r), "employee_id": r["employee_id"], "created_ip": r["created_ip"],
                       "employee": f"{r['last_name']} {r['first_name']}", "personnel_no": r["personnel_no"]} for r in rows]}


def _hr_cred(ctx: Ctx) -> dict:
    c = dbm.one(ctx.conn, "SELECT * FROM webauthn_credentials WHERE id = ? AND tenant_id = ?", (ctx.path["id"], ctx.tenant_id))
    if not c:
        raise not_found("Passkey")
    emp = dbm.one(ctx.conn, "SELECT * FROM employees WHERE id = ?", (c["employee_id"],))
    ctx.require_employee("employee.write", emp)
    return c


@route("POST", "/api/v1/passkeys/{id}/approve", perm="employee.write")
def approve(ctx: Ctx):
    c = _hr_cred(ctx)
    if c["status"] != "pending":
        raise conflict("Only pending laptops can be approved", "PASSKEY_NOT_PENDING")
    if c["user_id"] == ctx.actor:
        raise forbidden("You cannot approve your own laptop", "SELF_APPROVAL")
    ctx.conn.execute("UPDATE webauthn_credentials SET status = 'active', approved_by = ?, approved_at = ? WHERE id = ?",
                     (ctx.actor, now_iso(), c["id"]))
    ctx.audit("passkey.approved", "employee", c["employee_id"], after={"credential": c["id"]})
    return {"ok": True}


@route("POST", "/api/v1/passkeys/{id}/revoke", perm="employee.write")
def revoke(ctx: Ctx, body: RevokeIn):
    c = _hr_cred(ctx)
    if c["status"] == "revoked":
        raise conflict("Already revoked", "PASSKEY_REVOKED")
    _revoke(ctx, c, body.reason)
    return {"ok": True}
