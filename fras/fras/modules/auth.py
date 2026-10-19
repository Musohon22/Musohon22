"""Authentication: login (+MFA), refresh rotation, logout, invites, own profile and MFA enrolment."""

from __future__ import annotations

import secrets
import time
from datetime import timedelta

import jwt
from pydantic import BaseModel, Field

from .. import db as dbm
from ..errors import ApiError, bad_request, forbidden, unauthorized, unprocessable
from ..http import Ctx, route
from ..security import crypto, passwords, tokens, totp
from ..security.permissions import ALL_PERMISSIONS, SYSTEM_ROLES
from ..services import tenancy
from ..util import dumps, iso, loads, new_id, now_iso, parse_dt, token, utcnow

LOCK_AFTER = 5
LOCK_MINUTES = 15
REFRESH_COOKIE = "fras_refresh"
PLATFORM_REFRESH_COOKIE = "fras_platform_refresh"


class LoginIn(BaseModel):
    org: str = Field(min_length=2, max_length=64)
    login: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=1, max_length=200)


class MfaIn(BaseModel):
    mfa_token: str
    code: str = Field(min_length=6, max_length=12)


class InviteIn(BaseModel):
    org: str
    token: str
    password: str = Field(min_length=10, max_length=200)


class PasswordIn(BaseModel):
    current: str
    new: str = Field(min_length=10, max_length=200)


class CodeIn(BaseModel):
    code: str = Field(min_length=6, max_length=6)


class PlatformLoginIn(BaseModel):
    email: str
    password: str
    code: str | None = None


def _history(ctx: Ctx, tenant_id, user_id, login, success, reason=None):
    dbm.insert(ctx.conn, "login_history", {"id": new_id(), "tenant_id": tenant_id, "user_id": user_id, "login": login,
                                           "success": 1 if success else 0, "reason": reason, "ip": ctx.info["ip"],
                                           "user_agent": ctx.info["user_agent"][:200], "created_at": now_iso()})


def _start_session(ctx: Ctx, *, user_id: str, tenant_id: str | None, realm: str, mfa: bool) -> dict:
    refresh = token(32)
    sid = new_id()
    s = ctx.settings
    dbm.insert(ctx.conn, "sessions", {"id": sid, "tenant_id": tenant_id, "user_id": user_id, "realm": realm,
                                      "refresh_hash": tokens.hash_token(refresh), "mfa_passed": 1 if mfa else 0,
                                      "ip": ctx.info["ip"], "user_agent": ctx.info["user_agent"][:200],
                                      "created_at": now_iso(),
                                      "expires_at": iso(utcnow() + timedelta(seconds=s.refresh_token_ttl_s)),
                                      "revoked_at": None})
    access = tokens.issue_access(s.secret_key, sub=user_id, realm=realm, tenant_id=tenant_id, session_id=sid,
                                 mfa=mfa, ttl_s=s.access_token_ttl_s)
    cookie = REFRESH_COOKIE if realm == "tenant" else PLATFORM_REFRESH_COOKIE
    path = "/api/v1/auth" if realm == "tenant" else "/api/v1/platform/auth"
    ctx.cookies.append({"key": cookie, "value": f"{sid}.{refresh}", "httponly": True, "samesite": "strict",
                        "secure": ctx.settings.is_prod, "path": path, "max_age": s.refresh_token_ttl_s})
    return {"access_token": access, "token_type": "Bearer", "expires_in": s.access_token_ttl_s}


def _mfa_token(ctx: Ctx, user_id: str, tenant_id: str) -> str:
    now = int(time.time())
    return jwt.encode({"sub": user_id, "tid": tenant_id, "realm": "mfa", "iat": now, "exp": now + 300},
                      ctx.settings.secret_key, algorithm="HS256")


