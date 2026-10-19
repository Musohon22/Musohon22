"""Thin request framework on top of Starlette.

Handlers are plain synchronous functions registered with `@route`. The wrapper
does, in order: request id → rate limit → authentication (user / platform /
device / API key) → MFA enforcement → permission check → subscription gate →
body validation (pydantic) → idempotency → one DB transaction → JSON response.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

import jwt
from pydantic import BaseModel, ValidationError
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from . import db as dbm
from .errors import ApiError, forbidden, too_many, unauthorized, unprocessable, payment_required
from .ratelimit import POLICIES, limiter
from .security import audit as auditlog
from .security import crypto, tokens
from .security.permissions import SYSTEM_ROLES, platform_can
from .util import dumps, loads, now_iso, parse_dt, utcnow


@dataclass
class RouteSpec:
    method: str
    path: str
    handler: Callable
    perm: str | None
    auth: str              # user | platform | device | api | public | user_or_api
    rate: str
    body_model: type[BaseModel] | None
    mfa_exempt: bool
    billing: str | None    # None | "grow" | "write"
    form: bool


ROUTES: list[RouteSpec] = []


def route(method: str, path: str, *, perm: str | None = None, auth: str = "user", rate: str | None = None,
          mfa_exempt: bool = False, billing: str | None = None, form: bool = False):
    def deco(fn: Callable):
        sig = inspect.signature(fn)
        body_model = None
        if "body" in sig.parameters:
            ann = sig.parameters["body"].annotation
            if isinstance(ann, str):
                ann = fn.__globals__.get(ann)
            if inspect.isclass(ann) and issubclass(ann, BaseModel):
                body_model = ann
        default_rate = "read" if method == "GET" else "write"
        ROUTES.append(RouteSpec(method, path, fn, perm, auth, rate or default_rate, body_model,
                                mfa_exempt, billing, form))
        return fn
    return deco


# ----------------------------------------------------------------- principal & context

@dataclass
class Principal:
    kind: str                         # user | platform | device | api | public
    id: str | None = None
    tenant_id: str | None = None
    name: str = ""
    perms: dict[str, list[tuple[str, str | None]]] = field(default_factory=dict)
    roles: list[dict] = field(default_factory=list)
    session_id: str | None = None
    employee_id: str | None = None
    platform_role: str | None = None
    device: dict | None = None
    mfa_required: bool = False
    mfa_enabled: bool = False


_dek_cache: dict[str, bytes] = {}
_sub_cache: dict[str, tuple[float, str]] = {}


class Ctx:
    def __init__(self, state, conn: sqlite3.Connection, principal: Principal, info: dict,
                 path_params: dict, query: dict, headers: dict):
        self.state = state
        self.settings = state.settings
        self.conn = conn
        self.p = principal
        self.info = info
        self.path = path_params
        self.query = query
        self.headers = headers
        self._after: list[Callable[[], None]] = []
        self.response_headers: dict[str, str] = {}
        self.cookies: list[dict] = []
        self.cookies_in: dict[str, str] = {}
        # Set by handlers whose bookkeeping must survive an error response
        # (failed-login counters, security alerts).
        self.keep_on_error = False

    # -- tenant
    @property
    def tenant_id(self) -> str:
        if not self.p.tenant_id:
            raise forbidden("Tenant context required")
        return self.p.tenant_id

    @property
    def actor(self) -> str | None:
        return self.p.id

    # -- permissions
    def can(self, perm: str) -> bool:
        if self.p.kind == "platform":
            return platform_can(self.p.platform_role or "", perm)
        return perm in self.p.perms

    def require(self, perm: str) -> None:
        if not self.can(perm):
            raise forbidden("You do not have permission for this action", permission=perm)

    def scopes(self, perm: str) -> list[tuple[str, str | None]]:
        return self.p.perms.get(perm, [])

    def is_global(self, perm: str) -> bool:
        return any(s[0] == "global" for s in self.scopes(perm))

    def _dept_tree(self) -> dict[str, list[str]]:
        rows = dbm.all_(self.conn, "SELECT id, parent_id FROM departments WHERE tenant_id = ?", (self.tenant_id,))
        children: dict[str, list[str]] = {}
        for r in rows:
            if r["parent_id"]:
                children.setdefault(r["parent_id"], []).append(r["id"])
        return children

    def _dept_with_descendants(self, dept_id: str, tree: dict[str, list[str]]) -> list[str]:
        out, stack = [], [dept_id]
        while stack:
            d = stack.pop()
            out.append(d)
            stack.extend(tree.get(d, []))
        return out

    def employee_filter(self, perm: str, alias: str = "e") -> tuple[str, list]:
        """SQL fragment restricting an employees alias to the caller's scope for `perm`."""
        if self.p.kind in ("platform",):
            return "1=1", []
        scopes = self.scopes(perm)
        if not scopes:
            return "1=0", []
        if any(s[0] == "global" for s in scopes):
            return "1=1", []
        parts, params = [], []
        tree = None
        for kind, sid in scopes:
            if kind == "site":
                parts.append(f"{alias}.site_id = ?")
                params.append(sid)
            elif kind == "department":
                tree = tree or self._dept_tree()
                ids = self._dept_with_descendants(sid, tree)
                parts.append(f"{alias}.department_id IN ({','.join('?' * len(ids))})")
                params.extend(ids)
            elif kind == "team":
                dept, _, team = (sid or "").partition(":")
                parts.append(f"({alias}.department_id = ? AND {alias}.team = ?)")
                params.extend([dept, team])
            elif kind == "self":
                parts.append(f"{alias}.id = ?")
                params.append(self.p.employee_id or "-")
        return "(" + " OR ".join(parts) + ")", params

    def can_employee(self, perm: str, employee: dict) -> bool:
        if not self.can(perm):
            return False
        sql, params = self.employee_filter(perm, "e")
        return dbm.one(self.conn, f"SELECT 1 AS ok FROM employees e WHERE e.id = ? AND e.tenant_id = ? AND {sql}",
                       [employee["id"], self.tenant_id, *params]) is not None

    def require_employee(self, perm: str, employee: dict) -> None:
        if not self.can_employee(perm, employee):
            raise forbidden("This employee is outside your scope", permission=perm)

    def site_ids(self, perm: str) -> set[str] | None:
        """Sites the caller may see for `perm`; None means all sites."""
        scopes = self.scopes(perm)
        if any(s[0] == "global" for s in scopes):
            return None
        sites: set[str] = set()
        for kind, sid in scopes:
            if kind == "site":
                sites.add(sid)
            elif kind in ("department", "team"):
                dept = (sid or "").split(":")[0]
                row = dbm.one(self.conn, "SELECT site_id FROM departments WHERE id = ?", (dept,))
                if row:
                    sites.add(row["site_id"])
            elif kind == "self" and self.p.employee_id:
                row = dbm.one(self.conn, "SELECT site_id FROM employees WHERE id = ?", (self.p.employee_id,))
                if row:
                    sites.add(row["site_id"])
        return sites

    def require_site(self, perm: str, site_id: str) -> None:
        self.require(perm)
        allowed = self.site_ids(perm)
        if allowed is not None and site_id not in allowed:
            raise forbidden("This site is outside your scope", permission=perm)

    # -- crypto
    def dek(self, tenant_id: str | None = None) -> bytes:
        tid = tenant_id or self.tenant_id
        if tid not in _dek_cache:
            row = dbm.one(self.conn, "SELECT dek_wrapped FROM tenants WHERE id = ?", (tid,))
            _dek_cache[tid] = crypto.unwrap_dek(self.settings.master_key, row["dek_wrapped"], tid)
        return _dek_cache[tid]

    # -- audit
    def audit(self, action: str, object_type: str | None = None, object_id: str | None = None,
              before: dict | None = None, after: dict | None = None, result: str = "success",
              tenant_id: str | None = "__ctx__") -> None:
        tid = self.p.tenant_id if tenant_id == "__ctx__" else tenant_id
        actor_type = {"user": "user", "platform": "platform_user", "device": "device", "api": "api_key"}.get(
            self.p.kind, "system")
        auditlog.write(self.conn, tenant_id=tid, actor_type=actor_type, actor_id=self.p.id, action=action,
                       object_type=object_type, object_id=object_id, before=before, after=after,
                       ip=self.info.get("ip"), request_id=self.info.get("request_id"), result=result)

    def after_commit(self, fn: Callable[[], None]) -> None:
        self._after.append(fn)

    # -- query helpers
    def q(self, name: str, default=None, cast=str):
        v = self.query.get(name)
        if v in (None, ""):
            return default
        try:
            return cast(v)
        except (TypeError, ValueError):
            raise unprocessable(f"Invalid query parameter '{name}'", field=name)

    def qlist(self, name: str) -> list[str]:
        v = self.query.get(name)
        return [x for x in v.split(",") if x] if v else []


