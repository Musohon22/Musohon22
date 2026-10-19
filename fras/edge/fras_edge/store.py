"""Local persistent state (SQLite): identity, config, gallery package, outbox.

The outbox is the offline guarantee: every decision is written here before
the gate opens, with a monotonically increasing sequence number. Rows are
deleted only after the server acknowledged them, and only when space is
needed (spec TRM-16: un-acknowledged events are never dropped).
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from pathlib import Path

DEFAULT_CAPACITY = 100_000


class Store:
    def __init__(self, path: str, capacity: int = DEFAULT_CAPACITY):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.capacity = capacity
        self._lock = threading.Lock()
        self.conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self.conn.execute("PRAGMA journal_mode = WAL")
        self.conn.execute("PRAGMA synchronous = FULL")      # an event must survive power loss
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS outbox (
                seq INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT NOT NULL UNIQUE,
                payload TEXT NOT NULL,
                acked INTEGER NOT NULL DEFAULT 0,
                rejected TEXT,
                created_at REAL NOT NULL
            );
        """)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass

    # -- key/value
    def get(self, key: str, default=None):
        row = self.conn.execute("SELECT value FROM kv WHERE key = ?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def put(self, key: str, value) -> None:
        with self._lock:
            self.conn.execute("INSERT INTO kv(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                              (key, json.dumps(value)))

    # -- outbox
    def next_seq(self) -> int:
        row = self.conn.execute("SELECT seq FROM sqlite_sequence WHERE name = 'outbox'").fetchone()
        return (row[0] if row else 0) + 1

    def enqueue(self, event: dict, created_at: float) -> int:
        with self._lock:
            if self.pending_count() >= self.capacity:
                raise OutboxFull()
            self._make_room()
            cur = self.conn.execute("INSERT INTO outbox(event_id, payload, created_at) VALUES (?, ?, ?)",
                                    (event["event_id"], "{}", created_at))
            seq = cur.lastrowid
            event["seq"] = seq
            self.conn.execute("UPDATE outbox SET payload = ? WHERE seq = ?", (json.dumps(event), seq))
            return seq

    def _make_room(self) -> None:
        total = self.conn.execute("SELECT COUNT(*) FROM outbox").fetchone()[0]
        if total >= self.capacity:
            # only acknowledged rows may be removed
            self.conn.execute("DELETE FROM outbox WHERE seq IN (SELECT seq FROM outbox WHERE acked = 1 ORDER BY seq "
                              "LIMIT ?)", (max(1, total - self.capacity + 1),))

    def pending(self, limit: int = 500) -> list[dict]:
        rows = self.conn.execute("SELECT payload FROM outbox WHERE acked = 0 AND rejected IS NULL ORDER BY seq LIMIT ?",
                                 (limit,)).fetchall()
        return [json.loads(r[0]) for r in rows]

    def pending_count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM outbox WHERE acked = 0 AND rejected IS NULL").fetchone()[0]

    def ack(self, event_ids: list[str]) -> None:
        with self._lock:
            self.conn.executemany("UPDATE outbox SET acked = 1 WHERE event_id = ?", [(e,) for e in event_ids])

    def reject(self, event_id: str, reason: str) -> None:
        with self._lock:
            self.conn.execute("UPDATE outbox SET rejected = ? WHERE event_id = ?", (reason, event_id))

    def fill_ratio(self) -> float:
        return self.pending_count() / self.capacity

    def wipe(self) -> None:
        """Decommission: remove keys, gallery and every local record."""
        with self._lock:
            self.conn.execute("DELETE FROM kv")
            self.conn.execute("DELETE FROM outbox")
            self.conn.execute("VACUUM")


class OutboxFull(Exception):
    pass
