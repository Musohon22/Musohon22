"""Admin users, role assignments, custom roles, sessions and login history (SCR-70 … SCR-72)."""

from __future__ import annotations

from datetime import date, timedelta

from pydantic import BaseModel, Field

from .. import db as dbm
from ..errors import conflict, forbidden, not_found, unprocessable
from ..http import Ctx, page_params, paged, route
from ..security import tokens
from ..security.permissions import ALL_PERMISSIONS, SITE_ADMIN_GRANTABLE, SYSTEM_ROLES
from ..services import notify, tenancy
from ..util import dumps, iso, loads, new_id, now_iso, token, utcnow


class RoleAssignIn(BaseModel):
    role_code: str
    scope_type: str = Field(pattern="^(global|site|department|team|self)$")
    scope_id: str | None = None
    valid_until: date | None = None


class UserIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", max_length=160)
    roles: list[RoleAssignIn] = Field(min_length=1)
    employee_id: str | None = None
    language: str = Field(default="uz", pattern="^(uz|ru|en)$")


class BlockIn(BaseModel):
    reason: str = Field(min_length=5, max_length=300)


class CustomRoleIn(BaseModel):
    code: str = Field(min_length=3, max_length=40, pattern=r"^[a-z0-9_]+$")
    name: str = Field(min_length=2, max_length=80)
    permissions: list[str]


def _can_grant(ctx: Ctx, assign: RoleAssignIn) -> None:
    custom = dbm.one(ctx.conn, "SELECT code FROM roles WHERE tenant_id = ? AND code = ?", (ctx.tenant_id, assign.role_code))
    if assign.role_code not in SYSTEM_ROLES and not custom:
        raise unprocessable("Unknown role", "ROLE_UNKNOWN", role=assign.role_code)
    if assign.role_code == "super_admin" and not ctx.is_global("user.manage"):
        raise forbidden("Only a super admin can grant super admin", "ROLE_NOT_GRANTABLE")
    if not ctx.is_global("user.manage"):
        if assign.role_code not in SITE_ADMIN_GRANTABLE:
            raise forbidden("Role cannot be granted by a site admin", "ROLE_NOT_GRANTABLE")
        if assign.scope_type == "global":
            raise forbidden("Site admins can only grant site-scoped roles", "SCOPE_TOO_WIDE")
    if assign.scope_type != "global" and not assign.scope_id and assign.scope_type != "self":
        raise unprocessable("scope_id is required", "SCOPE_ID_REQUIRED")
    if assign.scope_type == "site":
        ctx.require_site("user.manage", assign.scope_id)
    elif assign.scope_type in ("department", "team"):
        dept_id = (assign.scope_id or "").split(":")[0]
        dept = dbm.one(ctx.conn, "SELECT site_id FROM departments WHERE id = ? AND tenant_id = ?", (dept_id, ctx.tenant_id))
        if not dept:
            raise unprocessable("Unknown department", "DEPARTMENT_UNKNOWN")
        ctx.require_site("user.manage", dept["site_id"])
        if assign.scope_type == "team" and ":" not in assign.scope_id:
            raise unprocessable("Team scope is 'department_id:team'", "SCOPE_ID_INVALID")


def _user_view(conn, u: dict) -> dict:
    roles = dbm.all_(conn, "SELECT id, role_code, scope_type, scope_id, valid_until FROM user_roles WHERE user_id = ?",
                     (u["id"],))
    for r in roles:
        r["role_name"] = SYSTEM_ROLES.get(r["role_code"], {}).get("name", r["role_code"])
    return {"id": u["id"], "login": u["login"], "email": u["email"], "name": u["name"], "status": u["status"],
            "mfa_enabled": bool(u["mfa_enabled"]), "employee_id": u["employee_id"], "language": u["language"],
            "last_login_at": u.get("last_login_at"), "created_at": u["created_at"], "roles": roles,
            "source": "local", "locked": bool(u.get("locked_until") and u["locked_until"] > now_iso())}


