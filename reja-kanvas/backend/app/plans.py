"""Plans, steps, trash and the field-level merge that lets two devices edit one plan."""

import json
import sqlite3
import uuid
from datetime import timedelta

from . import config, timeutil
from .errors import ApiError, forbidden, not_found
from .sanitize import html_to_text, sanitize_html
from .translit import normalize

# Fields whose concurrent edits are detected; x/y are last-write-wins (dragging must never conflict).
TRACKED = (
    "title", "body_html", "tag", "color", "due_at", "remind_minutes", "goal",
    "done_criteria", "require_proof", "approver_id", "backup_approver_id", "priority", "recurrence",
)
POSITION = ("x", "y")
# Once submitted or confirmed, the content is frozen until the plan is reopened.
LOCKED_STATUSES = ("pending_approval", "done")
EDITABLE_WHEN_LOCKED = {"color", "tag", "x", "y", "priority"}
PRIORITY_ORDER = "CASE priority WHEN 'urgent' THEN 0 WHEN 'high' THEN 1 WHEN 'normal' THEN 2 ELSE 3 END"


def new_id() -> str:
    return str(uuid.uuid4())


def stamp() -> str:
    return timeutil.to_iso(timeutil.now())


def log_event(conn, plan_id: str, user_id: str | None, kind: str, **data) -> None:
    conn.execute(
        "INSERT INTO events(plan_id, user_id, kind, data, created_at) VALUES (?,?,?,?,?)",
        (plan_id, user_id, kind, json.dumps(data, ensure_ascii=False), stamp()),
    )


def notify(conn, user_id: str | None, plan_id: str | None, kind: str, **data) -> None:
    if user_id:
        conn.execute(
            "INSERT INTO notifications(user_id, plan_id, kind, data, created_at) VALUES (?,?,?,?,?)",
            (user_id, plan_id, kind, json.dumps(data, ensure_ascii=False), stamp()),
        )


def user_brief(conn, user_id: str | None) -> dict | None:
    if not user_id:
        return None
    row = conn.execute("SELECT id, name, email FROM users WHERE id = ?", (user_id,)).fetchone()
    return dict(row) if row else None


def _search_key(title: str, body_html: str, tag: str | None, goal: str) -> str:
    return normalize(" ".join([title, tag or "", goal, html_to_text(body_html)[:2000]]))


def progress_map(conn, plan_ids: list[str]) -> dict[str, dict]:
    result = {pid: {"done": 0, "total": 0, "cancelled": 0} for pid in plan_ids}
    if not plan_ids:
        return result
    marks = ",".join("?" * len(plan_ids))
    for row in conn.execute(
        f"SELECT plan_id, status, COUNT(*) AS n FROM steps WHERE plan_id IN ({marks}) GROUP BY plan_id, status",
        plan_ids,
    ):
        p = result[row["plan_id"]]
        if row["status"] == "cancelled":
            p["cancelled"] += row["n"]
        else:
            p["total"] += row["n"]
            if row["status"] == "done":
                p["done"] += row["n"]
    return result


