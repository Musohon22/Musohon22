"""Numbers behind the analytics page: what got done, when, on time or not, and where time went."""

from collections import Counter, defaultdict
from datetime import timedelta

from . import timeutil
from .stats import _work_days, streak

WEEKDAY_COUNT = 7


def _best_streak(days: set) -> int:
    best = run = 0
    prev = None
    for d in sorted(days):
        run = run + 1 if prev is not None and d - prev == timedelta(days=1) else 1
        best = max(best, run)
        prev = d
    return best


def report(conn, user, days: int = 30) -> dict:
    tz = user["tz"]
    today = timeutil.local_today(tz)
    first = today - timedelta(days=days - 1)
    start_iso = timeutil.to_iso(timeutil.day_start_utc(first, tz))

    rows = conn.execute(
        """SELECT id, status, tag, priority, due_at, completed_at, submitted_at, created_at, late_minutes, tracked_seconds
           FROM plans WHERE owner_id = ? AND deleted_at IS NULL""",
        (user["id"],),
    ).fetchall()

    done_per_day: Counter = Counter()
    created_per_day: Counter = Counter()
    weekday_done = [0] * WEEKDAY_COUNT
    by_tag: dict[str, dict[str, int]] = defaultdict(lambda: {"done": 0, "open": 0})
    by_priority: Counter = Counter()
    on_time = late = 0
    late_total = 0
    for r in rows:
        created = timeutil.local_date(timeutil.parse_iso(r["created_at"]), tz)
        if created >= first:
            created_per_day[created] += 1
        tag = r["tag"] or ""
        if r["status"] == "done" and r["completed_at"]:
            finished = timeutil.local_date(timeutil.parse_iso(r["completed_at"]), tz)
            if finished >= first:
                done_per_day[finished] += 1
                weekday_done[finished.weekday()] += 1
                by_tag[tag]["done"] += 1
                by_priority[r["priority"]] += 1
                if r["due_at"]:
                    if r["late_minutes"]:
                        late += 1
                        late_total += r["late_minutes"]
                    else:
                        on_time += 1
        elif r["status"] in ("active", "returned", "pending_approval"):
            by_tag[tag]["open"] += 1

    series = []
    for i in range(days):
        d = first + timedelta(days=i)
        series.append({"date": d.isoformat(), "done": done_per_day[d], "created": created_per_day[d]})

    tracked = conn.execute(
        """SELECT p.tag, SUM(t.seconds) AS seconds FROM time_entries t JOIN plans p ON p.id = t.plan_id
           WHERE t.user_id = ? AND t.started_at >= ? GROUP BY p.tag ORDER BY seconds DESC""",
        (user["id"], start_iso),
    ).fetchall()

    work_days = _work_days(conn, user["id"], tz)
    current, _ = streak(work_days, today)
    total_done = sum(done_per_day.values())
    open_now = sum(1 for r in rows if r["status"] in ("active", "returned"))
    overdue_now = sum(
        1 for r in rows
        if r["status"] in ("active", "returned") and r["due_at"] and timeutil.parse_iso(r["due_at"]) < timeutil.now()
    )
    return {
        "days": days,
        "series": series,
        "total_done": total_done,
        "total_created": sum(created_per_day.values()),
        "open_now": open_now,
        "overdue_now": overdue_now,
        "on_time": on_time,
        "late": late,
        "on_time_rate": round(on_time / (on_time + late), 3) if on_time + late else None,
        "avg_late_minutes": round(late_total / late) if late else None,
        "weekday_done": weekday_done,
        "by_tag": sorted(
            ({"tag": k, **v} for k, v in by_tag.items()), key=lambda x: -(x["done"] + x["open"])
        )[:12],
        "by_priority": {p: by_priority[p] for p in ("urgent", "high", "normal", "low")},
        "tracked_by_tag": [{"tag": r["tag"] or "", "seconds": r["seconds"]} for r in tracked],
        "tracked_total": sum(r["seconds"] for r in tracked),
        "streak": current,
        "best_streak": _best_streak(work_days),
    }
