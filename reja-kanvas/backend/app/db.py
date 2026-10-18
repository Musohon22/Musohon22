import sqlite3
from contextlib import contextmanager
from pathlib import Path

from . import config

SCHEMA_VERSION = 2

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    tz TEXT NOT NULL DEFAULT 'Asia/Tashkent',
    lang TEXT NOT NULL DEFAULT 'uz',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS plans (
    id TEXT PRIMARY KEY,
    owner_id TEXT NOT NULL REFERENCES users(id),
    title TEXT NOT NULL,
    body_html TEXT NOT NULL DEFAULT '',
    tag TEXT,
    color TEXT NOT NULL DEFAULT 'yellow',
    x REAL NOT NULL DEFAULT 0,
    y REAL NOT NULL DEFAULT 0,
    due_at TEXT,
    remind_minutes INTEGER,
    goal TEXT NOT NULL DEFAULT '',
    done_criteria TEXT NOT NULL DEFAULT '',
    require_proof INTEGER NOT NULL DEFAULT 0,
    approver_id TEXT REFERENCES users(id),
    backup_approver_id TEXT REFERENCES users(id),
    status TEXT NOT NULL DEFAULT 'active',
    submitted_at TEXT,
    completed_at TEXT,
    approved_at TEXT,
    approved_by TEXT REFERENCES users(id),
    late_minutes INTEGER,
    rating TEXT,
    final_note TEXT,
    return_reason TEXT,
    approval_reminded_at TEXT,
    escalated_at TEXT,
    due_reminded_at TEXT,
    version INTEGER NOT NULL DEFAULT 1,
    field_versions TEXT NOT NULL DEFAULT '{}',
    search_key TEXT NOT NULL DEFAULT '',
    deleted_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS plans_owner ON plans(owner_id, deleted_at);
CREATE INDEX IF NOT EXISTS plans_approver ON plans(approver_id, status);
CREATE INDEX IF NOT EXISTS plans_backup ON plans(backup_approver_id, status);

CREATE TABLE IF NOT EXISTS steps (
    id TEXT PRIMARY KEY,
    plan_id TEXT NOT NULL REFERENCES plans(id) ON DELETE CASCADE,
    text TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'todo',
    position INTEGER NOT NULL,
    done_at TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS steps_plan ON steps(plan_id, position);

CREATE TABLE IF NOT EXISTS attachments (
    id TEXT PRIMARY KEY,
    plan_id TEXT NOT NULL REFERENCES plans(id) ON DELETE CASCADE,
    user_id TEXT NOT NULL REFERENCES users(id),
    filename TEXT NOT NULL,
    mime TEXT NOT NULL,
    size INTEGER NOT NULL,
    stored_name TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS attachments_plan ON attachments(plan_id);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id TEXT NOT NULL REFERENCES plans(id) ON DELETE CASCADE,
    user_id TEXT REFERENCES users(id),
    kind TEXT NOT NULL,
    data TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS events_plan ON events(plan_id, id);

CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL REFERENCES users(id),
    plan_id TEXT REFERENCES plans(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    data TEXT NOT NULL DEFAULT '{}',
    read_at TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS notifications_user ON notifications(user_id, read_at);

CREATE TABLE IF NOT EXISTS share_links (
    token TEXT PRIMARY KEY,
    plan_id TEXT NOT NULL REFERENCES plans(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    created_by TEXT NOT NULL REFERENCES users(id),
    expires_at TEXT NOT NULL,
    revoked_at TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


# Ordered, append-only. Each entry upgrades the schema by one version; never edit a released one.
MIGRATIONS: dict[int, list[str]] = {
    2: [
        "ALTER TABLE plans ADD COLUMN priority TEXT NOT NULL DEFAULT 'normal'",
        "ALTER TABLE plans ADD COLUMN recurrence TEXT",
        "ALTER TABLE plans ADD COLUMN series_id TEXT",
        "ALTER TABLE plans ADD COLUMN next_occurrence_id TEXT",
        "ALTER TABLE plans ADD COLUMN archived_at TEXT",
        "ALTER TABLE plans ADD COLUMN tracked_seconds INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE plans ADD COLUMN timer_started_at TEXT",
        "ALTER TABLE users ADD COLUMN token_version INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE users ADD COLUMN ics_token TEXT",
        """CREATE TABLE IF NOT EXISTS dependencies (
            plan_id TEXT NOT NULL REFERENCES plans(id) ON DELETE CASCADE,
            blocker_id TEXT NOT NULL REFERENCES plans(id) ON DELETE CASCADE,
            created_at TEXT NOT NULL,
            PRIMARY KEY (plan_id, blocker_id)
        )""",
        "CREATE INDEX IF NOT EXISTS dependencies_blocker ON dependencies(blocker_id)",
        """CREATE TABLE IF NOT EXISTS comments (
            id TEXT PRIMARY KEY,
            plan_id TEXT NOT NULL REFERENCES plans(id) ON DELETE CASCADE,
            user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
            body TEXT NOT NULL,
            created_at TEXT NOT NULL,
            edited_at TEXT
        )""",
        "CREATE INDEX IF NOT EXISTS comments_plan ON comments(plan_id, created_at)",
        """CREATE TABLE IF NOT EXISTS user_templates (
            id TEXT PRIMARY KEY,
            owner_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            data TEXT NOT NULL,
            created_at TEXT NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS time_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            plan_id TEXT NOT NULL REFERENCES plans(id) ON DELETE CASCADE,
            user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            started_at TEXT NOT NULL,
            ended_at TEXT NOT NULL,
            seconds INTEGER NOT NULL
        )""",
        "CREATE INDEX IF NOT EXISTS time_entries_user ON time_entries(user_id, started_at)",
        "CREATE UNIQUE INDEX IF NOT EXISTS users_ics_token ON users(ics_token)",
    ],
}


def connect(path: Path | None = None) -> sqlite3.Connection:
    path = Path(path or config.DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 10000")
    return conn


def init_db(path: Path | None = None) -> None:
    conn = connect(path)
    try:
        conn.executescript(SCHEMA)
        conn.execute("INSERT OR IGNORE INTO meta(key, value) VALUES ('schema_version', '1')")
        current = int(conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()[0])
        for version in sorted(v for v in MIGRATIONS if v > current):
            for statement in MIGRATIONS[version]:
                conn.execute(statement)
            conn.execute("UPDATE meta SET value = ? WHERE key = 'schema_version'", (str(version),))
        conn.commit()
    finally:
        conn.close()


@contextmanager
def session():
    """One connection per request: commit on success, roll back on any error."""
    conn = connect()
    try:
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()