def blockers_map(conn, plan_ids: list[str]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {pid: [] for pid in plan_ids}
    if not plan_ids:
        return result
    marks = ",".join("?" * len(plan_ids))
    for row in conn.execute(f"SELECT plan_id, blocker_id FROM dependencies WHERE plan_id IN ({marks})", plan_ids):
        result[row["plan_id"]].append(row["blocker_id"])
    return result


def role_of(plan: sqlite3.Row, user_id: str) -> str | None:
    if plan["owner_id"] == user_id:
        return "owner"
    if plan["approver_id"] == user_id:
        return "approver"
    if plan["backup_approver_id"] == user_id:
        return "backup"
    return None


def can_decide(plan: sqlite3.Row, user_id: str) -> bool:
    """The approver decides; the backup approver only once the request has been escalated."""
    if plan["status"] != "pending_approval":
        return False
    if plan["approver_id"] == user_id:
        return True
    return plan["backup_approver_id"] == user_id and plan["escalated_at"] is not None


def serialize(
    conn, plan: sqlite3.Row, user_id: str | None, *, detail: bool = False,
    progress: dict | None = None, blocked_by: list[str] | None = None,
) -> dict:
    data = {
        k: plan[k]
        for k in (
            "id", "title", "tag", "color", "x", "y", "due_at", "remind_minutes", "goal",
            "done_criteria", "status", "submitted_at", "completed_at", "approved_at",
            "late_minutes", "rating", "final_note", "return_reason", "escalated_at",
            "version", "deleted_at", "created_at", "updated_at", "owner_id",
            "approver_id", "backup_approver_id", "priority", "series_id", "next_occurrence_id",
            "archived_at", "tracked_seconds", "timer_started_at",
        )
    }
    data["require_proof"] = bool(plan["require_proof"])
    data["recurrence"] = json.loads(plan["recurrence"]) if plan["recurrence"] else None
    data["blocked_by"] = blocked_by if blocked_by is not None else blockers_map(conn, [plan["id"]])[plan["id"]]
    data["progress"] = progress or progress_map(conn, [plan["id"]])[plan["id"]]
    if user_id:
        data["my_role"] = role_of(plan, user_id)
        data["can_decide"] = can_decide(plan, user_id)
    if detail:
        data["body_html"] = plan["body_html"]
        data["steps"] = [
            dict(r)
            for r in conn.execute(
                "SELECT id, text, status, position, done_at FROM steps WHERE plan_id = ? ORDER BY position, created_at",
                (plan["id"],),
            )
        ]
        data["attachments"] = [
            dict(r)
            for r in conn.execute(
                "SELECT id, filename, mime, size, created_at FROM attachments WHERE plan_id = ? ORDER BY created_at",
                (plan["id"],),
            )
        ]
        data["owner"] = user_brief(conn, plan["owner_id"])
        data["approver"] = user_brief(conn, plan["approver_id"])
        data["backup_approver"] = user_brief(conn, plan["backup_approver_id"])
        data["approved_by"] = user_brief(conn, plan["approved_by"])
    return data


def load(conn, plan_id: str, *, include_deleted: bool = False) -> sqlite3.Row:
    try:
        plan_id = str(uuid.UUID(plan_id))
    except ValueError:
        raise not_found()
    row = conn.execute("SELECT * FROM plans WHERE id = ?", (plan_id,)).fetchone()
    if row is None or (row["deleted_at"] and not include_deleted):
        raise not_found()
    return row


def load_for(conn, plan_id: str, user_id: str, need: str = "view", *, include_deleted: bool = False) -> sqlite3.Row:
    """need: 'view' (owner or approvers) or 'edit' (owner only). Strangers get 404, never 403,
    so plan ids cannot be probed."""
    plan = load(conn, plan_id, include_deleted=include_deleted)
    role = role_of(plan, user_id)
    if role is None:
        raise not_found()
    if need == "edit" and role != "owner":
        raise forbidden("owner_only")
    return plan


def _check_people(conn, owner_id: str, approver_id: str | None, backup_id: str | None) -> None:
    for uid in (approver_id, backup_id):
        if uid is None:
            continue
        if uid == owner_id:
            raise ApiError(400, "approver_is_owner")
        if conn.execute("SELECT 1 FROM users WHERE id = ?", (uid,)).fetchone() is None:
            raise ApiError(400, "approver_not_found")
    if backup_id and not approver_id:
        raise ApiError(400, "backup_without_approver")
    if backup_id and backup_id == approver_id:
        raise ApiError(400, "backup_same_as_approver")


def list_for_owner(conn, user_id: str, q: str | None = None, *, archived: bool = False) -> list[dict]:
    sql = "SELECT * FROM plans WHERE owner_id = ? AND deleted_at IS NULL"
    sql += " AND archived_at IS NOT NULL" if archived else " AND archived_at IS NULL"
    args: list = [user_id]
    if q:
        sql += " AND search_key LIKE ?"
        args.append("%" + normalize(q).replace("%", "").replace("_", "") + "%")
    sql += f" ORDER BY COALESCE(due_at, '9999'), {PRIORITY_ORDER}, created_at"
    rows = conn.execute(sql, args).fetchall()
    ids = [r["id"] for r in rows]
    prog = progress_map(conn, ids)
    deps = blockers_map(conn, ids)
    return [serialize(conn, r, user_id, progress=prog[r["id"]], blocked_by=deps[r["id"]]) for r in rows]


def list_awaiting_me(conn, user_id: str) -> list[dict]:
    rows = conn.execute(
        """SELECT * FROM plans WHERE deleted_at IS NULL AND status = 'pending_approval'
           AND (approver_id = ? OR (backup_approver_id = ? AND escalated_at IS NOT NULL))
           ORDER BY submitted_at""",
        (user_id, user_id),
    ).fetchall()
    prog = progress_map(conn, [r["id"] for r in rows])
    out = []
    for r in rows:
        item = serialize(conn, r, user_id, progress=prog[r["id"]])
        item["owner"] = user_brief(conn, r["owner_id"])
        out.append(item)
    return out


def create(conn, user_id: str, data) -> dict:
    count = conn.execute(
        "SELECT COUNT(*) FROM plans WHERE owner_id = ? AND deleted_at IS NULL", (user_id,)
    ).fetchone()[0]
    if count >= config.MAX_PLANS_PER_USER:
        raise ApiError(400, "plan_limit_reached", limit=config.MAX_PLANS_PER_USER)
    plan_id = data.id or new_id()
    existing = conn.execute("SELECT owner_id FROM plans WHERE id = ?", (plan_id,)).fetchone()
    if existing is not None:
        # An offline client retrying the same create: answer with what is already there.
        if existing["owner_id"] != user_id:
            raise ApiError(409, "id_taken")
        return serialize(conn, load(conn, plan_id, include_deleted=True), user_id, detail=True)
    if len(data.steps) > config.MAX_STEPS_PER_PLAN:
        raise ApiError(400, "too_many_steps")
    _check_people(conn, user_id, data.approver_id, data.backup_approver_id)
    body = sanitize_html(data.body_html)
    now = stamp()
    conn.execute(
        """INSERT INTO plans (id, owner_id, title, body_html, tag, color, x, y, due_at, remind_minutes,
           goal, done_criteria, require_proof, approver_id, backup_approver_id, priority, recurrence,
           search_key, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            plan_id, user_id, data.title, body, data.tag, data.color, data.x, data.y,
            timeutil.to_iso(data.due_at), data.remind_minutes, data.goal, data.done_criteria,
            int(data.require_proof), data.approver_id, data.backup_approver_id, data.priority,
            recurrence_json(data.recurrence), _search_key(data.title, body, data.tag, data.goal), now, now,
        ),
    )
    for pos, text in enumerate(data.steps):
        conn.execute(
            "INSERT INTO steps(id, plan_id, text, position, created_at) VALUES (?,?,?,?,?)",
            (new_id(), plan_id, text, pos, now),
        )
    log_event(conn, plan_id, user_id, "created")
    return serialize(conn, load(conn, plan_id), user_id, detail=True)


def recurrence_json(value) -> str | None:
    if value is None:
        return None
    data = value.model_dump(mode="json") if hasattr(value, "model_dump") else value
    return json.dumps(data, sort_keys=True)


def _normalize_value(field: str, value):
    if field == "recurrence":
        return recurrence_json(value)
    if field == "due_at":
        return timeutil.to_iso(value)
    if field == "require_proof":
        return int(value)
    if field == "body_html":
        return sanitize_html(value)
    return value


def apply_patch(conn, plan: sqlite3.Row, user_id: str | None, base_version: int, changes: dict, *, via: str | None = None) -> dict:
    """Field-level optimistic merge. A field conflicts only if someone else changed it after
    base_version and the incoming value differs; non-overlapping edits merge silently."""
    if base_version > plan["version"]:
        raise ApiError(400, "bad_base_version")
    values = {f: _normalize_value(f, v) for f, v in changes.items()}
    changed = {f: v for f, v in values.items() if plan[f] != v}
    if not changed:
        return serialize(conn, plan, user_id, detail=True)

    if plan["status"] in LOCKED_STATUSES:
        blocked = [f for f in changed if f not in EDITABLE_WHEN_LOCKED]
        if blocked:
            raise ApiError(409, "plan_locked", fields=blocked, status=plan["status"])

    field_versions = json.loads(plan["field_versions"])
    conflicts = [f for f in changed if f in TRACKED and field_versions.get(f, 0) > base_version]
    if conflicts:
        raise ApiError(
            409, "conflict", fields=conflicts,
            server=serialize(conn, plan, user_id, detail=True),
        )

    if "approver_id" in changed or "backup_approver_id" in changed:
        _check_people(
            conn, plan["owner_id"],
            changed.get("approver_id", plan["approver_id"]),
            changed.get("backup_approver_id", plan["backup_approver_id"]),
        )

    tracked_changed = [f for f in changed if f in TRACKED]
    version = plan["version"] + 1 if tracked_changed else plan["version"]
    for f in tracked_changed:
        field_versions[f] = version
    sets = dict(changed)
    if "due_at" in changed or "remind_minutes" in changed:
        sets["due_reminded_at"] = None
    merged = {k: sets.get(k, plan[k]) for k in ("title", "body_html", "tag", "goal")}
    sets["search_key"] = _search_key(merged["title"], merged["body_html"], merged["tag"], merged["goal"])
    sets["version"] = version
    sets["field_versions"] = json.dumps(field_versions)
    sets["updated_at"] = stamp()
    conn.execute(
        f"UPDATE plans SET {', '.join(f'{k} = ?' for k in sets)} WHERE id = ?",
        (*sets.values(), plan["id"]),
    )
    if tracked_changed:
        log_event(conn, plan["id"], user_id, "edited", fields=tracked_changed, **({"via": via} if via else {}))
    return serialize(conn, load(conn, plan["id"]), user_id, detail=True)


def batch_move(conn, user_id: str, items) -> list[dict]:
    out = []
    now = stamp()
    for item in items:
        plan = load_for(conn, item.id, user_id, "edit")
        conn.execute("UPDATE plans SET x = ?, y = ?, updated_at = ? WHERE id = ?", (item.x, item.y, now, plan["id"]))
        out.append({"id": plan["id"], "x": item.x, "y": item.y, "version": plan["version"]})
    return out


def soft_delete(conn, plan: sqlite3.Row, user_id: str) -> None:
    conn.execute("UPDATE plans SET deleted_at = ?, updated_at = ? WHERE id = ?", (stamp(), stamp(), plan["id"]))
    log_event(conn, plan["id"], user_id, "deleted")


def restore(conn, plan: sqlite3.Row, user_id: str) -> dict:
    if not plan["deleted_at"]:
        return serialize(conn, plan, user_id, detail=True)
    conn.execute("UPDATE plans SET deleted_at = NULL, updated_at = ? WHERE id = ?", (stamp(), plan["id"]))
    log_event(conn, plan["id"], user_id, "restored")
    return serialize(conn, load(conn, plan["id"]), user_id, detail=True)


def list_trash(conn, user_id: str) -> list[dict]:
    purge_expired(conn)
    rows = conn.execute(
        "SELECT * FROM plans WHERE owner_id = ? AND deleted_at IS NOT NULL ORDER BY deleted_at DESC", (user_id,)
    ).fetchall()
    out = []
    for r in rows:
        item = serialize(conn, r, user_id)
        purge_at = timeutil.parse_iso(r["deleted_at"]) + timedelta(days=config.TRASH_RETENTION_DAYS)
        item["purge_at"] = timeutil.to_iso(purge_at)
        out.append(item)
    return out


def purge(conn, plan_id: str) -> None:
    for row in conn.execute("SELECT stored_name FROM attachments WHERE plan_id = ?", (plan_id,)).fetchall():
        (config.UPLOAD_DIR / row["stored_name"]).unlink(missing_ok=True)
    conn.execute("DELETE FROM plans WHERE id = ?", (plan_id,))


def purge_expired(conn) -> int:
    cutoff = timeutil.to_iso(timeutil.now() - timedelta(days=config.TRASH_RETENTION_DAYS))
    ids = [r["id"] for r in conn.execute("SELECT id FROM plans WHERE deleted_at IS NOT NULL AND deleted_at < ?", (cutoff,))]
    for pid in ids:
        purge(conn, pid)
    return len(ids)


# ---- steps -------------------------------------------------------------------------------

def _guard_steps(plan: sqlite3.Row) -> None:
    if plan["status"] in LOCKED_STATUSES:
        raise ApiError(409, "plan_locked", status=plan["status"])


def add_step(conn, plan: sqlite3.Row, user_id: str, data) -> dict:
    _guard_steps(plan)
    step_id = data.id or new_id()
    existing = conn.execute("SELECT * FROM steps WHERE id = ?", (step_id,)).fetchone()
    if existing is not None:
        if existing["plan_id"] != plan["id"]:
            raise ApiError(409, "id_taken")
        return dict(existing)
    count = conn.execute("SELECT COUNT(*) FROM steps WHERE plan_id = ?", (plan["id"],)).fetchone()[0]
    if count >= config.MAX_STEPS_PER_PLAN:
        raise ApiError(400, "too_many_steps")
    position = data.position if data.position is not None else count
    conn.execute(
        "INSERT INTO steps(id, plan_id, text, position, created_at) VALUES (?,?,?,?,?)",
        (step_id, plan["id"], data.text, position, stamp()),
    )
    _touch(conn, plan["id"])
    return dict(conn.execute("SELECT id, text, status, position, done_at FROM steps WHERE id = ?", (step_id,)).fetchone())


def load_step(conn, step_id: str, user_id: str) -> tuple[sqlite3.Row, sqlite3.Row]:
    row = conn.execute("SELECT * FROM steps WHERE id = ?", (step_id,)).fetchone()
    if row is None:
        raise not_found("step")
    plan = load_for(conn, row["plan_id"], user_id, "edit")
    return row, plan


def update_step(conn, step: sqlite3.Row, plan: sqlite3.Row, user_id: str, data) -> dict:
    _guard_steps(plan)
    sets = {}
    if data.text is not None:
        sets["text"] = data.text
    if data.position is not None:
        sets["position"] = data.position
    if data.status is not None and data.status != step["status"]:
        sets["status"] = data.status
        sets["done_at"] = stamp() if data.status == "done" else None
        log_event(conn, plan["id"], user_id, f"step_{data.status}", text=step["text"])
    if sets:
        conn.execute(f"UPDATE steps SET {', '.join(f'{k} = ?' for k in sets)} WHERE id = ?", (*sets.values(), step["id"]))
        _touch(conn, plan["id"])
    return dict(conn.execute("SELECT id, text, status, position, done_at FROM steps WHERE id = ?", (step["id"],)).fetchone())


def delete_step(conn, step: sqlite3.Row, plan: sqlite3.Row) -> None:
    _guard_steps(plan)
    conn.execute("DELETE FROM steps WHERE id = ?", (step["id"],))
    _touch(conn, plan["id"])


def _touch(conn, plan_id: str) -> None:
    conn.execute("UPDATE plans SET updated_at = ? WHERE id = ?", (stamp(), plan_id))
