from datetime import date, timedelta

from . import timeutil


def _work_days(conn, user_id: str, tz: str) -> set[date]:
    days = set()
    for row in conn.execute(
        """SELECT completed_at, submitted_at, status FROM plans WHERE owner_id = ? AND deleted_at IS NULL
           AND status IN ('done', 'pending_approval')""",
        (user_id,),
    ):
        when = row["completed_at"] if row["status"] == "done" else row["submitted_at"]
        if when:
            days.add(timeutil.local_date(timeutil.parse_iso(when), tz))
    return days


def streak(days: set[date], today: date) -> tuple[int, bool]:
    """Consecutive days with at least one finished plan. One missed day per ISO week is
    forgiven (a "freeze"), so a single slip does not wipe out a long run. Today does not
    break the streak while it is still in progress. Returns (streak, freeze used this week)."""
    if not days:
        return 0, False
    earliest = min(days)
    current = today if today in days else today - timedelta(days=1)
    count = 0
    frozen_weeks: set[tuple[int, int]] = set()
    while current >= earliest:
        if current in days:
            count += 1
        else:
            week = current.isocalendar()[:2]
            if week in frozen_weeks or count == 0:
                break
            frozen_weeks.add(week)
        current -= timedelta(days=1)
    return count, today.isocalendar()[:2] in frozen_weeks


def summary(conn, user) -> dict:
    tz = user["tz"]
    today = timeutil.local_today(tz)
    start, end = (timeutil.to_iso(d) for d in timeutil.day_bounds_utc(today, tz))
    rows = conn.execute(
        """SELECT status, due_at, completed_at, submitted_at FROM plans
           WHERE owner_id = ? AND deleted_at IS NULL AND status != 'cancelled'
           AND ((due_at >= ? AND due_at < ?) OR (completed_at >= ? AND completed_at < ?)
                OR (submitted_at >= ? AND submitted_at < ?))""",
        (user["id"], start, end, start, end, start, end),
    ).fetchall()
    total = len(rows)
    finished = sum(1 for r in rows if r["status"] in ("done", "pending_approval"))
    count, freeze_used = streak(_work_days(conn, user["id"], tz), today)
    pending_mine = conn.execute(
        """SELECT COUNT(*) FROM plans WHERE deleted_at IS NULL AND status = 'pending_approval'
           AND (approver_id = ? OR (backup_approver_id = ? AND escalated_at IS NOT NULL))""",
        (user["id"], user["id"]),
    ).fetchone()[0]
    unread = conn.execute(
        "SELECT COUNT(*) FROM notifications WHERE user_id = ? AND read_at IS NULL", (user["id"],)
    ).fetchone()[0]
    return {
        "today": today.isoformat(),
        "today_total": total,
        "today_done": finished,
        "streak": count,
        "freeze_used_this_week": freeze_used,
        "awaiting_my_approval": pending_mine,
        "unread_notifications": unread,
    }
