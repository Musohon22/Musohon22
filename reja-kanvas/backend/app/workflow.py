"""Completion and approval workflow, overdue handling and the periodic jobs
(approval reminders, escalation to the backup approver, due reminders, trash purge)."""

import math
import sqlite3
from datetime import timedelta

from . import config, dependencies, recurrence, timeutil, tracking
from .errors import ApiError, forbidden
from .plans import (
    LOCKED_STATUSES, load, load_for, log_event, notify, progress_map, purge_expired,
    serialize, stamp,
)

_CLEAR_COMPLETION = {
    "submitted_at": None, "completed_at": None, "approved_at": None, "approved_by": None,
    "late_minutes": None, "approval_reminded_at": None, "escalated_at": None,
}


def _update(conn, plan_id: str, **sets) -> None:
    sets["updated_at"] = stamp()
    conn.execute(f"UPDATE plans SET {', '.join(f'{k} = ?' for k in sets)} WHERE id = ?", (*sets.values(), plan_id))


def _late_minutes(plan: sqlite3.Row) -> int | None:
    due = timeutil.parse_iso(plan["due_at"])
    if due is None:
        return None
    late = (timeutil.now() - due).total_seconds() / 60
    return math.floor(late) if late >= 1 else 0


def _owner_tz(conn, plan: sqlite3.Row) -> str:
    return conn.execute("SELECT tz FROM users WHERE id = ?", (plan["owner_id"],)).fetchone()["tz"]


def readiness(conn, plan: sqlite3.Row) -> list[str]:
    """What still blocks confirming this plan, as stable codes the UI explains."""
    blockers = []
    if dependencies.open_blockers(conn, plan["id"]):
        blockers.append("blocked_by_open")
    prog = progress_map(conn, [plan["id"]])[plan["id"]]
    if prog["done"] < prog["total"]:
        blockers.append("steps_incomplete")
    if plan["require_proof"]:
        has = conn.execute("SELECT 1 FROM attachments WHERE plan_id = ? LIMIT 1", (plan["id"],)).fetchone()
        if not has:
            blockers.append("proof_required")
    return blockers


def submit(conn, plan: sqlite3.Row, user_id: str, data) -> dict:
    if plan["status"] not in ("active", "returned"):
        raise ApiError(409, "invalid_status", status=plan["status"])
    blockers = readiness(conn, plan)
    if blockers:
        prog = progress_map(conn, [plan["id"]])[plan["id"]]
        raise ApiError(
            400, blockers[0], blockers=blockers, remaining=prog["total"] - prog["done"],
            open_blockers=dependencies.open_blockers(conn, plan["id"]),
        )
    if plan["timer_started_at"]:
        tracking.stop(conn, plan["owner_id"])
    now = stamp()
    late = _late_minutes(plan)
    common = dict(final_note=data.final_note, rating=data.rating, late_minutes=late, submitted_at=now, return_reason=None)
    if plan["approver_id"]:
        _update(conn, plan["id"], status="pending_approval", approval_reminded_at=None, escalated_at=None, **common)
        log_event(conn, plan["id"], user_id, "submitted", late_minutes=late)
        notify(conn, plan["approver_id"], plan["id"], "approval_requested", title=plan["title"])
    else:
        _update(conn, plan["id"], status="done", completed_at=now, **common)
        log_event(conn, plan["id"], user_id, "completed", late_minutes=late)
        recurrence.spawn_next(conn, load(conn, plan["id"]), _owner_tz(conn, plan))
    return serialize(conn, load(conn, plan["id"]), user_id, detail=True)


def approve(conn, plan: sqlite3.Row, user_id: str) -> dict:
    _require_decider(plan, user_id)
    now = stamp()
    # The work counts on the day it was submitted, not the day someone got round to approving it.
    _update(conn, plan["id"], status="done", completed_at=plan["submitted_at"], approved_at=now, approved_by=user_id)
    log_event(conn, plan["id"], user_id, "approved")
    recurrence.spawn_next(conn, load(conn, plan["id"]), _owner_tz(conn, plan))
    notify(conn, plan["owner_id"], plan["id"], "approved", title=plan["title"])
    return serialize(conn, load(conn, plan["id"]), user_id, detail=True)


def reject(conn, plan: sqlite3.Row, user_id: str, data) -> dict:
    _require_decider(plan, user_id)
    _update(conn, plan["id"], status="returned", return_reason=data.reason, **_CLEAR_COMPLETION)
    log_event(conn, plan["id"], user_id, "returned", reason=data.reason)
    notify(conn, plan["owner_id"], plan["id"], "returned", title=plan["title"], reason=data.reason)
    return serialize(conn, load(conn, plan["id"]), user_id, detail=True)


def _require_decider(plan: sqlite3.Row, user_id: str) -> None:
    if plan["status"] != "pending_approval":
        raise ApiError(409, "invalid_status", status=plan["status"])
    if plan["approver_id"] == user_id:
        return
    if plan["backup_approver_id"] == user_id:
        if plan["escalated_at"] is None:
            raise forbidden("not_escalated_yet")
        return
    raise forbidden("not_approver")