@route("GET", "/api/v1/users", perm="user.manage")
def list_users(ctx: Ctx):
    limit, offset = page_params(ctx)
    where, params = ["u.tenant_id = ?"], [ctx.tenant_id]
    if ctx.q("q"):
        where.append("(lower(u.name) LIKE ? OR lower(u.login) LIKE ?)")
        params += [f"%{ctx.q('q').lower()}%"] * 2
    if ctx.q("kind", "admins") == "admins":
        where.append("EXISTS (SELECT 1 FROM user_roles r WHERE r.user_id = u.id AND r.role_code <> 'employee')")
    total = dbm.scalar(ctx.conn, f"SELECT COUNT(*) FROM users u WHERE {' AND '.join(where)}", params)
    rows = dbm.all_(ctx.conn, f"SELECT u.* FROM users u WHERE {' AND '.join(where)} ORDER BY u.name LIMIT ? OFFSET ?",
                    [*params, limit, offset])
    allowed = ctx.site_ids("user.manage")
    items = [_user_view(ctx.conn, u) for u in rows]
    if allowed is not None:
        items = [i for i in items if all(r["scope_type"] != "global" for r in i["roles"])]
    return paged(items, total, limit, offset)


@route("POST", "/api/v1/users", perm="user.manage")
def invite(ctx: Ctx, body: UserIn):
    email = body.email.lower()
    if dbm.one(ctx.conn, "SELECT 1 AS x FROM users WHERE tenant_id = ? AND login = ?", (ctx.tenant_id, email)):
        raise conflict("A user with this email already exists", "USER_EXISTS")
    for r in body.roles:
        _can_grant(ctx, r)
    if any(r.role_code != "employee" for r in body.roles):
        tenancy.check_limit(ctx.conn, ctx.tenant_id, "admins")
    invite_token = token(24)
    user = {"id": new_id(), "tenant_id": ctx.tenant_id, "login": email, "email": email, "name": body.name,
            "status": "invited", "mfa_enabled": 0, "employee_id": body.employee_id, "language": body.language,
            "invite_token_hash": tokens.hash_token(invite_token),
            "invite_expires_at": iso(utcnow() + timedelta(hours=48)), "created_at": now_iso()}
    dbm.insert(ctx.conn, "users", user)
    for r in body.roles:
        dbm.insert(ctx.conn, "user_roles", {"id": new_id(), "tenant_id": ctx.tenant_id, "user_id": user["id"],
                                            "role_code": r.role_code, "scope_type": r.scope_type, "scope_id": r.scope_id,
                                            "valid_until": r.valid_until.isoformat() if r.valid_until else None,
                                            "created_by": ctx.actor, "created_at": now_iso()})
    tenant = dbm.one(ctx.conn, "SELECT slug FROM tenants WHERE id = ?", (ctx.tenant_id,))
    link = f"{ctx.settings.public_base_url}/app/invite?org={tenant['slug']}&token={invite_token}"
    notify.enqueue(ctx.conn, ctx.tenant_id, "email", email, {"subject": "FRAS taklifnomasi",
                                                             "body": f"Hisobingizni faollashtiring (48 soat): {link}"})
    ctx.audit("user.invited", "user", user["id"], after={**user, "roles": [r.model_dump(mode="json") for r in body.roles]})
    return 201, {**_user_view(ctx.conn, user), "invite_link": link}


def _get_user(ctx: Ctx) -> dict:
    u = dbm.one(ctx.conn, "SELECT * FROM users WHERE id = ? AND tenant_id = ?", (ctx.path["id"], ctx.tenant_id))
    if not u:
        raise not_found("User")
    if not ctx.is_global("user.manage"):
        if dbm.one(ctx.conn, "SELECT 1 AS x FROM user_roles WHERE user_id = ? AND scope_type = 'global'", (u["id"],)):
            raise forbidden("This user is managed by organisation-wide admins")
    return u


@route("GET", "/api/v1/users/{id}", perm="user.manage")
def get_user(ctx: Ctx):
    u = _get_user(ctx)
    out = _user_view(ctx.conn, u)
    out["sessions"] = dbm.all_(ctx.conn, "SELECT id, ip, user_agent, created_at, expires_at FROM sessions WHERE user_id = ? "
                                         "AND revoked_at IS NULL AND expires_at > ? ORDER BY created_at DESC",
                               (u["id"], now_iso()))
    return out


