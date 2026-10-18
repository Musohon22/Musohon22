"""Recurring plans. When an occurrence is finished, the next one is created with fresh steps.
Undoing that completion removes the next occurrence again if nobody has touched it yet."""

import calendar
import json
import sqlite3
from datetime import date, datetime, timedelta

from . import timeutil
from .plans import log_event, new_id, stamp


def _add_months(day: date, months: int) -> date:
    month_index = day.month - 1 + months
    year, month = day.year + month_index // 12, month_index % 12 + 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def _step(local: datetime, rule: dict) -> datetime:
    interval = rule.get("interval", 1)
    freq = rule["freq"]
    if freq == "daily":
        return local + timedelta(days=interval)
    if freq == "monthly":
        return datetime.combine(_add_months(local.date(), interval), local.time(), tzinfo=local.tzinfo)
    weekdays = rule.get("weekdays") or []
    if not weekdays:
        return local + timedelta(weeks=interval)
    # Next listed weekday later this week; past the last one, jump `interval` weeks to the first.
    later = [d for d in weekdays if d > local.weekday()]
    if later:
        return local + timedelta(days=later[0] - local.weekday())
    week_start = local - timedelta(days=local.weekday())
    return week_start + timedelta(weeks=interval, days=weekdays[0])


def next_due(due_utc: datetime, rule: dict, tz: str, now: datetime | None = None) -> datetime | None:
    """The next due instant after `due_utc` that is also in the future, keeping the local time
    of day (so 09:00 stays 09:00 across DST). None once the rule's `until` date has passed."""
    now = now or timeutil.now()
    zone = timeutil.zone(tz)
    local = due_utc.astimezone(zone)
    until = date.fromisoformat(rule["until"]) if rule.get("until") else None
    for _ in range(1000):
        local = _step(local, rule)
        # Rebuild from wall-clock parts so the UTC offset is recomputed for the new date.
        local = datetime.combine(local.date(), local.time().replace(tzinfo=None), tzinfo=zone)
        if until and local.date() > until:
            return None
        if local > now:
            return local.astimezone(timeutil.UTC)
    return None


def spawn_next(conn, plan: sqlite3.Row, user_tz: str) -> str | None:
    if not plan["recurrence"] or not plan["due_at"] or plan["next_occurrence_id"]:
        return None
    rule = json.loads(plan["recurrence"])
    due = next_due(timeutil.parse_iso(plan["due_at"]), rule, user_tz)
    if due is None:
        return None
    new = new_id()
    now = stamp()
    series = plan["series_id"] or plan["id"]
    conn.execute(
        """INSERT INTO plans (id, owner_id, title, body_html, tag, color, x, y, due_at, remind_minutes,
           goal, done_criteria, require_proof, approver_id, backup_approver_id, priority, recurrence,
           series_id, search_key, created_at, updated_at)
           SELECT ?, owner_id, title, body_html, tag, color, x, y + 200, ?, remind_minutes,
           goal, done_criteria, require_proof, approver_id, backup_approver_id, priority, recurrence,
           ?, search_key, ?, ? FROM plans WHERE id = ?""",
        (new, timeutil.to_iso(due), series, now, now, plan["id"]),
    )
    for step in conn.execute(
        "SELECT text, position FROM steps WHERE plan_id = ? AND status != 'cancelled' ORDER BY position", (plan["id"],)
    ).fetchall():
        conn.execute(
            "INSERT INTO steps(id, plan_id, text, position, created_at) VALUES (?,?,?,?,?)",
            (new_id(), new, step["text"], step["position"], now),
        )
    conn.execute("UPDATE plans SET next_occurrence_id = ?, series_id = ? WHERE id = ?", (new, series, plan["id"]))
    log_event(conn, new, None, "recurred", previous=plan["id"])
    return new


def retract_next(conn, plan: sqlite3.Row) -> bool:
    """Called when a finished occurrence is reopened: drop the follow-up if it is still untouched."""
    nxt = plan["next_occurrence_id"]
    if not nxt:
        return False
    row = conn.execute("SELECT status, version, deleted_at FROM plans WHERE id = ?", (nxt,)).fetchone()
    touched = conn.execute(
        "SELECT 1 FROM steps WHERE plan_id = ? AND status != 'todo' LIMIT 1", (nxt,)
    ).fetchone()
    conn.execute("UPDATE plans SET next_occurrence_id = NULL WHERE id = ?", (plan["id"],))
    if row and row["status"] == "active" and row["version"] == 1 and not touched and not row["deleted_at"]:
        conn.execute("DELETE FROM plans WHERE id = ?", (nxt,))
        return True
    return False
