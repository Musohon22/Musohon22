"""Duplicate, archive and personal templates."""

import json
import uuid
from datetime import timedelta

from . import timeutil
from .errors import ApiError
from .plans import create, load, log_event, serialize, stamp
from .schemas import PlanCreate

MAX_USER_TEMPLATES = 50


def _copy_fields(conn, plan) -> dict:
    steps = [
        r["text"]
        for r in conn.execute(
            "SELECT text FROM steps WHERE plan_id = ? AND status != 'cancelled' ORDER BY position", (plan["id"],)
        )
    ]
    return {
        "title": plan["title"], "body_html": plan["body_html"], "tag": plan["tag"], "color": plan["color"],
        "goal": plan["goal"], "done_criteria": plan["done_criteria"], "require_proof": bool(plan["require_proof"]),
        "priority": plan["priority"], "remind_minutes": plan["remind_minutes"],
        "recurrence": json.loads(plan["recurrence"]) if plan["recurrence"] else None, "steps": steps,
    }


def duplicate(conn, plan, user_id: str) -> dict:
    fields = _copy_fields(conn, plan)
    fields["title"] = fields["title"][:196] + " (2)" if len(fields["title"]) > 196 else fields["title"] + " (2)"
    out = create(conn, user_id, PlanCreate(**fields, x=plan["x"] + 40, y=plan["y"] + 40, due_at=plan["due_at"],
                                          approver_id=plan["approver_id"], backup_approver_id=plan["backup_approver_id"]))
    log_event(conn, out["id"], user_id, "duplicated", source=plan["title"])
    return out


def archive(conn, plan, user_id: str, on: bool) -> dict:
    if on and plan["status"] not in ("done", "cancelled"):
        raise ApiError(409, "archive_open_plan")
    conn.execute("UPDATE plans SET archived_at = ?, updated_at = ? WHERE id = ?", (stamp() if on else None, stamp(), plan["id"]))
    log_event(conn, plan["id"], user_id, "archived" if on else "unarchived")
    return serialize(conn, load(conn, plan["id"]), user_id, detail=True)


def archive_finished(conn, user_id: str, older_than_days: int = 7) -> int:
    cutoff = timeutil.to_iso(timeutil.now() - timedelta(days=older_than_days))
    return conn.execute(
        """UPDATE plans SET archived_at = ? WHERE owner_id = ? AND deleted_at IS NULL AND archived_at IS NULL
           AND status IN ('done', 'cancelled') AND updated_at < ?""",
        (stamp(), user_id, cutoff),
    ).rowcount


# ---- personal templates ----------------------------------------------------------------------

def save_template(conn, plan, user_id: str, name: str) -> dict:
    count = conn.execute("SELECT COUNT(*) FROM user_templates WHERE owner_id = ?", (user_id,)).fetchone()[0]
    if count >= MAX_USER_TEMPLATES:
        raise ApiError(400, "too_many_templates", limit=MAX_USER_TEMPLATES)
    tid = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO user_templates(id, owner_id, name, data, created_at) VALUES (?,?,?,?,?)",
        (tid, user_id, name, json.dumps(_copy_fields(conn, plan), ensure_ascii=False), stamp()),
    )
    return {"key": f"u:{tid}", "name": name, "count": 1}


def list_templates(conn, user_id: str) -> list[dict]:
    return [
        {"key": f"u:{r['id']}", "name": r["name"], "count": 1}
        for r in conn.execute("SELECT id, name FROM user_templates WHERE owner_id = ? ORDER BY created_at DESC", (user_id,))
    ]


def _load_template(conn, user_id: str, key: str):
    row = conn.execute("SELECT * FROM user_templates WHERE id = ? AND owner_id = ?", (key.removeprefix("u:"), user_id)).fetchone()
    if row is None:
        raise ApiError(404, "template_not_found")
    return row


def apply_template(conn, user, key: str, x: float = 40, y: float = 90) -> list[dict]:
    fields = json.loads(_load_template(conn, user["id"], key)["data"])
    return [create(conn, user["id"], PlanCreate(**fields, x=x, y=y))]


def delete_template(conn, user_id: str, key: str) -> None:
    row = _load_template(conn, user_id, key)
    conn.execute("DELETE FROM user_templates WHERE id = ?", (row["id"],))