@route("POST", "/api/v1/users/{id}/roles", perm="user.manage")
def add_role(ctx: Ctx, body: RoleAssignIn):
    u = _get_user(ctx)
    _can_grant(ctx, body)
    row = {"id": new_id(), "tenant_id": ctx.tenant_id, "user_id": u["id"], "role_code": body.role_code,
           "scope_type": body.scope_type, "scope_id": body.scope_id,
           "valid_until": body.valid_until.isoformat() if body.valid_until else None, "created_by": ctx.actor,
           "created_at": now_iso()}
    dbm.insert(ctx.conn, "user_roles", row)
    ctx.audit("user.role_added", "user", u["id"], after=row)
    return 201, row


@route("DELETE", "/api/v1/users/{id}/roles/{role_id}", perm="user.manage")
def remove_role(ctx: Ctx):
    u = _get_user(ctx)
    r = dbm.one(ctx.conn, "SELECT * FROM user_roles WHERE id = ? AND user_id = ?", (ctx.path["role_id"], u["id"]))
    if not r:
        raise not_found("Role assignment")
    if r["role_code"] == "super_admin":
        left = dbm.scalar(ctx.conn, "SELECT COUNT(*) FROM user_roles ur JOIN users x ON x.id = ur.user_id WHERE "
                                    "ur.tenant_id = ? AND ur.role_code = 'super_admin' AND x.status = 'active'",
                          (ctx.tenant_id,))
        if left <= 1:
            raise conflict("The last super admin cannot be removed", "LAST_SUPER_ADMIN")
    ctx.conn.execute("DELETE FROM user_roles WHERE id = ?", (r["id"],))
    ctx.audit("user.role_removed", "user", u["id"], before=r)
    return {"ok": True}


@route("POST", "/api/v1/users/{id}/block", perm="user.manage")
def block(ctx: Ctx, body: BlockIn):
    u = _get_user(ctx)
    if u["id"] == ctx.actor:
        raise unprocessable("You cannot block yourself", "SELF_BLOCK")
    dbm.update(ctx.conn, "users", {"id": u["id"]}, {"status": "blocked"})
    ctx.conn.execute("UPDATE sessions SET revoked_at = ? WHERE user_id = ? AND revoked_at IS NULL", (now_iso(), u["id"]))
    ctx.audit("user.blocked", "user", u["id"], after={"reason": body.reason})
    return {"ok": True}


@route("POST", "/api/v1/users/{id}/unblock", perm="user.manage")
def unblock(ctx: Ctx):
    u = _get_user(ctx)
    dbm.update(ctx.conn, "users", {"id": u["id"]}, {"status": "active" if u["password_hash"] else "invited",
                                                   "failed_logins": 0, "locked_until": None})
    ctx.audit("user.unblocked", "user", u["id"])
    return {"ok": True}


@route("POST", "/api/v1/users/{id}/reset-mfa", perm="user.manage")
def reset_mfa(ctx: Ctx):
    u = _get_user(ctx)
    is_sa = dbm.one(ctx.conn, "SELECT 1 AS x FROM user_roles WHERE user_id = ? AND role_code = 'super_admin'", (u["id"],))
    if is_sa and not ctx.is_global("user.manage"):
        raise forbidden("Resetting a super admin's MFA needs another super admin")
    if u["id"] == ctx.actor:
        raise forbidden("Ask another administrator to reset your MFA", "SELF_MFA_RESET")
    dbm.update(ctx.conn, "users", {"id": u["id"]}, {"mfa_enabled": 0, "totp_secret_enc": None, "backup_codes": "[]"})
    ctx.conn.execute("UPDATE sessions SET revoked_at = ? WHERE user_id = ? AND revoked_at IS NULL", (now_iso(), u["id"]))
    ctx.audit("user.mfa_reset", "user", u["id"])
    return {"ok": True}