def reopen(conn, plan: sqlite3.Row, user_id: str, data) -> dict:
    """Undo a confirmation (the 10-second toast), withdraw a pending submission, or reopen a
    finished/cancelled plan. Always recorded in the history."""
    is_owner = plan["owner_id"] == user_id
    is_approver = user_id in (plan["approver_id"], plan["backup_approver_id"])
    if plan["status"] == "pending_approval":
        if not is_owner:
            raise forbidden("owner_only")
        kind = "withdrawn"
    elif plan["status"] in ("done", "cancelled"):
        if not (is_owner or (is_approver and plan["status"] == "done")):
            raise forbidden("owner_only")
        kind = "undone" if data.reason == "undo" else "reopened"
    else:
        raise ApiError(409, "invalid_status", status=plan["status"])
    _update(conn, plan["id"], status="active", **_CLEAR_COMPLETION)
    log_event(conn, plan["id"], user_id, kind, note=data.note)
    if plan["status"] == "done":
        recurrence.retract_next(conn, plan)
    if plan["approved_by"] and plan["approved_by"] != user_id:
        notify(conn, plan["approved_by"], plan["id"], "reopened", title=plan["title"])
    if plan["status"] == "pending_approval":
        notify(conn, plan["approver_id"], plan["id"], "withdrawn", title=plan["title"])
    return serialize(conn, load(conn, plan["id"]), user_id, detail=True)


def cancel(conn, plan: sqlite3.Row, user_id: str) -> dict:
    if plan["status"] not in ("active", "returned"):
        raise ApiError(409, "invalid_status", status=plan["status"])
    _update(conn, plan["id"], status="cancelled")
    log_event(conn, plan["id"], user_id, "cancelled")
    return serialize(conn, load(conn, plan["id"]), user_id, detail=True)


# ---- overdue ----------------------------------------------------------------------------

def overdue(conn, user: sqlite3.Row) -> list[dict]:
    start = timeutil.to_iso(timeutil.day_start_utc(timeutil.local_today(user["tz"]), user["tz"]))
    rows = conn.execute(
        """SELECT * FROM plans WHERE owner_id = ? AND deleted_at IS NULL
           AND status IN ('active', 'returned') AND due_at IS NOT NULL AND due_at < ?
           ORDER BY due_at""",
        (user["id"], start),
    ).fetchall()
    prog = progress_map(conn, [r["id"] for r in rows])
    return [serialize(conn, r, user["id"], progress=prog[r["id"]]) for r in rows]


def reschedule(conn, user: sqlite3.Row, data) -> list[dict]:
    if data.action == "date" and data.date is None:
        raise ApiError(400, "date_required")
    tz = user["tz"]
    target_day = timeutil.local_today(tz) if data.action == "today" else data.date
    out = []
    for pid in data.ids:
        plan = load_for(conn, pid, user["id"], "edit")
        if plan["status"] in LOCKED_STATUSES:
            continue
        if data.action == "cancel":
            if plan["status"] in ("active", "returned"):
                out.append(cancel(conn, plan, user["id"]))
            continue
        old = timeutil.parse_iso(plan["due_at"])
        local_old = old.astimezone(timeutil.zone(tz)) if old else None
        hour, minute = (local_old.hour, local_old.minute) if local_old else (18, 0)
        new_due = timeutil.to_iso(timeutil.at_local(target_day, hour, minute, tz))
        _update(conn, plan["id"], due_at=new_due, due_reminded_at=None)
        log_event(conn, plan["id"], user["id"], "rescheduled", **{"from": plan["due_at"], "to": new_due})
        out.append(serialize(conn, load(conn, plan["id"]), user["id"]))
    return out


# ---- periodic jobs ----------------------------------------------------------------------

def run_jobs(conn) -> dict:
    now = timeutil.now()
    counts = {"reminded": 0, "escalated": 0, "due_reminders": 0, "purged": 0}

    remind_before = timeutil.to_iso(now - timedelta(hours=config.APPROVAL_REMIND_HOURS))
    for plan in conn.execute(
        """SELECT * FROM plans WHERE status = 'pending_approval' AND deleted_at IS NULL
           AND approval_reminded_at IS NULL AND submitted_at <= ?""",
        (remind_before,),
    ).fetchall():
        notify(conn, plan["approver_id"], plan["id"], "approval_reminder", title=plan["title"])
        conn.execute("UPDATE plans SET approval_reminded_at = ? WHERE id = ?", (timeutil.to_iso(now), plan["id"]))
        counts["reminded"] += 1

    escalate_before = timeutil.to_iso(now - timedelta(hours=config.APPROVAL_ESCALATE_HOURS))
    for plan in conn.execute(
        """SELECT * FROM plans WHERE status = 'pending_approval' AND deleted_at IS NULL
           AND escalated_at IS NULL AND submitted_at <= ?""",
        (escalate_before,),
    ).fetchall():
        conn.execute("UPDATE plans SET escalated_at = ? WHERE id = ?", (timeutil.to_iso(now), plan["id"]))
        if plan["backup_approver_id"]:
            notify(conn, plan["backup_approver_id"], plan["id"], "approval_escalated", title=plan["title"])
            log_event(conn, plan["id"], None, "escalated")
        notify(
            conn, plan["owner_id"], plan["id"], "approver_silent",
            title=plan["title"], has_backup=bool(plan["backup_approver_id"]),
        )
        counts["escalated"] += 1

    for plan in conn.execute(
        """SELECT * FROM plans WHERE status IN ('active', 'returned') AND deleted_at IS NULL
           AND due_at IS NOT NULL AND remind_minutes IS NOT NULL AND due_reminded_at IS NULL
           AND due_at > ?""",
        (timeutil.to_iso(now),),
    ).fetchall():
        due = timeutil.parse_iso(plan["due_at"])
        if due - timedelta(minutes=plan["remind_minutes"]) <= now:
            notify(conn, plan["owner_id"], plan["id"], "due_soon", title=plan["title"], due_at=plan["due_at"])
            conn.execute("UPDATE plans SET due_reminded_at = ? WHERE id = ?", (timeutil.to_iso(now), plan["id"]))
            counts["due_reminders"] += 1

    counts["purged"] = purge_expired(conn)
    return counts