def page_params(ctx: Ctx, max_limit: int = 200) -> tuple[int, int]:
    limit = min(max(ctx.q("limit", 50, int), 1), max_limit)
    offset = max(ctx.q("offset", 0, int), 0)
    return limit, offset


def paged(rows: list[dict], total: int, limit: int, offset: int) -> dict:
    return {"items": rows, "total": total, "limit": limit, "offset": offset}


# ----------------------------------------------------------------- authentication

def load_user_principal(conn: sqlite3.Connection, user: dict, session_id: str | None) -> Principal:
    roles = dbm.all_(conn, "SELECT * FROM user_roles WHERE user_id = ? AND (valid_until IS NULL OR valid_until > ?)",
                     (user["id"], now_iso()))
    custom = {r["code"]: loads(r["permissions"], []) for r in dbm.all_(
        conn, "SELECT code, permissions FROM roles WHERE tenant_id = ?", (user["tenant_id"],))}
    perms: dict[str, list] = {}
    mfa_required = False
    for ur in roles:
        code = ur["role_code"]
        if code in SYSTEM_ROLES:
            granted = SYSTEM_ROLES[code]["permissions"]
            mfa_required = mfa_required or SYSTEM_ROLES[code]["mfa"]
        else:
            granted = set(custom.get(code, []))
        scope = (ur["scope_type"], ur["scope_id"])
        for perm in granted:
            perms.setdefault(perm, [])
            if scope not in perms[perm]:
                perms[perm].append(scope)
    if user.get("employee_id"):
        for perm in ("self.read", "self.request"):
            perms.setdefault(perm, [])
            if ("self", user["employee_id"]) not in perms[perm]:
                perms[perm].append(("self", user["employee_id"]))
    return Principal(kind="user", id=user["id"], tenant_id=user["tenant_id"], name=user["name"], perms=perms,
                     roles=roles, session_id=session_id, employee_id=user.get("employee_id"),
                     mfa_required=mfa_required, mfa_enabled=bool(user["mfa_enabled"]))