@route("POST", "/api/v1/users/{id}/resend-invite", perm="user.manage")
def resend_invite(ctx: Ctx):
    u = _get_user(ctx)
    if u["status"] != "invited":
        raise conflict("User already activated", "ALREADY_ACTIVE")
    t = token(24)
    dbm.update(ctx.conn, "users", {"id": u["id"]}, {"invite_token_hash": tokens.hash_token(t),
                                                   "invite_expires_at": iso(utcnow() + timedelta(hours=48))})
    tenant = dbm.one(ctx.conn, "SELECT slug FROM tenants WHERE id = ?", (ctx.tenant_id,))
    link = f"{ctx.settings.public_base_url}/app/invite?org={tenant['slug']}&token={t}"
    notify.enqueue(ctx.conn, ctx.tenant_id, "email", u["email"], {"subject": "FRAS taklifnomasi", "body": link})
    return {"invite_link": link}


@route("POST", "/api/v1/users/{id}/set-password", perm="user.manage")
def admin_set_password(ctx: Ctx):
    """Issue a one-time password reset link (admins never see or set the password)."""
    u = _get_user(ctx)
    t = token(24)
    dbm.update(ctx.conn, "users", {"id": u["id"]}, {"invite_token_hash": tokens.hash_token(t),
                                                   "invite_expires_at": iso(utcnow() + timedelta(hours=24))})
    tenant = dbm.one(ctx.conn, "SELECT slug FROM tenants WHERE id = ?", (ctx.tenant_id,))
    ctx.audit("user.password_reset_issued", "user", u["id"])
    return {"reset_link": f"{ctx.settings.public_base_url}/app/invite?org={tenant['slug']}&token={t}"}


# ----------------------------------------------------------------- roles (SCR-71)

@route("GET", "/api/v1/roles", perm="role.read")
def roles(ctx: Ctx):
    items = [{"code": c, "name": r["name"], "system": True, "mfa_required": r["mfa"],
              "permissions": sorted(r["permissions"]),
              "users": dbm.scalar(ctx.conn, "SELECT COUNT(DISTINCT user_id) FROM user_roles WHERE tenant_id = ? AND "
                                            "role_code = ?", (ctx.tenant_id, c))} for c, r in SYSTEM_ROLES.items()]
    for r in dbm.all_(ctx.conn, "SELECT * FROM roles WHERE tenant_id = ?", (ctx.tenant_id,)):
        items.append({"code": r["code"], "name": r["name"], "system": False, "mfa_required": False,
                      "permissions": loads(r["permissions"], []),
                      "users": dbm.scalar(ctx.conn, "SELECT COUNT(DISTINCT user_id) FROM user_roles WHERE tenant_id = ? "
                                                    "AND role_code = ?", (ctx.tenant_id, r["code"]))})
    return {"items": items, "permissions": ALL_PERMISSIONS}


@route("POST", "/api/v1/roles", perm="role.manage")
def create_role(ctx: Ctx, body: CustomRoleIn):
    if body.code in SYSTEM_ROLES:
        raise conflict("System role codes are reserved", "ROLE_RESERVED")
    bad = [p for p in body.permissions if p not in ALL_PERMISSIONS]
    if bad:
        raise unprocessable("Unknown permissions", "PERMISSION_UNKNOWN", permissions=bad)
    if "billing.manage" in body.permissions or "role.manage" in body.permissions:
        raise unprocessable("Custom roles cannot hold role or billing management", "PERMISSION_NOT_ALLOWED")
    if dbm.one(ctx.conn, "SELECT 1 AS x FROM roles WHERE tenant_id = ? AND code = ?", (ctx.tenant_id, body.code)):
        raise conflict("Role code exists", "ROLE_EXISTS")
    row = {"id": new_id(), "tenant_id": ctx.tenant_id, "code": body.code, "name": body.name,
           "permissions": dumps(sorted(set(body.permissions))), "system": 0, "created_at": now_iso()}
    dbm.insert(ctx.conn, "roles", row)
    ctx.audit("role.created", "role", row["id"], after=row)
    return 201, {**row, "permissions": loads(row["permissions"])}


