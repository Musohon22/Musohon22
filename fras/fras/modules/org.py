"""Organisation structure: sites, buildings, zones, access points, departments, positions (SCR-80)."""

from __future__ import annotations

from pydantic import BaseModel, Field

from .. import db as dbm
from ..errors import conflict, not_found, unprocessable
from ..http import Ctx, route
from ..services import tenancy
from ..util import new_id, now_iso

TZ_PATTERN = r"^[A-Za-z_]+/[A-Za-z_\-]+(/[A-Za-z_\-]+)?$"


class SiteIn(BaseModel):
    code: str = Field(min_length=1, max_length=20, pattern=r"^[A-Za-z0-9_\-]+$")
    name: str = Field(min_length=2, max_length=120)
    timezone: str = Field(default="Asia/Tashkent", pattern=TZ_PATTERN)
    address: str | None = Field(default=None, max_length=300)


class BuildingIn(BaseModel):
    site_id: str
    name: str = Field(min_length=1, max_length=120)


class ZoneIn(BaseModel):
    building_id: str
    name: str = Field(min_length=1, max_length=120)


class AccessPointIn(BaseModel):
    site_id: str
    zone_id: str | None = None
    name: str = Field(min_length=1, max_length=120)
    direction: str = Field(default="both", pattern="^(in|out|both)$")


class DepartmentIn(BaseModel):
    site_id: str
    parent_id: str | None = None
    code: str = Field(min_length=1, max_length=20)
    name: str = Field(min_length=2, max_length=120)


class PositionIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)


class RenameIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    timezone: str | None = Field(default=None, pattern=TZ_PATTERN)
    direction: str | None = Field(default=None, pattern="^(in|out|both)$")


def _get(ctx: Ctx, table: str, obj_id: str) -> dict:
    row = dbm.one(ctx.conn, f"SELECT * FROM {table} WHERE id = ? AND tenant_id = ?", (obj_id, ctx.tenant_id))
    if not row:
        raise not_found(table[:-1].capitalize())
    return row


def _validate_tz(name: str) -> None:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        raise unprocessable("Unknown time zone", "TIMEZONE_INVALID", field="timezone")


@route("GET", "/api/v1/org/tree", perm="org.read")
def tree(ctx: Ctx):
    t = ctx.tenant_id
    allowed = ctx.site_ids("org.read")
    sites = [s for s in dbm.all_(ctx.conn, "SELECT * FROM sites WHERE tenant_id = ? ORDER BY name", (t,))
             if allowed is None or s["id"] in allowed]
    buildings = dbm.all_(ctx.conn, "SELECT * FROM buildings WHERE tenant_id = ? ORDER BY name", (t,))
    zones = dbm.all_(ctx.conn, "SELECT * FROM zones WHERE tenant_id = ? ORDER BY name", (t,))
    aps = dbm.all_(ctx.conn, "SELECT * FROM access_points WHERE tenant_id = ? ORDER BY name", (t,))
    depts = dbm.all_(ctx.conn, "SELECT d.*, (SELECT COUNT(*) FROM employees e WHERE e.department_id = d.id "
                               "AND e.status = 'active') AS employees FROM departments d WHERE d.tenant_id = ? "
                               "ORDER BY d.name", (t,))
    positions = dbm.all_(ctx.conn, "SELECT * FROM positions WHERE tenant_id = ? ORDER BY name", (t,))
    for s in sites:
        s["buildings"] = [b for b in buildings if b["site_id"] == s["id"]]
        for b in s["buildings"]:
            b["zones"] = [z for z in zones if z["building_id"] == b["id"]]
        s["access_points"] = [a for a in aps if a["site_id"] == s["id"]]
        s["departments"] = [d for d in depts if d["site_id"] == s["id"]]
    return {"sites": sites, "positions": positions}


@route("POST", "/api/v1/org/sites", perm="org.manage", billing="grow")
def create_site(ctx: Ctx, body: SiteIn):
    if not ctx.is_global("org.manage"):
        raise unprocessable("Only organisation-wide admins can add sites", "SCOPE_TOO_NARROW")
    _validate_tz(body.timezone)
    tenancy.check_limit(ctx.conn, ctx.tenant_id, "sites")
    if dbm.one(ctx.conn, "SELECT 1 AS x FROM sites WHERE tenant_id = ? AND code = ?", (ctx.tenant_id, body.code)):
        raise conflict("Site code already exists", "SITE_CODE_TAKEN")
    row = {"id": new_id(), "tenant_id": ctx.tenant_id, **body.model_dump(), "status": "active", "created_at": now_iso()}
    dbm.insert(ctx.conn, "sites", row)
    ctx.audit("org.site_created", "site", row["id"], after=row)
    return 201, row


@route("PATCH", "/api/v1/org/sites/{id}", perm="org.manage")
def update_site(ctx: Ctx, body: RenameIn):
    site = _get(ctx, "sites", ctx.path["id"])
    ctx.require_site("org.manage", site["id"])
    changes = {"name": body.name}
    if body.timezone and body.timezone != site["timezone"]:
        _validate_tz(body.timezone)
        changes["timezone"] = body.timezone
    dbm.update(ctx.conn, "sites", {"id": site["id"]}, changes)
    ctx.audit("org.site_updated", "site", site["id"], before=site, after=changes)
    return {**site, **changes}


