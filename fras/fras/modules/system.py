"""Backups, restore tests, full tenant data export, system info (SCR-87, business tab 7.5)."""

from __future__ import annotations

import csv
import io
import json
import sqlite3
import tempfile
import zipfile
from pathlib import Path

from starlette.responses import Response

from .. import __version__
from .. import db as dbm
from ..errors import forbidden, not_found
from ..http import Ctx, route
from ..security import crypto
from ..util import new_id, now_iso

# Never part of a tenant export: secrets and biometric templates (they would not work elsewhere and are risky).
EXPORT_TABLES = {
    "sites": None, "buildings": None, "zones": None, "access_points": None, "departments": None, "positions": None,
    "employees": ["pinfl_enc", "pinfl_hash", "pin_hash"], "employment_assignments": None, "shift_templates": None,
    "rotations": None, "shift_assignments": None, "calendar_days": None, "leave_requests": None,
    "attendance_events": ["signature", "capture_ref"], "event_reviews": None, "corrections": None,
    "daily_summaries": None, "anomalies": None, "periods": None, "biometric_consents": None,
    "devices": ["public_key", "enc_public_key", "activation_code_hash"], "audit_logs": None,
    "users": ["password_hash", "totp_secret_enc", "backup_codes", "invite_token_hash"],
}


@route("GET", "/api/v1/system/info", perm="settings.read")
def info(ctx: Ctx):
    from ..biometrics.providers import get_provider
    p = get_provider(ctx.settings)
    return {"version": __version__, "env": ctx.settings.env, "biometric_provider": p.model_version,
            "biometric_provider_dev": p.is_dev, "server_time": now_iso(),
            "db": {"engine": "sqlite", "journal": dbm.scalar(ctx.conn, "PRAGMA journal_mode")}}


@route("POST", "/api/v1/system/full-export", perm="settings.read")
def full_export(ctx: Ctx):
    if not (ctx.can("backup.manage") or ctx.can("billing.manage")):
        raise forbidden("Super admin required")
    buf = io.BytesIO()
    counts = {}
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for table, drop in EXPORT_TABLES.items():
            rows = dbm.all_(ctx.conn, f"SELECT * FROM {table} WHERE tenant_id = ?", (ctx.tenant_id,))
            counts[table] = len(rows)
            if not rows:
                continue
            cols = [c for c in rows[0] if c not in (drop or []) and not isinstance(rows[0][c], (bytes, bytearray))]
            s = io.StringIO()
            w = csv.writer(s)
            w.writerow(cols)
            for r in rows:
                w.writerow([r[c] for c in cols])
            z.writestr(f"{table}.csv", s.getvalue().encode("utf-8-sig"))
        z.writestr("README.txt", "FRAS full data export.\nBiometric templates, password hashes and device keys are "
                                 "intentionally excluded.\nEach CSV corresponds to a table; schema in docs/ARCHITECTURE.md.\n")
        z.writestr("manifest.json", json.dumps({"tenant_id": ctx.tenant_id, "created_at": now_iso(), "counts": counts},
                                               indent=2))
    ctx.audit("system.full_export", "tenant", ctx.tenant_id, after={"counts": counts})
    return Response(buf.getvalue(), media_type="application/zip",
                    headers={"Content-Disposition": "attachment; filename=fras-full-export.zip"})


def make_backup(state, actor: str) -> dict:
    """Online SQLite backup, encrypted with the master key (AES-GCM) and checksummed."""
    folder = Path(state.settings.data_dir) / "backups"
    folder.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        tmp_path = Path(tmp.name)
    src = sqlite3.connect(state.settings.db_path)
    dst = sqlite3.connect(tmp_path)
    src.backup(dst)
    dst.close()
    src.close()
    raw = tmp_path.read_bytes()
    tmp_path.unlink()
    sealed = crypto.seal(state.settings.master_key, raw, aad=b"backup")
    backup_id = new_id()
    path = folder / f"{backup_id}.db.enc"
    path.write_bytes(sealed)
    row = {"id": backup_id, "path": str(path), "size_bytes": len(sealed), "sha256": crypto.sha256_hex(sealed),
           "kind": "backup", "status": "ok", "created_by": actor, "created_at": now_iso()}
    return row


@route("GET", "/api/v1/system/backups", perm="backup.manage")
def backups(ctx: Ctx):
    return {"items": dbm.all_(ctx.conn, "SELECT id, size_bytes, sha256, kind, status, created_by, created_at FROM backups "
                                        "ORDER BY created_at DESC LIMIT 100"),
            "policy": {"schedule": "daily 02:00 + WAL", "encryption": "AES-256-GCM (master key)",
                       "restore_test": "quarterly, into an isolated copy — never over production"}}


@route("POST", "/api/v1/system/backups", perm="backup.manage")
def backup_now(ctx: Ctx):
    if not ctx.is_global("backup.manage"):
        raise forbidden()
    row = make_backup(ctx.state, ctx.actor)
    dbm.insert(ctx.conn, "backups", row)
    ctx.audit("system.backup_created", "backup", row["id"], after={"size": row["size_bytes"]}, tenant_id=ctx.tenant_id)
    return 201, {k: v for k, v in row.items() if k != "path"}


@route("POST", "/api/v1/system/backups/{id}/restore-test", perm="backup.manage")
def restore_test(ctx: Ctx):
    """Decrypts the backup into a temporary file and runs integrity checks. Never touches production."""
    b = dbm.one(ctx.conn, "SELECT * FROM backups WHERE id = ?", (ctx.path["id"],))
    if not b:
        raise not_found("Backup")
    data = Path(b["path"]).read_bytes()
    checksum_ok = crypto.sha256_hex(data) == b["sha256"]
    raw = crypto.open_sealed(ctx.settings.master_key, data, aad=b"backup")
    with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
        tmp.write(raw)
        tmp.flush()
        c = sqlite3.connect(tmp.name)
        integrity = c.execute("PRAGMA integrity_check").fetchone()[0]
        events = c.execute("SELECT COUNT(*) FROM attendance_events").fetchone()[0]
        tenants = c.execute("SELECT COUNT(*) FROM tenants").fetchone()[0]
        c.close()
    ok = checksum_ok and integrity == "ok"
    row = {"id": new_id(), "path": b["path"], "size_bytes": b["size_bytes"], "sha256": b["sha256"], "kind": "restore_test",
           "status": "ok" if ok else "failed", "created_by": ctx.actor, "created_at": now_iso()}
    dbm.insert(ctx.conn, "backups", row)
    ctx.audit("system.restore_tested", "backup", b["id"], after={"ok": ok, "integrity": integrity})
    return {"ok": ok, "checksum_ok": checksum_ok, "integrity": integrity, "events": events, "tenants": tenants}
