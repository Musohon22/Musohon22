"""Consistent online backup of the SQLite database (safe while the server is running).

    python -m scripts.backup            # writes data/backups/reja-YYYYmmdd-HHMMSS.db, keeps the last 14
Schedule it daily with cron or a systemd timer. Uploaded files live in data/uploads; copy that
folder alongside (e.g. rsync) to back up attachments."""

import sqlite3
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config  # noqa: E402

KEEP = 14


def main() -> Path:
    config.BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    target = config.BACKUP_DIR / f"reja-{datetime.now():%Y%m%d-%H%M%S}.db"
    src = sqlite3.connect(config.DB_PATH)
    dst = sqlite3.connect(target)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    for old in sorted(config.BACKUP_DIR.glob("reja-*.db"))[:-KEEP]:
        old.unlink()
    return target


if __name__ == "__main__":
    print(main())
