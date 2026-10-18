import sqlite3
from contextlib import contextmanager
from pathlib import Path

from . import config

SCHEMA_VERSION = 3

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
    3: [
        # plans: nesting, time blocks, goals, boards, approval chain
        "ALTER TABLE plans ADD COLUMN parent_id TEXT REFERENCES plans(id) ON DELETE SET NULL",
        "ALTER TABLE plans ADD COLUMN duration_minutes INTEGER",
        "ALTER TABLE plans ADD COLUMN goal_id TEXT",
        "ALTER TABLE plans ADD COLUMN board_id TEXT",
        "ALTER TABLE plans ADD COLUMN approval_chain TEXT NOT NULL DEFAULT '[]'",
        "ALTER TABLE plans ADD COLUMN approval_stage INTEGER NOT NULL DEFAULT 0",
        "CREATE INDEX IF NOT EXISTS plans_parent ON plans(parent_id)",
        "CREATE INDEX IF NOT EXISTS plans_board ON plans(board_id, deleted_at)",
        # steps: own due date and assignee
        "ALTER TABLE steps ADD COLUMN due_at TEXT",
        "ALTER TABLE steps ADD COLUMN assignee_id TEXT REFERENCES users(id) ON DELETE SET NULL",
        # attachments shown inside the notes (images) rather than as proof
        "ALTER TABLE attachments ADD COLUMN inline INTEGER NOT NULL DEFAULT 0",
        # users: preferences, two-factor auth
        "ALTER TABLE users ADD COLUMN prefs TEXT NOT NULL DEFAULT '{}'",
        "ALTER TABLE users ADD COLUMN totp_secret TEXT",
        "ALTER TABLE users ADD COLUMN totp_enabled INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE users ADD COLUMN recovery_codes TEXT NOT NULL DEFAULT '[]'",
        "ALTER TABLE users ADD COLUMN last_digest_on TEXT",
        "ALTER TABLE notifications ADD COLUMN emailed_at TEXT",
        """CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            user_agent TEXT NOT NULL DEFAULT '',
            ip TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL,
            revoked_at TEXT
        )""",
        "CREATE INDEX IF NOT EXISTS sessions_user ON sessions(user_id)",
        """CREATE TABLE IF NOT EXISTS password_resets (
            token_hash TEXT PRIMARY KEY,
            user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            expires_at TEXT NOT NULL,
            used_at TEXT
        )""",
        """CREATE TABLE IF NOT EXISTS api_keys (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            prefix TEXT NOT NULL,
            key_hash TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL,
            last_used_at TEXT,
            revoked_at TEXT
        )""",
        """CREATE TABLE IF NOT EXISTS webhooks (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            url TEXT NOT NULL,
            secret TEXT NOT NULL,
            events TEXT NOT NULL,
            active INTEGER NOT NULL DEFAULT 1,
            failures INTEGER NOT NULL DEFAULT 0,
            last_status TEXT,
            created_at TEXT NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS webhook_deliveries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            webhook_id TEXT NOT NULL REFERENCES webhooks(id) ON DELETE CASCADE,
            event TEXT NOT NULL,
            payload TEXT NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 0,
            next_attempt_at TEXT NOT NULL,
            delivered_at TEXT,
            last_error TEXT,
            created_at TEXT NOT NULL
        )""",
        "CREATE INDEX IF NOT EXISTS webhook_deliveries_due ON webhook_deliveries(delivered_at, next_attempt_at)",
        """CREATE TABLE IF NOT EXISTS goals (
            id TEXT PRIMARY KEY,
            owner_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            title TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            target_date TEXT,
            color TEXT NOT NULL DEFAULT 'sky',
            archived_at TEXT,
            created_at TEXT NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS saved_filters (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            query TEXT NOT NULL,
            created_at TEXT NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS comment_reactions (
            comment_id TEXT NOT NULL REFERENCES comments(id) ON DELETE CASCADE,
            user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            emoji TEXT NOT NULL,
            PRIMARY KEY (comment_id, user_id, emoji)
        )""",
        """CREATE TABLE IF NOT EXISTS signatures (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            plan_id TEXT NOT NULL REFERENCES plans(id) ON DELETE CASCADE,
            user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
            role TEXT NOT NULL,
            image TEXT NOT NULL,
            signed_at TEXT NOT NULL
        )""",
        "ALTER TABLE time_entries ADD COLUMN note TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE time_entries ADD COLUMN manual INTEGER NOT NULL DEFAULT 0",
        """CREATE TABLE IF NOT EXISTS teams (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            created_by TEXT REFERENCES users(id) ON DELETE SET NULL,
            created_at TEXT NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS team_members (
            team_id TEXT NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
            user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            role TEXT NOT NULL,
            joined_at TEXT NOT NULL,
            PRIMARY KEY (team_id, user_id)
        )""",
        """CREATE TABLE IF NOT EXISTS boards (
            id TEXT PRIMARY KEY,
            owner_id TEXT REFERENCES users(id) ON DELETE CASCADE,
            team_id TEXT REFERENCES teams(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            created_at TEXT NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS canvas_items (
            id TEXT PRIMARY KEY,
            owner_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            board_id TEXT,
            kind TEXT NOT NULL,
            x REAL NOT NULL, y REAL NOT NULL, w REAL NOT NULL, h REAL NOT NULL,
            text TEXT NOT NULL DEFAULT '',
            color TEXT NOT NULL DEFAULT 'yellow',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )""",
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
