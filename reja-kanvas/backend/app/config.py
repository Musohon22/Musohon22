import os
import secrets
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("REJA_DATA_DIR", BASE_DIR / "data"))
DB_PATH = Path(os.environ.get("REJA_DB_PATH", DATA_DIR / "reja.db"))
UPLOAD_DIR = Path(os.environ.get("REJA_UPLOAD_DIR", DATA_DIR / "uploads"))
BACKUP_DIR = Path(os.environ.get("REJA_BACKUP_DIR", DATA_DIR / "backups"))

FRONTEND_ORIGINS = [
    o.strip()
    for o in os.environ.get("REJA_FRONTEND_ORIGINS", "http://localhost:3000").split(",")
    if o.strip()
]

# Where the web app lives; used in links inside emails (password reset, notifications).
FRONTEND_URL = os.environ.get("REJA_FRONTEND_URL", FRONTEND_ORIGINS[0] if FRONTEND_ORIGINS else "http://localhost:3000")

TOKEN_TTL_DAYS = 30
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
MAX_ATTACHMENTS_PER_PLAN = 10
MAX_BODY_HTML = 200_000
MAX_PLANS_PER_USER = 5000
MAX_STEPS_PER_PLAN = 50
TRASH_RETENTION_DAYS = 30
APPROVAL_REMIND_HOURS = 24
APPROVAL_ESCALATE_HOURS = 48
LOGIN_MAX_FAILURES = 10
LOGIN_WINDOW_SECONDS = 15 * 60
JOB_INTERVAL_SECONDS = 60


def secret_key() -> str:
    """REJA_SECRET_KEY, or a random key persisted next to the database so tokens survive restarts."""
    env = os.environ.get("REJA_SECRET_KEY")
    if env:
        return env
    path = DATA_DIR / "secret.key"
    if path.exists():
        return path.read_text().strip()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    key = secrets.token_urlsafe(48)
    path.write_text(key)
    path.chmod(0o600)
    return key