def _auth_bearer(state, conn, header: str, realm_expected: str) -> Principal:
    token = header.split(" ", 1)[1].strip() if " " in header else ""
    try:
        claims = tokens.decode_access(state.settings.secret_key, token)
    except jwt.ExpiredSignatureError:
        raise unauthorized("Session expired", "TOKEN_EXPIRED")
    except jwt.PyJWTError:
        raise unauthorized("Invalid token", "TOKEN_INVALID")
    if claims.get("realm") != realm_expected:
        raise unauthorized("Wrong token realm", "TOKEN_REALM")
    sess = dbm.one(conn, "SELECT * FROM sessions WHERE id = ?", (claims["sid"],))
    if not sess or sess["revoked_at"] or parse_dt(sess["expires_at"]) < utcnow():
        raise unauthorized("Session revoked", "SESSION_REVOKED")
    if realm_expected == "platform":
        user = dbm.one(conn, "SELECT * FROM platform_users WHERE id = ?", (claims["sub"],))
        if not user or user["status"] != "active":
            raise unauthorized("Account disabled", "ACCOUNT_DISABLED")
        return Principal(kind="platform", id=user["id"], name=user["name"], platform_role=user["role"],
                         session_id=sess["id"], mfa_enabled=bool(user["mfa_enabled"]))
    user = dbm.one(conn, "SELECT * FROM users WHERE id = ?", (claims["sub"],))
    if not user or user["status"] != "active":
        raise unauthorized("Account disabled", "ACCOUNT_DISABLED")
    return load_user_principal(conn, user, sess["id"])