@route("PUT", "/api/v1/roles/{code}", perm="role.manage")
def update_role(ctx: Ctx, body: CustomRoleIn):
    r = dbm.one(ctx.conn, "SELECT * FROM roles WHERE tenant_id = ? AND code = ?", (ctx.tenant_id, ctx.path["code"]))
    if not r:
        raise unprocessable("System roles cannot be edited; create a copy", "ROLE_SYSTEM")
    bad = [p for p in body.permissions if p not in ALL_PERMISSIONS]
    if bad:
        raise unprocessable("Unknown permissions", "PERMISSION_UNKNOWN", permissions=bad)
    affected = dbm.scalar(ctx.conn, "SELECT COUNT(DISTINCT user_id) FROM user_roles WHERE tenant_id = ? AND role_code = ?",
                          (ctx.tenant_id, r["code"]))
    dbm.update(ctx.conn, "roles", {"id": r["id"]}, {"name": body.name, "permissions": dumps(sorted(set(body.permissions)))})
    ctx.audit("role.updated", "role", r["id"], before={"permissions": loads(r["permissions"])},
              after={"permissions": body.permissions})
    return {"ok": True, "users_affected": affected}


# ----------------------------------------------------------------- sessions (SCR-72)

@route("GET", "/api/v1/security/logins", perm="user.manage")
def logins(ctx: Ctx):
    limit, offset = page_params(ctx)
    where, params = ["l.tenant_id = ?"], [ctx.tenant_id]
    if ctx.q("success") in ("0", "1"):
        where.append("l.success = ?")
        params.append(int(ctx.q("success")))
    if ctx.q("user_id"):
        where.append("l.user_id = ?")
        params.append(ctx.q("user_id"))
    total = dbm.scalar(ctx.conn, f"SELECT COUNT(*) FROM login_history l WHERE {' AND '.join(where)}", params)
    rows = dbm.all_(ctx.conn, f"SELECT l.*, u.name AS user_name FROM login_history l LEFT JOIN users u ON u.id = l.user_id "
                              f"WHERE {' AND '.join(where)} ORDER BY l.created_at DESC LIMIT ? OFFSET ?",
                    [*params, limit, offset])
    return paged(rows, total, limit, offset)


@route("GET", "/api/v1/security/sessions", perm="session.revoke")
def sessions(ctx: Ctx):
    rows = dbm.all_(ctx.conn, "SELECT s.id, s.user_id, u.name AS user_name, u.login, s.ip, s.user_agent, s.created_at, "
                              "s.expires_at, s.mfa_passed FROM sessions s JOIN users u ON u.id = s.user_id "
                              "WHERE s.tenant_id = ? AND s.revoked_at IS NULL AND s.expires_at > ? ORDER BY s.created_at DESC",
                    (ctx.tenant_id, now_iso()))
    for r in rows:
        r["current"] = r["id"] == ctx.p.session_id
    return {"items": rows}


@route("POST", "/api/v1/security/sessions/{id}/revoke", perm="session.revoke")
def revoke_session(ctx: Ctx):
    s = dbm.one(ctx.conn, "SELECT * FROM sessions WHERE id = ? AND tenant_id = ?", (ctx.path["id"], ctx.tenant_id))
    if not s:
        raise not_found("Session")
    ctx.conn.execute("UPDATE sessions SET revoked_at = ? WHERE id = ?", (now_iso(), s["id"]))
    ctx.audit("session.revoked", "session", s["id"], after={"user_id": s["user_id"]})
    return {"ok": True}


@route("GET", "/api/v1/me/sessions", mfa_exempt=True)
def my_sessions(ctx: Ctx):
    rows = dbm.all_(ctx.conn, "SELECT id, ip, user_agent, created_at, expires_at FROM sessions WHERE user_id = ? AND "
                              "revoked_at IS NULL AND expires_at > ? ORDER BY created_at DESC", (ctx.actor, now_iso()))
    for r in rows:
        r["current"] = r["id"] == ctx.p.session_id
    return {"items": rows}


@route("POST", "/api/v1/me/sessions/{id}/revoke", mfa_exempt=True)
def revoke_my_session(ctx: Ctx):
    ctx.conn.execute("UPDATE sessions SET revoked_at = ? WHERE id = ? AND user_id = ?", (now_iso(), ctx.path["id"], ctx.actor))
    return {"ok": True}

