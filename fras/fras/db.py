"""SQLite access: connections, migrations, and small query helpers.

Each request gets its own connection (cheap for SQLite) and runs inside one
transaction. WAL mode lets readers proceed while a writer holds the lock.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def _dict_factory(cursor: sqlite3.Cursor, row: tuple) -> dict:
    return {col[0]: row[i] for i, col in enumerate(cursor.description)}


class Database:
    def __init__(self, path: str):
        self.path = path
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._memory_conn: sqlite3.Connection | None = None

    def connect(self) -> sqlite3.Connection:
        if self.path == ":memory:":
            # Tests share one in-memory connection; requests are serialized by the test client.
            if self._memory_conn is None:
                self._memory_conn = self._open()
            return self._memory_conn
        return self._open()

    def _open(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=15, isolation_level=None, check_same_thread=False)
        conn.row_factory = _dict_factory
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 15000")
        if self.path != ":memory:":
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA synchronous = NORMAL")
        return conn

    def release(self, conn: sqlite3.Connection) -> None:
        if conn is not self._memory_conn:
            conn.close()

    @contextmanager
    def tx(self, write: bool = True):
        conn = self.connect()
        try:
            conn.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield conn
            conn.execute("COMMIT")
        except BaseException:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        finally:
            self.release(conn)

    def migrate(self) -> list[str]:
        conn = self.connect()
        try:
            conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations (name TEXT PRIMARY KEY, applied_at TEXT NOT NULL)")
            done = {r["name"] for r in conn.execute("SELECT name FROM schema_migrations").fetchall()}
            applied = []
            for file in sorted(MIGRATIONS_DIR.glob("*.sql")):
                if file.name in done:
                    continue
                conn.executescript("BEGIN;\n" + file.read_text() + "\nCOMMIT;")
                conn.execute(
                    "INSERT INTO schema_migrations(name, applied_at) VALUES (?, datetime('now'))", (file.name,)
                )
                applied.append(file.name)
            return applied
        finally:
            self.release(conn)


# ----------------------------------------------------------------- helpers

def one(conn: sqlite3.Connection, sql: str, params: Iterable[Any] = ()) -> dict | None:
    return conn.execute(sql, tuple(params)).fetchone()


def all_(conn: sqlite3.Connection, sql: str, params: Iterable[Any] = ()) -> list[dict]:
    return conn.execute(sql, tuple(params)).fetchall()


def scalar(conn: sqlite3.Connection, sql: str, params: Iterable[Any] = ()):
    row = conn.execute(sql, tuple(params)).fetchone()
    if row is None:
        return None
    return next(iter(row.values()))


def insert(conn: sqlite3.Connection, table: str, values: dict) -> dict:
    cols = ", ".join(values)
    marks = ", ".join("?" for _ in values)
    conn.execute(f"INSERT INTO {table} ({cols}) VALUES ({marks})", tuple(values.values()))
    return values


def update(conn: sqlite3.Connection, table: str, key: dict, values: dict) -> int:
    if not values:
        return 0
    sets = ", ".join(f"{k} = ?" for k in values)
    where = " AND ".join(f"{k} = ?" for k in key)
    cur = conn.execute(f"UPDATE {table} SET {sets} WHERE {where}", (*values.values(), *key.values()))
    return cur.rowcount