def _auth_device(state, conn, request_meta: dict, body: bytes) -> Principal:
    h = request_meta["headers"]
    device_id, ts, sig = h.get("x-device-id"), h.get("x-device-ts"), h.get("x-device-sig")
    if not (device_id and ts and sig):
        raise unauthorized("Device signature required", "DEVICE_AUTH_REQUIRED")
    try:
        skew = abs(time.time() - int(ts))
    except ValueError:
        raise unauthorized("Bad timestamp", "DEVICE_AUTH_INVALID")
    if skew > 300:
        raise unauthorized("Request timestamp outside allowed window (replay protection)", "DEVICE_REPLAY")
    dev = dbm.one(conn, "SELECT * FROM devices WHERE id = ?", (device_id,))
    if not dev or not dev["public_key"] or dev["status"] == "decommissioned":
        raise unauthorized("Unknown or decommissioned device", "DEVICE_UNKNOWN")
    message = device_message(request_meta["method"], request_meta["path"], ts, body)
    if not crypto.verify(dev["public_key"], message, sig):
        raise unauthorized("Invalid device signature", "DEVICE_AUTH_INVALID")
    return Principal(kind="device", id=dev["id"], tenant_id=dev["tenant_id"], name=dev["name"], device=dev)


def device_message(method: str, path: str, ts: str, body: bytes) -> bytes:
    return f"{method}\n{path}\n{ts}\n{hashlib.sha256(body).hexdigest()}".encode()


def _auth_api_key(state, conn, key: str, ip: str) -> Principal:
    parts = key.split("_")
    if len(parts) != 3 or parts[0] != "fras":
        raise unauthorized("Invalid API key", "API_KEY_INVALID")
    row = dbm.one(conn, "SELECT * FROM api_keys WHERE prefix = ?", (parts[1],))
    if not row or row["revoked_at"] or (row["expires_at"] and parse_dt(row["expires_at"]) < utcnow()):
        raise unauthorized("Invalid API key", "API_KEY_INVALID")
    if tokens.hash_token(key) != row["key_hash"]:
        raise unauthorized("Invalid API key", "API_KEY_INVALID")
    allow = loads(row["ip_allowlist"], [])
    if allow and ip not in allow:
        raise forbidden("IP not allowed for this API key", "API_KEY_IP")
    conn.execute("UPDATE api_keys SET last_used_at = ? WHERE id = ?", (now_iso(), row["id"]))
    perms = {p: [("global", None)] for p in loads(row["scopes"], [])}
    return Principal(kind="api", id=row["id"], tenant_id=row["tenant_id"], name=row["name"], perms=perms)


def subscription_status(conn, tenant_id: str) -> str:
    cached = _sub_cache.get(tenant_id)
    if cached and cached[0] > time.monotonic():
        return cached[1]
    row = dbm.one(conn, "SELECT status FROM subscriptions WHERE tenant_id = ? ORDER BY created_at DESC LIMIT 1",
                  (tenant_id,))
    status = row["status"] if row else "active"
    _sub_cache[tenant_id] = (time.monotonic() + 15, status)
    return status