@route("POST", "/api/v1/org/buildings", perm="org.manage")
def create_building(ctx: Ctx, body: BuildingIn):
    site = _get(ctx, "sites", body.site_id)
    ctx.require_site("org.manage", site["id"])
    row = {"id": new_id(), "tenant_id": ctx.tenant_id, "site_id": site["id"], "name": body.name, "status": "active",
           "created_at": now_iso()}
    dbm.insert(ctx.conn, "buildings", row)
    ctx.audit("org.building_created", "building", row["id"], after=row)
    return 201, row


@route("POST", "/api/v1/org/zones", perm="org.manage")
def create_zone(ctx: Ctx, body: ZoneIn):
    b = _get(ctx, "buildings", body.building_id)
    ctx.require_site("org.manage", b["site_id"])
    row = {"id": new_id(), "tenant_id": ctx.tenant_id, "building_id": b["id"], "name": body.name, "status": "active",
           "created_at": now_iso()}
    dbm.insert(ctx.conn, "zones", row)
    ctx.audit("org.zone_created", "zone", row["id"], after=row)
    return 201, row


@route("POST", "/api/v1/org/access-points", perm="org.manage")
def create_access_point(ctx: Ctx, body: AccessPointIn):
    site = _get(ctx, "sites", body.site_id)
    ctx.require_site("org.manage", site["id"])
    if body.zone_id:
        _get(ctx, "zones", body.zone_id)
    row = {"id": new_id(), "tenant_id": ctx.tenant_id, **body.model_dump(), "status": "active", "created_at": now_iso()}
    dbm.insert(ctx.conn, "access_points", row)
    ctx.audit("org.access_point_created", "access_point", row["id"], after=row)
    return 201, row


@route("PATCH", "/api/v1/org/access-points/{id}", perm="org.manage")
def update_access_point(ctx: Ctx, body: RenameIn):
    ap = _get(ctx, "access_points", ctx.path["id"])
    ctx.require_site("org.manage", ap["site_id"])
    changes = {"name": body.name}
    if body.direction:
        changes["direction"] = body.direction
    dbm.update(ctx.conn, "access_points", {"id": ap["id"]}, changes)
    ctx.audit("org.access_point_updated", "access_point", ap["id"], before=ap, after=changes)
    return {**ap, **changes}


@route("POST", "/api/v1/org/departments", perm="org.manage")
def create_department(ctx: Ctx, body: DepartmentIn):
    site = _get(ctx, "sites", body.site_id)
    ctx.require_site("org.manage", site["id"])
    if body.parent_id:
        parent = _get(ctx, "departments", body.parent_id)
        if parent["site_id"] != site["id"]:
            raise unprocessable("Parent department belongs to another site", "PARENT_SITE_MISMATCH")
    if dbm.one(ctx.conn, "SELECT 1 AS x FROM departments WHERE tenant_id = ? AND site_id = ? AND code = ?",
               (ctx.tenant_id, site["id"], body.code)):
        raise conflict("Department code already exists on this site", "DEPARTMENT_CODE_TAKEN")
    row = {"id": new_id(), "tenant_id": ctx.tenant_id, **body.model_dump(), "status": "active", "created_at": now_iso()}
    dbm.insert(ctx.conn, "departments", row)
    ctx.audit("org.department_created", "department", row["id"], after=row)
    return 201, row


@route("PATCH", "/api/v1/org/departments/{id}", perm="org.manage")
def update_department(ctx: Ctx, body: RenameIn):
    d = _get(ctx, "departments", ctx.path["id"])
    ctx.require_site("org.manage", d["site_id"])
    dbm.update(ctx.conn, "departments", {"id": d["id"]}, {"name": body.name})
    ctx.audit("org.department_updated", "department", d["id"], before=d, after={"name": body.name})
    return {**d, "name": body.name}


@route("POST", "/api/v1/org/departments/{id}/archive", perm="org.manage")
def archive_department(ctx: Ctx):
    d = _get(ctx, "departments", ctx.path["id"])
    ctx.require_site("org.manage", d["site_id"])
    active = dbm.scalar(ctx.conn, "SELECT COUNT(*) FROM employees WHERE department_id = ? AND status = 'active'", (d["id"],))
    if active:
        raise conflict(f"Department has {active} active employees; move them first", "DEPARTMENT_NOT_EMPTY",
                       employees=active)
    dbm.update(ctx.conn, "departments", {"id": d["id"]}, {"status": "archived"})
    ctx.audit("org.department_archived", "department", d["id"])
    return {"ok": True}


@route("POST", "/api/v1/org/positions", perm="org.manage")
def create_position(ctx: Ctx, body: PositionIn):
    if dbm.one(ctx.conn, "SELECT 1 AS x FROM positions WHERE tenant_id = ? AND name = ?", (ctx.tenant_id, body.name)):
        raise conflict("Position already exists", "POSITION_TAKEN")
    row = {"id": new_id(), "tenant_id": ctx.tenant_id, "name": body.name, "created_at": now_iso()}
    dbm.insert(ctx.conn, "positions", row)
    ctx.audit("org.position_created", "position", row["id"], after=row)
    return 201, row
