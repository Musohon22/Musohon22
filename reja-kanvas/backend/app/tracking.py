"""Time tracking: one running timer per user; starting another stops the first."""

from . import timeutil
from .errors import ApiError
from .plans import stamp

MAX_ENTRY_SECONDS = 12 * 3600  # a forgotten timer never books more than 12 hours


def stop(conn, user_id: str) -> int:
    """Stops this user's running timer, if any; returns the seconds booked."""
    row = conn.execute(
        """SELECT id, timer_started_at FROM plans WHERE owner_id = ? AND timer_started_at IS NOT NULL""",
        (user_id,),
    ).fetchone()
    if row is None:
        return 0
    started = timeutil.parse_iso(row["timer_started_at"])
    seconds = int(min(MAX_ENTRY_SECONDS, max(0, (timeutil.now() - started).total_seconds())))
    conn.execute(
        "INSERT INTO time_entries(plan_id, user_id, started_at, ended_at, seconds) VALUES (?,?,?,?,?)",
        (row["id"], user_id, row["timer_started_at"], stamp(), seconds),
    )
    conn.execute(
        "UPDATE plans SET timer_started_at = NULL, tracked_seconds = tracked_seconds + ? WHERE id = ?",
        (seconds, row["id"]),
    )
    return seconds


def start(conn, plan, user_id: str) -> None:
    if plan["status"] not in ("active", "returned"):
        raise ApiError(409, "invalid_status", status=plan["status"])
    if plan["timer_started_at"]:
        return
    stop(conn, user_id)
    conn.execute("UPDATE plans SET timer_started_at = ? WHERE id = ?", (stamp(), plan["id"]))


def total_between(conn, user_id: str, start_iso: str, end_iso: str) -> int:
    return conn.execute(
        "SELECT COALESCE(SUM(seconds), 0) FROM time_entries WHERE user_id = ? AND started_at >= ? AND started_at < ?",
        (user_id, start_iso, end_iso),
    ).fetchone()[0]