def invalidate_subscription_cache(tenant_id: str) -> None:
    _sub_cache.pop(tenant_id, None)


# ----------------------------------------------------------------- endpoint wrapper

def _error_response(err: ApiError, request_id: str) -> JSONResponse:
    headers = {"X-Request-Id": request_id}
    if err.status == 429 and "retry_after" in err.details:
        headers["Retry-After"] = str(err.details["retry_after"])
    return JSONResponse({"error": {"code": err.code, "message": err.message, "details": err.details,
                                   "request_id": request_id}}, status_code=err.status, headers=headers)


def make_endpoint(spec: RouteSpec, state):
    async def endpoint(request: Request):
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
        ip = request.client.host if request.client else "-"
        try:
            body_bytes = b""
            form_data = None
            if spec.form:
                form = await request.form()
                form_data = {"fields": {}, "files": {}}
                for k, v in form.multi_items():
                    if hasattr(v, "filename"):
                        form_data["files"][k] = (v.filename, await v.read())
                    else:
                        form_data["fields"][k] = v
            elif request.method in ("POST", "PUT", "PATCH", "DELETE"):
                body_bytes = await request.body()
            meta = {"method": request.method, "path": request.url.path, "headers": dict(request.headers),
                    "ip": ip, "request_id": request_id, "user_agent": request.headers.get("user-agent", "")}
            result = await run_in_threadpool(
                _run, spec, state, meta, body_bytes, form_data, dict(request.path_params),
                dict(request.query_params), request.cookies)
            return result
        except ApiError as err:
            return _error_response(err, request_id)

    endpoint.__name__ = spec.handler.__name__
    return endpoint


