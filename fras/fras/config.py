"""Runtime configuration, read once from environment variables."""

from __future__ import annotations

import base64
import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    return value if value not in (None, "") else default


@dataclass
class Settings:
    env: str = "dev"                      # dev | test | prod
    db_path: str = str(BASE_DIR / "var" / "fras.db")
    data_dir: str = str(BASE_DIR / "var")
    secret_key: str = ""                  # signs JWTs
    master_key: bytes = b""               # wraps tenant data keys (32 bytes)
    access_token_ttl_s: int = 900
    refresh_token_ttl_s: int = 12 * 3600
    biometric_provider: str = "dev"       # dev | onnx
    detector_model: str | None = None     # path to SCRFD-style ONNX detector
    recognizer_model: str | None = None   # path to ArcFace-style ONNX recognizer
    pad_model: str | None = None          # optional presentation-attack model
    smtp_host: str | None = None
    telegram_bot_token: str | None = None
    public_base_url: str = "http://localhost:8000"
    heartbeat_offline_s: int = 90
    web_dir: str = str(BASE_DIR / "web")
    cors_origins: list[str] = field(default_factory=list)
    # Dev/demo only: lets privileged demo accounts work without enrolling MFA. Refused in prod.
    relax_mfa: bool = False

    @property
    def is_prod(self) -> bool:
        return self.env == "prod"


def load_settings() -> Settings:
    env = _env("FRAS_ENV", "dev")
    s = Settings(env=env)
    s.data_dir = _env("FRAS_DATA_DIR", s.data_dir)
    s.db_path = _env("FRAS_DB_PATH", str(Path(s.data_dir) / "fras.db"))
    s.biometric_provider = _env("FRAS_BIOMETRIC_PROVIDER", "onnx" if env == "prod" else "dev")
    s.detector_model = _env("FRAS_DETECTOR_MODEL")
    s.recognizer_model = _env("FRAS_RECOGNIZER_MODEL")
    s.pad_model = _env("FRAS_PAD_MODEL")
    s.smtp_host = _env("FRAS_SMTP_HOST")
    s.telegram_bot_token = _env("FRAS_TELEGRAM_BOT_TOKEN")
    s.public_base_url = _env("FRAS_PUBLIC_URL", s.public_base_url)
    s.heartbeat_offline_s = int(_env("FRAS_HEARTBEAT_OFFLINE_S", "90"))
    s.web_dir = _env("FRAS_WEB_DIR", s.web_dir)
    s.relax_mfa = _env("FRAS_DEV_RELAX_MFA", "0") == "1"
    if env == "prod" and s.relax_mfa:
        raise RuntimeError("FRAS_DEV_RELAX_MFA is not allowed in prod")

    secret = _env("FRAS_SECRET_KEY")
    master = _env("FRAS_MASTER_KEY")
    if env == "prod" and (not secret or not master):
        raise RuntimeError("FRAS_SECRET_KEY and FRAS_MASTER_KEY must be set in prod")
    if env == "prod" and s.biometric_provider == "dev":
        raise RuntimeError("The dev biometric provider is not a real face recognizer and is refused in prod")
    s.secret_key = secret or _dev_secret(s.data_dir, "secret_key")
    s.master_key = base64.b64decode(master) if master else base64.b64decode(_dev_secret(s.data_dir, "master_key"))
    if len(s.master_key) != 32:
        raise RuntimeError("FRAS_MASTER_KEY must be 32 bytes, base64-encoded")
    return s


def _dev_secret(data_dir: str, name: str) -> str:
    """Persist generated secrets in the data dir so dev restarts keep sessions and keys."""
    path = Path(data_dir) / f".{name}"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    value = base64.b64encode(secrets.token_bytes(32)).decode()
    path.write_text(value, encoding="utf-8")
    os.chmod(path, 0o600)
    return value
