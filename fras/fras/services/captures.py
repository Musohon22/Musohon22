"""Encrypted storage of terminal captures for suspicious events (kept 30 days by policy)."""

from __future__ import annotations

import base64
from pathlib import Path

from ..security import crypto
from ..util import new_id


def _key(dek: bytes) -> bytes:
    return crypto.derive(dek, "capture")


def store(data_dir: str, tenant_id: str, dek: bytes, jpeg: bytes) -> str:
    ref = new_id()
    folder = Path(data_dir) / "captures" / tenant_id
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{ref}.bin").write_bytes(crypto.seal(_key(dek), jpeg, aad=ref.encode()))
    return ref


def load_data_url(ctx, ref: str) -> str:
    path = Path(ctx.settings.data_dir) / "captures" / ctx.tenant_id / f"{ref}.bin"
    if not path.exists():
        from ..errors import not_found
        raise not_found("Capture")
    jpeg = crypto.open_sealed(_key(ctx.dek()), path.read_bytes(), aad=ref.encode())
    return "data:image/jpeg;base64," + base64.b64encode(jpeg).decode()


def delete(data_dir: str, tenant_id: str, ref: str) -> None:
    path = Path(data_dir) / "captures" / tenant_id / f"{ref}.bin"
    if path.exists():
        path.unlink()
