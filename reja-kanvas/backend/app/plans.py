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
STEP_COLUMNS = "id, text, status, position, done_at, due_at, assignee_id"
TRACKED = (
    "title", "body_html", "tag", "color", "due_at", "remind_minutes", "goal",
    "done_criteria", "require_proof", "approver_id", "backup_approver_id", "priority", "recurrence",
    "parent_id", "goal_id", "duration_minutes", "approval_chain",
)
MAX_DEPTH = 3
POSITION = ("x", "y")
# Once submitted or confirmed, the content is frozen until the plan is reopened.
LOCKED_STATUSES = ("pending_approval", "done")
EDITABLE_WHEN_LOCKED = {"color", "tag", "x", "y", "priority", "goal_id", "duration_minutes"}
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
    from . import webhooks  # local import: webhooks imports this module

    webhooks.on_event(conn, plan_id, kind)


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


def approval_chain(plan: sqlite3.Row) -> list[str]:
    """Approvers in order: the main approver, then any further stages."""
    if not plan["approver_id"]:
        return []
    return [plan["approver_id"], *json.loads(plan["approval_chain"] or "[]")]


def current_approver(plan: sqlite3.Row) -> str | None:
    chain = approval_chain(plan)
    stage = plan["approval_stage"] or 0
    return chain[stage] if plan["status"] == "pending_approval" and stage < len(chain) else None


def team_role(conn, board_id: str | None, user_id: str) -> str | None:
    """The user's role in the team that owns this board, if it is a team board."""
    if not board_id:
        return None
    row = conn.execute(
        """SELECT m.role FROM boards b JOIN team_members m ON m.team_id = b.team_id
           WHERE b.id = ? AND m.user_id = ?""",
        (board_id, user_id),
    ).fetchone()
    return row["role"] if row else None


EDIT_TEAM_ROLES = ("owner", "admin", "member")


def role_of(conn, plan: sqlite3.Row, user_id: str) -> str | None:
    if plan["owner_id"] == user_id:
        return "owner"
    if user_id in approval_chain(plan):
        return "approver"
    if plan["backup_approver_id"] == user_id:
        return "backup"
    role = team_role(conn, plan["board_id"], user_id)
    if role:
        return "team" if role in EDIT_TEAM_ROLES else "viewer"
    return None


def can_edit_role(role: str | None) -> bool:
    return role in ("owner", "team")