@route("POST", "/api/v1/auth/login", auth="public", rate="login")
def login(ctx: Ctx, body: LoginIn):
    tenant = dbm.one(ctx.conn, "SELECT id, status FROM tenants WHERE slug = ?", (body.org.strip().lower(),))
    login_id = body.login.strip().lower()
    user = None
    if tenant and tenant["status"] == "active":
        user = dbm.one(ctx.conn, "SELECT * FROM users WHERE tenant_id = ? AND login = ?", (tenant["id"], login_id))
    if user and user["locked_until"] and parse_dt(user["locked_until"]) > utcnow():
        _history(ctx, tenant["id"], user["id"], login_id, False, "locked")
        raise ApiError(423, "ACCOUNT_LOCKED", "Too many failed attempts. Try again in 15 minutes.")
    ok = passwords.verify_secret(body.password, user["password_hash"] if user else None)
    ctx.keep_on_error = True
    if not ok or user["status"] != "active":
        if user:
            fails = user["failed_logins"] + 1
            lock = iso(utcnow() + timedelta(minutes=LOCK_MINUTES)) if fails >= LOCK_AFTER else None
            ctx.conn.execute("UPDATE users SET failed_logins = ?, locked_until = ? WHERE id = ?",
                             (0 if lock else fails, lock, user["id"]))
            _history(ctx, tenant["id"], user["id"], login_id, False, "bad_password" if not ok else user["status"])
            if lock:
                ctx.audit("auth.account_locked", "user", user["id"], tenant_id=tenant["id"])
                from ..services.alerts import raise_alert
                raise_alert(ctx.conn, tenant["id"], "login_failures", "medium",
                            {"user_id": user["id"], "login": login_id, "ip": ctx.info["ip"]})
        else:
            _history(ctx, tenant["id"] if tenant else None, None, login_id, False, "unknown")
        raise unauthorized("Login or password is incorrect", "INVALID_CREDENTIALS")
    ctx.conn.execute("UPDATE users SET failed_logins = 0, locked_until = NULL WHERE id = ?", (user["id"],))
    if user["mfa_enabled"]:
        return {"mfa_required": True, "mfa_token": _mfa_token(ctx, user["id"], tenant["id"])}
    ctx.conn.execute("UPDATE users SET last_login_at = ? WHERE id = ?", (now_iso(), user["id"]))
    _history(ctx, tenant["id"], user["id"], login_id, True)
    return _start_session(ctx, user_id=user["id"], tenant_id=tenant["id"], realm="tenant", mfa=False)


