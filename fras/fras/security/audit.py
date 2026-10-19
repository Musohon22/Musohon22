"""Hash-chained, append-only audit log.

Each record stores the hash of the previous record of the same tenant, so any
edit or deletion made directly in the database breaks the chain and is found
by `verify_chain`. Database triggers additionally forbid UPDATE/DELETE.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3

from ..util import new_id, now_iso

GENESIS = "0" * 64

SENSITIVE_KEYS = {"pinfl", "pinfl_enc", "password", "password_hash", "pin", "pin_hash",
                  "totp_secret", "totp_secret_enc", "template_enc", "secret", "key_hash"}


def _mask(value):
    if isinstance(value, dict):
        return {k: ("***" if k in SENSITIVE_KEYS else _mask(v)) for k, v in value.items()
                if not isinstance(v, (bytes, bytearray))}
    if isinstance(value, list):
        return [_mask(v) for v in value]
    return value


def _digest(prev_hash: str, record: dict) -> str:
    canonical = json.dumps(record, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256((prev_hash + canonical).encode()).hexdigest()


CHAIN_FIELDS = ("id", "tenant_id", "actor_type", "actor_id", "action", "object_type", "object_id",
                "before_json", "after_json", "result", "created_at")


def write(conn: sqlite3.Connection, *, tenant_id: str | None, actor_type: str, actor_id: str | None,
          action: str, object_type: str | None = None, object_id: str | None = None,
          before: dict | None = None, after: dict | None = None, ip: str | None = None,
          request_id: str | None = None, result: str = "success") -> str:
    if tenant_id is None:
        row = conn.execute("SELECT hash FROM audit_logs WHERE tenant_id IS NULL ORDER BY seq DESC LIMIT 1").fetchone()
    else:
        row = conn.execute("SELECT hash FROM audit_logs WHERE tenant_id = ? ORDER BY seq DESC LIMIT 1", (tenant_id,)).fetchone()
    prev = row["hash"] if row else GENESIS
    record = {
        "id": new_id(),
        "tenant_id": tenant_id,
        "actor_type": actor_type,
        "actor_id": actor_id,
        "action": action,
        "object_type": object_type,
        "object_id": object_id,
        "before_json": json.dumps(_mask(before), ensure_ascii=False, default=str) if before is not None else None,
        "after_json": json.dumps(_mask(after), ensure_ascii=False, default=str) if after is not None else None,
        "result": result,
        "created_at": now_iso(),
    }
    h = _digest(prev, record)
    conn.execute(
        "INSERT INTO audit_logs (id, tenant_id, actor_type, actor_id, action, object_type, object_id, ip, "
        "request_id, before_json, after_json, result, created_at, prev_hash, hash) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (record["id"], tenant_id, actor_type, actor_id, action, object_type, object_id, ip, request_id,
         record["before_json"], record["after_json"], result, record["created_at"], prev, h),
    )
    return record["id"]


def verify_chain(conn: sqlite3.Connection, tenant_id: str | None) -> dict:
    if tenant_id is None:
        rows = conn.execute("SELECT * FROM audit_logs WHERE tenant_id IS NULL ORDER BY seq").fetchall()
    else:
        rows = conn.execute("SELECT * FROM audit_logs WHERE tenant_id = ? ORDER BY seq", (tenant_id,)).fetchall()
    prev = GENESIS
    for i, row in enumerate(rows):
        record = {k: row[k] for k in CHAIN_FIELDS}
        if row["prev_hash"] != prev or _digest(prev, record) != row["hash"]:
            return {"ok": False, "records": len(rows), "broken_at_seq": row["seq"], "position": i}
        prev = row["hash"]
    return {"ok": True, "records": len(rows)}