def can_decide(plan: sqlite3.Row, user_id: str) -> bool:
    """The approver of the current stage decides; the backup approver only once the request has
    been escalated."""
    if plan["status"] != "pending_approval":
        return False
    if current_approver(plan) == user_id:
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
            "archived_at", "tracked_seconds", "timer_started_at", "parent_id", "duration_minutes",
            "goal_id", "board_id", "approval_stage",
        )
    }
    data["approval_chain"] = json.loads(plan["approval_chain"] or "[]")
    data["require_proof"] = bool(plan["require_proof"])
    data["recurrence"] = json.loads(plan["recurrence"]) if plan["recurrence"] else None
    data["blocked_by"] = blocked_by if blocked_by is not None else blockers_map(conn, [plan["id"]])[plan["id"]]
    data["progress"] = progress or progress_map(conn, [plan["id"]])[plan["id"]]
    if user_id:
        data["my_role"] = role_of(conn, plan, user_id)
        data["can_decide"] = can_decide(plan, user_id)
    if detail:
        data["body_html"] = plan["body_html"]
        data["steps"] = [
            dict(r)
            for r in conn.execute(
                f"SELECT {STEP_COLUMNS} FROM steps WHERE plan_id = ? ORDER BY position, created_at",
                (plan["id"],),
            )
        ]
        data["attachments"] = [
            dict(r)
            for r in conn.execute(
                "SELECT id, filename, mime, size, created_at, inline FROM attachments WHERE plan_id = ? ORDER BY created_at",
                (plan["id"],),
            )
        ]
        for a in data["attachments"]:
            a["inline"] = bool(a["inline"])
        data["chain"] = [user_brief(conn, uid) for uid in approval_chain(plan)]
        data["current_approver"] = user_brief(conn, current_approver(plan))
        data["children"] = [
            {**dict(r), "progress": None}
            for r in conn.execute(
                "SELECT id, title, status, due_at FROM plans WHERE parent_id = ? AND deleted_at IS NULL ORDER BY COALESCE(due_at, '9999'), created_at",
                (plan["id"],),
            )
        ]
        data["parent"] = (
            dict(conn.execute("SELECT id, title FROM plans WHERE id = ?", (plan["parent_id"],)).fetchone() or {})
            if plan["parent_id"] else None
        )
        data["signatures"] = [
            dict(r)
            for r in conn.execute(
                """SELECT s.role, s.image, s.signed_at, u.name AS user_name FROM signatures s
                   LEFT JOIN users u ON u.id = s.user_id WHERE s.plan_id = ? ORDER BY s.id""",
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
    """need: 'view' (owner, approvers, team) or 'edit' (owner, or a member of the plan's team
    board). Strangers get 404, never 403, so plan ids cannot be probed."""
    plan = load(conn, plan_id, include_deleted=include_deleted)
    role = role_of(conn, plan, user_id)
    if role is None:
        raise not_found()
    if need == "edit" and not can_edit_role(role):
        raise forbidden("owner_only")
    return plan


def _check_people(conn, owner_id: str, approver_id: str | None, backup_id: str | None, chain: list[str] | None = None) -> None:
    chain = chain or []
    if chain and not approver_id:
        raise ApiError(400, "chain_without_approver")
    if len(set(chain)) != len(chain) or (approver_id and approver_id in chain):
        raise ApiError(400, "chain_duplicate")
    for uid in (approver_id, backup_id, *chain):
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


def board_access(conn, board_id: str | None, user_id: str) -> str | None:
    """'owner' for the user's personal boards, the team role for team boards, else None."""
    if board_id is None:
        return "owner"
    row = conn.execute("SELECT owner_id, team_id FROM boards WHERE id = ?", (board_id,)).fetchone()
    if row is None:
        return None
    if row["owner_id"]:
        return "owner" if row["owner_id"] == user_id else None
    return team_role(conn, board_id, user_id)


def _check_refs(conn, user_id: str, board_id: str | None, plan_id: str | None, parent_id: str | None, goal_id: str | None) -> None:
    if parent_id:
        parent = conn.execute("SELECT id, board_id, parent_id, owner_id FROM plans WHERE id = ? AND deleted_at IS NULL", (parent_id,)).fetchone()
        if parent is None or parent["board_id"] != board_id or (board_id is None and parent["owner_id"] != user_id):
            raise ApiError(400, "parent_not_found")
        # walk up: no cycles, limited depth
        depth, node = 1, parent
        while node is not None and node["parent_id"]:
            if node["parent_id"] == plan_id or depth >= MAX_DEPTH:
                raise ApiError(400, "parent_cycle" if node["parent_id"] == plan_id else "too_deep")
            node = conn.execute("SELECT id, parent_id FROM plans WHERE id = ?", (node["parent_id"],)).fetchone()
            depth += 1
        if parent_id == plan_id:
            raise ApiError(400, "parent_cycle")
    if goal_id and conn.execute("SELECT 1 FROM goals WHERE id = ? AND owner_id = ?", (goal_id, user_id)).fetchone() is None:
        raise ApiError(400, "goal_not_found")


def list_for_owner(conn, user_id: str, q: str | None = None, *, archived: bool = False) -> list[dict]:
    """Everything on the user's canvases: their own plans plus every plan on their teams' boards."""
    sql = """SELECT * FROM plans WHERE deleted_at IS NULL AND (owner_id = ? OR board_id IN (
             SELECT b.id FROM boards b JOIN team_members m ON m.team_id = b.team_id WHERE m.user_id = ?))"""
    sql += " AND archived_at IS NOT NULL" if archived else " AND archived_at IS NULL"
    args: list = [user_id, user_id]
    if q:
        sql += " AND search_key LIKE ?"
        args.append("%" + normalize(q).replace("%", "").replace("_", "") + "%")
    sql += f" ORDER BY COALESCE(due_at, '9999'), {PRIORITY_ORDER}, created_at"
    rows = conn.execute(sql, args).fetchall()
    ids = [r["id"] for r in rows]
    prog = progress_map(conn, ids)
    deps = blockers_map(conn, ids)
    out = []
    names: dict[str, dict | None] = {}
    for r in rows:
        item = serialize(conn, r, user_id, progress=prog[r["id"]], blocked_by=deps[r["id"]])
        if r["owner_id"] != user_id:
            if r["owner_id"] not in names:
                names[r["owner_id"]] = user_brief(conn, r["owner_id"])
            item["owner"] = names[r["owner_id"]]
        out.append(item)
    return out


def list_awaiting_me(conn, user_id: str) -> list[dict]:
    candidates = conn.execute(
        """SELECT * FROM plans WHERE deleted_at IS NULL AND status = 'pending_approval'
           AND (approver_id = ? OR backup_approver_id = ? OR approval_chain LIKE ?)
           ORDER BY submitted_at""",
        (user_id, user_id, f'%"{user_id}"%'),
    ).fetchall()
    rows = [r for r in candidates if can_decide(r, user_id)]
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
    if board_access(conn, data.board_id, user_id) not in ("owner", "admin", "member"):
        raise ApiError(404, "board_not_found")
    _check_people(conn, user_id, data.approver_id, data.backup_approver_id, data.approval_chain)
    _check_refs(conn, user_id, data.board_id, plan_id, data.parent_id, data.goal_id)
    body = sanitize_html(data.body_html)
    now = stamp()
    conn.execute(
        """INSERT INTO plans (id, owner_id, title, body_html, tag, color, x, y, due_at, remind_minutes,
           goal, done_criteria, require_proof, approver_id, backup_approver_id, priority, recurrence,
           parent_id, goal_id, board_id, duration_minutes, approval_chain,
           search_key, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            plan_id, user_id, data.title, body, data.tag, data.color, data.x, data.y,
            timeutil.to_iso(data.due_at), data.remind_minutes, data.goal, data.done_criteria,
            int(data.require_proof), data.approver_id, data.backup_approver_id, data.priority,
            recurrence_json(data.recurrence), data.parent_id, data.goal_id, data.board_id,
            data.duration_minutes, json.dumps(data.approval_chain),
            _search_key(data.title, body, data.tag, data.goal), now, now,
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
    if field == "approval_chain":
        return json.dumps(value or [])
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

    if {"approver_id", "backup_approver_id", "approval_chain"} & changed.keys():
        _check_people(
            conn, plan["owner_id"],
            changed.get("approver_id", plan["approver_id"]),
            changed.get("backup_approver_id", plan["backup_approver_id"]),
            json.loads(changed.get("approval_chain", plan["approval_chain"]) or "[]"),
        )
    if {"parent_id", "goal_id"} & changed.keys():
        _check_refs(conn, plan["owner_id"], plan["board_id"], plan["id"], changed.get("parent_id"), changed.get("goal_id"))

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
    return dict(conn.execute(f"SELECT {STEP_COLUMNS} FROM steps WHERE id = ?", (step_id,)).fetchone())


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
    fields = data.model_fields_set
    if "due_at" in fields:
        sets["due_at"] = timeutil.to_iso(data.due_at)
    if "assignee_id" in fields and data.assignee_id != step["assignee_id"]:
        if data.assignee_id and data.assignee_id not in step_assignees(conn, plan):
            raise ApiError(400, "assignee_not_member")
        sets["assignee_id"] = data.assignee_id
        if data.assignee_id and data.assignee_id != user_id:
            notify(conn, data.assignee_id, plan["id"], "step_assigned", title=plan["title"], step=step["text"])
    if sets:
        conn.execute(f"UPDATE steps SET {', '.join(f'{k} = ?' for k in sets)} WHERE id = ?", (*sets.values(), step["id"]))
        _touch(conn, plan["id"])
    return dict(conn.execute(f"SELECT {STEP_COLUMNS} FROM steps WHERE id = ?", (step["id"],)).fetchone())


def step_assignees(conn, plan: sqlite3.Row) -> set[str]:
    """Who a step can be given to: the plan's owner and, on a team board, the team's editors."""
    people = {plan["owner_id"]}
    if plan["board_id"]:
        people |= {
            r["user_id"]
            for r in conn.execute(
                """SELECT m.user_id FROM boards b JOIN team_members m ON m.team_id = b.team_id
                   WHERE b.id = ? AND m.role != 'viewer'""",
                (plan["board_id"],),
            )
        }
    return people


def reorder_steps(conn, plan: sqlite3.Row, ids: list[str]) -> list[dict]:
    _guard_steps(plan)
    existing = [r["id"] for r in conn.execute("SELECT id FROM steps WHERE plan_id = ?", (plan["id"],))]
    if sorted(existing) != sorted(ids):
        raise ApiError(400, "step_order_mismatch")
    for pos, sid in enumerate(ids):
        conn.execute("UPDATE steps SET position = ? WHERE id = ?", (pos, sid))
    _touch(conn, plan["id"])
    return [dict(r) for r in conn.execute(f"SELECT {STEP_COLUMNS} FROM steps WHERE plan_id = ? ORDER BY position", (plan["id"],))]


def delete_step(conn, step: sqlite3.Row, plan: sqlite3.Row) -> None:
    _guard_steps(plan)
    conn.execute("DELETE FROM steps WHERE id = ?", (step["id"],))
    _touch(conn, plan["id"])


def _touch(conn, plan_id: str) -> None:
    conn.execute("UPDATE plans SET updated_at = ? WHERE id = ?", (stamp(), plan_id))