def _run(spec: RouteSpec, state, meta: dict, body_bytes: bytes, form_data, path_params: dict, query: dict,
         cookies: dict):
    request_id = meta["request_id"]
    headers = meta["headers"]
    conn = state.db.connect()
    try:
        # ---- authentication (read-only lookups before the write transaction)
        principal = Principal(kind="public")
        auth_header = headers.get("authorization", "")
        api_key = headers.get("x-api-key")
        if spec.auth == "device":
            principal = _auth_device(state, conn, meta, body_bytes)
        elif spec.auth in ("user", "user_or_api"):
            if auth_header.lower().startswith("bearer "):
                principal = _auth_bearer(state, conn, auth_header, "tenant")
            elif api_key and spec.auth == "user_or_api":
                principal = _auth_api_key(state, conn, api_key, meta["ip"])
            else:
                raise unauthorized()
        elif spec.auth == "platform":
            if not auth_header.lower().startswith("bearer "):
                raise unauthorized()
            principal = _auth_bearer(state, conn, auth_header, "platform")
        elif spec.auth == "optional" and auth_header.lower().startswith("bearer "):
            try:
                principal = _auth_bearer(state, conn, auth_header, "tenant")
            except ApiError:
                principal = Principal(kind="public")

        # ---- rate limiting
        rate_key = f"{spec.rate}:{principal.id or meta['ip']}"
        cap, refill = POLICIES[spec.rate]
        wait = limiter.hit(rate_key, cap, refill)
        if wait:
            raise too_many(wait)

        # ---- MFA: privileged roles must enrol before using the API
        if (principal.kind == "user" and principal.mfa_required and not principal.mfa_enabled and not spec.mfa_exempt
                and not state.settings.relax_mfa):
            raise forbidden("Multi-factor authentication must be enabled for your role", "MFA_SETUP_REQUIRED")

        ctx = Ctx(state, conn, principal, meta, path_params, query, headers)
        ctx.cookies_in = cookies
        if spec.perm:
            ctx.require(spec.perm)

        # ---- subscription gate (never applied to device traffic)
        if spec.billing and principal.tenant_id and principal.kind in ("user", "api"):
            status = subscription_status(conn, principal.tenant_id)
            if spec.billing == "grow" and status in ("restricted", "suspended", "cancelled", "archived"):
                raise payment_required("Subscription is restricted: adding new employees, devices or integrations is "
                                       "paused until payment. Attendance keeps working.")
            if spec.billing == "write" and status in ("suspended", "cancelled", "archived"):
                raise payment_required("Subscription is suspended: the admin panel is read-only. Terminals, events "
                                       "and data export keep working.", "SUBSCRIPTION_SUSPENDED")

        # ---- body
        kwargs: dict[str, Any] = {}
        if spec.body_model is not None:
            try:
                raw = json.loads(body_bytes or b"{}")
            except json.JSONDecodeError:
                raise unprocessable("Body must be valid JSON", "INVALID_JSON")
            try:
                kwargs["body"] = spec.body_model.model_validate(raw)
            except ValidationError as e:
                fields = [{"field": ".".join(str(x) for x in err["loc"]), "message": err["msg"], "type": err["type"]}
                          for err in e.errors()]
                raise unprocessable("Validation failed", "VALIDATION_ERROR", fields=fields)
        elif spec.auth == "device":
            kwargs["raw"] = body_bytes
        if form_data is not None:
            kwargs["form"] = form_data

        # ---- idempotency
        idem_key = headers.get("idempotency-key")
        idem_scope = principal.tenant_id or principal.id or "public"
        req_hash = hashlib.sha256(meta["method"].encode() + meta["path"].encode() + body_bytes).hexdigest()
        if idem_key and meta["method"] in ("POST", "PUT", "PATCH"):
            prior = dbm.one(conn, "SELECT * FROM idempotency_keys WHERE scope = ? AND key = ?", (idem_scope, idem_key))
            if prior:
                if prior["request_hash"] != req_hash:
                    raise unprocessable("Idempotency-Key was already used with a different request",
                                        "IDEMPOTENCY_KEY_REUSED")
                return JSONResponse(json.loads(prior["response"]), status_code=prior["status_code"],
                                    headers={"X-Request-Id": request_id, "Idempotent-Replay": "true"})

        # ---- transaction
        write = meta["method"] != "GET"
        conn.execute("BEGIN IMMEDIATE" if write else "BEGIN")
        try:
            out = spec.handler(ctx, **kwargs)
            status = 200
            if isinstance(out, tuple):
                status, out = out
            if isinstance(out, Response):
                response = out
            else:
                payload = json.loads(dumps(out if out is not None else {"ok": True}))
                response = JSONResponse(payload, status_code=status)
                if idem_key and write and 200 <= status < 300:
                    conn.execute("INSERT OR REPLACE INTO idempotency_keys VALUES (?,?,?,?,?,?,?,?)",
                                 (idem_scope, idem_key, meta["method"], meta["path"], req_hash, status,
                                  dumps(payload), now_iso()))
            conn.execute("COMMIT")
        except ApiError:
            if conn.in_transaction:
                conn.execute("COMMIT" if ctx.keep_on_error else "ROLLBACK")
            raise
        except BaseException:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        for fn in ctx._after:
            try:
                fn()
            except Exception:  # noqa: BLE001 - post-commit side effects must not fail the request
                pass
        response.headers["X-Request-Id"] = request_id
        for k, v in ctx.response_headers.items():
            response.headers[k] = v
        for c in ctx.cookies:
            response.set_cookie(**c)
        return response
    except sqlite3.IntegrityError as e:
        msg = str(e)
        if "append-only" in msg:
            raise ApiError(409, "IMMUTABLE_RECORD", "This record cannot be modified")
        raise ApiError(409, "CONSTRAINT_VIOLATION", "The change conflicts with existing data", {"detail": msg})
    finally:
        state.db.release(conn)