@route("POST", "/api/v1/auth/mfa", auth="public", rate="login")
def login_mfa(ctx: Ctx, body: MfaIn):
    try:
        claims = jwt.decode(body.mfa_token, ctx.settings.secret_key, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise unauthorized("MFA step expired, log in again", "MFA_TOKEN_INVALID")
    if claims.get("realm") != "mfa":
        raise unauthorized("MFA step expired, log in again", "MFA_TOKEN_INVALID")
    user = dbm.one(ctx.conn, "SELECT * FROM users WHERE id = ?", (claims["sub"],))
    if not user or user["status"] != "active":
        raise unauthorized()
    secret = crypto.open_sealed(ctx.dek(user["tenant_id"]), user["totp_secret_enc"], b"totp").decode()
    code = body.code.strip().lower()
    ok = totp.verify(secret, code)
    if not ok:
        codes = loads(user["backup_codes"], [])
        hashed = tokens.hash_token(code)
        if hashed in codes:
            codes.remove(hashed)
            ctx.conn.execute("UPDATE users SET backup_codes = ? WHERE id = ?", (dumps(codes), user["id"]))
            ok = True
    if not ok:
        _history(ctx, user["tenant_id"], user["id"], user["login"], False, "bad_mfa")
        raise unauthorized("Code is incorrect", "MFA_INVALID")
    ctx.conn.execute("UPDATE users SET last_login_at = ? WHERE id = ?", (now_iso(), user["id"]))
    _history(ctx, user["tenant_id"], user["id"], user["login"], True)
    return _start_session(ctx, user_id=user["id"], tenant_id=user["tenant_id"], realm="tenant", mfa=True)


def _rotate(ctx: Ctx, cookie_name: str, realm: str):
    if ctx.headers.get("x-requested-with") != "fras":
        raise forbidden("Missing anti-CSRF header", "CSRF")
    raw = ctx.cookies_in.get(cookie_name, "")
    sid, _, secret = raw.partition(".")
    sess = dbm.one(ctx.conn, "SELECT * FROM sessions WHERE id = ? AND realm = ?", (sid, realm))
    if not sess or sess["revoked_at"] or parse_dt(sess["expires_at"]) < utcnow():
        raise unauthorized("Session expired", "SESSION_EXPIRED")
    if tokens.hash_token(secret) != sess["refresh_hash"]:
        # Refresh token reuse: revoke the whole session (token theft signal).
        ctx.conn.execute("UPDATE sessions SET revoked_at = ? WHERE id = ?", (now_iso(), sid))
        raise unauthorized("Session revoked", "SESSION_REVOKED")
    ctx.conn.execute("UPDATE sessions SET revoked_at = ? WHERE id = ?", (now_iso(), sid))
    return _start_session(ctx, user_id=sess["user_id"], tenant_id=sess["tenant_id"], realm=realm,
                          mfa=bool(sess["mfa_passed"]))


@route("POST", "/api/v1/auth/refresh", auth="public", rate="login")
def refresh(ctx: Ctx):
    return _rotate(ctx, REFRESH_COOKIE, "tenant")


@route("POST", "/api/v1/auth/logout", mfa_exempt=True)
def logout(ctx: Ctx):
    ctx.conn.execute("UPDATE sessions SET revoked_at = ? WHERE id = ?", (now_iso(), ctx.p.session_id))
    ctx.cookies.append({"key": REFRESH_COOKIE, "value": "", "path": "/api/v1/auth", "max_age": 0})
    return {"ok": True}


@route("POST", "/api/v1/auth/accept-invite", auth="public", rate="login")
def accept_invite(ctx: Ctx, body: InviteIn):
    tenant = dbm.one(ctx.conn, "SELECT id FROM tenants WHERE slug = ?", (body.org.strip().lower(),))
    if not tenant:
        raise bad_request("Invitation is invalid", "INVITE_INVALID")
    user = dbm.one(ctx.conn, "SELECT * FROM users WHERE tenant_id = ? AND invite_token_hash = ?",
                   (tenant["id"], tokens.hash_token(body.token)))
    if not user or parse_dt(user["invite_expires_at"]) < utcnow():
        raise bad_request("Invitation is invalid or expired", "INVITE_INVALID")
    problems = passwords.password_problems(body.password)
    if problems:
        raise unprocessable("Password does not meet policy", "PASSWORD_WEAK", problems=problems)
    ctx.conn.execute("UPDATE users SET password_hash = ?, status = 'active', invite_token_hash = NULL, "
                     "invite_expires_at = NULL WHERE id = ?", (passwords.hash_secret(body.password), user["id"]))
    ctx.p.tenant_id = tenant["id"]
    ctx.p.id = user["id"]
    ctx.p.kind = "user"
    ctx.audit("user.invite_accepted", "user", user["id"])
    return {"ok": True, "login": user["login"]}


@route("GET", "/api/v1/me", mfa_exempt=True)
def me(ctx: Ctx):
    user = dbm.one(ctx.conn, "SELECT id, login, email, name, language, mfa_enabled, employee_id, telegram_chat_id "
                             "FROM users WHERE id = ?", (ctx.p.id,))
    tenant = dbm.one(ctx.conn, "SELECT id, slug, name, plan_code, deployment FROM tenants WHERE id = ?", (ctx.tenant_id,))
    sub = dbm.one(ctx.conn, "SELECT status, trial_ends_at, period_end FROM subscriptions WHERE tenant_id = ? "
                            "ORDER BY created_at DESC LIMIT 1", (ctx.tenant_id,))
    plan = tenancy.tenant_plan(ctx.conn, ctx.tenant_id)
    sites = dbm.all_(ctx.conn, "SELECT id, name, code, timezone FROM sites WHERE tenant_id = ? AND status = 'active' "
                               "ORDER BY name", (ctx.tenant_id,))
    allowed_sites = ctx.site_ids("attendance.read") if ctx.can("attendance.read") else set()
    if allowed_sites is not None:
        sites = [s for s in sites if s["id"] in allowed_sites]
    return {
        "user": {**user, "mfa_enabled": bool(user["mfa_enabled"]), "telegram_linked": bool(user["telegram_chat_id"])},
        "tenant": tenant,
        "subscription": sub,
        "plan": {"code": plan["code"], "name": plan["name"], "features": plan["features"], "limits": plan["limits"]},
        "permissions": sorted(ctx.p.perms),
        "roles": [{"code": r["role_code"], "name": SYSTEM_ROLES.get(r["role_code"], {}).get("name", r["role_code"]),
                   "scope_type": r["scope_type"], "scope_id": r["scope_id"]} for r in ctx.p.roles],
        "mfa_required": ctx.p.mfa_required,
        "mfa_relaxed": ctx.settings.relax_mfa,
        "sites": sites,
        "permission_labels": ALL_PERMISSIONS,
    }


@route("POST", "/api/v1/me/mfa/setup", mfa_exempt=True)
def mfa_setup(ctx: Ctx):
    user = dbm.one(ctx.conn, "SELECT login, mfa_enabled FROM users WHERE id = ?", (ctx.p.id,))
    if user["mfa_enabled"]:
        raise bad_request("MFA is already enabled", "MFA_ALREADY_ENABLED")
    secret = totp.new_secret()
    ctx.conn.execute("UPDATE users SET totp_secret_enc = ? WHERE id = ?",
                     (crypto.seal(ctx.dek(), secret.encode(), b"totp"), ctx.p.id))
    tenant = dbm.one(ctx.conn, "SELECT slug FROM tenants WHERE id = ?", (ctx.tenant_id,))
    return {"secret": secret, "otpauth_uri": totp.provisioning_uri(secret, f"{tenant['slug']}:{user['login']}")}


@route("POST", "/api/v1/me/mfa/enable", mfa_exempt=True)
def mfa_enable(ctx: Ctx, body: CodeIn):
    user = dbm.one(ctx.conn, "SELECT totp_secret_enc, mfa_enabled FROM users WHERE id = ?", (ctx.p.id,))
    if not user["totp_secret_enc"]:
        raise bad_request("Start MFA setup first", "MFA_NOT_STARTED")
    secret = crypto.open_sealed(ctx.dek(), user["totp_secret_enc"], b"totp").decode()
    if not totp.verify(secret, body.code):
        raise unprocessable("Code is incorrect", "MFA_INVALID")
    codes = totp.backup_codes()
    ctx.conn.execute("UPDATE users SET mfa_enabled = 1, backup_codes = ? WHERE id = ?",
                     (dumps([tokens.hash_token(c) for c in codes]), ctx.p.id))
    ctx.audit("user.mfa_enabled", "user", ctx.p.id)
    return {"enabled": True, "backup_codes": codes}


@route("POST", "/api/v1/me/password", mfa_exempt=True)
def change_password(ctx: Ctx, body: PasswordIn):
    user = dbm.one(ctx.conn, "SELECT password_hash FROM users WHERE id = ?", (ctx.p.id,))
    if not passwords.verify_secret(body.current, user["password_hash"]):
        raise unprocessable("Current password is incorrect", "PASSWORD_MISMATCH")
    problems = passwords.password_problems(body.new)
    if problems:
        raise unprocessable("Password does not meet policy", "PASSWORD_WEAK", problems=problems)
    ctx.conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (passwords.hash_secret(body.new), ctx.p.id))
    ctx.conn.execute("UPDATE sessions SET revoked_at = ? WHERE user_id = ? AND id <> ? AND revoked_at IS NULL",
                     (now_iso(), ctx.p.id, ctx.p.session_id))
    ctx.audit("user.password_changed", "user", ctx.p.id)
    return {"ok": True}


