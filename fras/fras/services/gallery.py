"""Gallery versioning: any change to who may pass where bumps the tenant gallery
version; devices notice the new version on their next heartbeat and pull a
fresh package (target: on every online terminal within 5 minutes)."""

from __future__ import annotations

from .. import db as dbm
from ..util import now_iso


def bump(conn, tenant_id: str) -> int:
    conn.execute("UPDATE gallery_versions SET version = version + 1, updated_at = ? WHERE tenant_id = ?",
                 (now_iso(), tenant_id))
    return dbm.scalar(conn, "SELECT version FROM gallery_versions WHERE tenant_id = ?", (tenant_id,))


def current(conn, tenant_id: str) -> int:
    return dbm.scalar(conn, "SELECT version FROM gallery_versions WHERE tenant_id = ?", (tenant_id,)) or 0