class LanguageIn(BaseModel):
    language: str = Field(pattern="^(uz|ru|en)$")


@route("PATCH", "/api/v1/me", mfa_exempt=True)
def update_me(ctx: Ctx, body: LanguageIn):
    ctx.conn.execute("UPDATE users SET language = ? WHERE id = ?", (body.language, ctx.p.id))
    return {"ok": True}


@route("POST", "/api/v1/me/telegram-link", mfa_exempt=True)
def telegram_link(ctx: Ctx):
    """One-time code the user sends to the bot; the bot webhook binds the chat id."""
    code = f"{secrets.randbelow(1_000_000):06d}"
    ctx.state.telegram_codes[code] = (ctx.p.id, time.time() + 600)
    return {"code": code, "expires_in": 600, "bot_hint": "Send /link <code> to the company bot"}


# ----------------------------------------------------------------- platform realm

@route("POST", "/api/v1/platform/auth/login", auth="public", rate="login")
def platform_login(ctx: Ctx, body: PlatformLoginIn):
    user = dbm.one(ctx.conn, "SELECT * FROM platform_users WHERE email = ?", (body.email.strip().lower(),))
    if not user or not passwords.verify_secret(body.password, user["password_hash"]) or user["status"] != "active":
        _history(ctx, None, user["id"] if user else None, body.email, False, "bad_password")
        raise unauthorized("Login or password is incorrect", "INVALID_CREDENTIALS")
    if user["mfa_enabled"]:
        if not body.code:
            return {"mfa_required": True}
        if not totp.verify(crypto.open_sealed(ctx.settings.master_key, bytes.fromhex(user["totp_secret"]),
                                              b"platform-totp").decode(), body.code):
            raise unauthorized("Code is incorrect", "MFA_INVALID")
    _history(ctx, None, user["id"], body.email, True)
    ctx.p.kind, ctx.p.id = "platform", user["id"]
    ctx.audit("platform.login", "platform_user", user["id"], tenant_id=None)
    return _start_session(ctx, user_id=user["id"], tenant_id=None, realm="platform", mfa=bool(user["mfa_enabled"]))


@route("POST", "/api/v1/platform/auth/refresh", auth="public", rate="login")
def platform_refresh(ctx: Ctx):
    return _rotate(ctx, PLATFORM_REFRESH_COOKIE, "platform")


@route("POST", "/api/v1/platform/auth/logout", auth="platform")
def platform_logout(ctx: Ctx):
    ctx.conn.execute("UPDATE sessions SET revoked_at = ? WHERE id = ?", (now_iso(), ctx.p.session_id))
    ctx.cookies.append({"key": PLATFORM_REFRESH_COOKIE, "value": "", "path": "/api/v1/platform/auth", "max_age": 0})
    return {"ok": True}


@route("GET", "/api/v1/platform/me", auth="platform")
def platform_me(ctx: Ctx):
    u = dbm.one(ctx.conn, "SELECT id, email, name, role, mfa_enabled FROM platform_users WHERE id = ?", (ctx.p.id,))
    return {"user": u}
