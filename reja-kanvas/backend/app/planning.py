"""Goals, saved filters, steps assigned to me, manual time entries and comment reactions."""

import json
import uuid
from datetime import timedelta

from . import timeutil
from .errors import ApiError, forbidden, not_found
from .plans import stamp

MAX_GOALS = 100
MAX_FILTERS = 30


# ---- goals -----------------------------------------------------------------------------------

def _goal_dict(conn, row) -> dict:
    counts = conn.execute(
        """SELECT COUNT(*) AS total, SUM(CASE WHEN status = 'done' THEN 1 ELSE 0 END) AS done
           FROM plans WHERE goal_id = ? AND deleted_at IS NULL AND status != 'cancelled'""",
        (row["id"],),
    ).fetchone()
    total, done = counts["total"] or 0, counts["done"] or 0
    return {
        **{k: row[k] for k in ("id", "title", "description", "target_date", "color", "archived_at", "created_at")},
        "plans_total": total,
        "plans_done": done,
        "progress": round(done / total, 3) if total else 0,
    }


def list_goals(conn, user_id: str, archived: bool = False) -> list[dict]:
    rows = conn.execute(
        f"SELECT * FROM goals WHERE owner_id = ? AND archived_at IS {'NOT ' if archived else ''}NULL ORDER BY COALESCE(target_date, '9999'), created_at",
        (user_id,),
    ).fetchall()
    return [_goal_dict(conn, r) for r in rows]


def create_goal(conn, user_id: str, data) -> dict:
    if conn.execute("SELECT COUNT(*) FROM goals WHERE owner_id = ?", (user_id,)).fetchone()[0] >= MAX_GOALS:
        raise ApiError(400, "too_many_goals", limit=MAX_GOALS)
    gid = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO goals(id, owner_id, title, description, target_date, color, created_at) VALUES (?,?,?,?,?,?,?)",
        (gid, user_id, data.title, data.description, data.target_date.isoformat() if data.target_date else None, data.color, stamp()),
    )
    return _goal_dict(conn, conn.execute("SELECT * FROM goals WHERE id = ?", (gid,)).fetchone())


def _own_goal(conn, goal_id: str, user_id: str):
    row = conn.execute("SELECT * FROM goals WHERE id = ? AND owner_id = ?", (goal_id, user_id)).fetchone()
    if row is None:
        raise not_found("goal")
    return row


def update_goal(conn, goal_id: str, user_id: str, data) -> dict:
    row = _own_goal(conn, goal_id, user_id)
    sets = {}
    fields = data.model_fields_set
    for key in ("title", "description", "color"):
        if key in fields and getattr(data, key) is not None:
            sets[key] = getattr(data, key)
    if "target_date" in fields:
        sets["target_date"] = data.target_date.isoformat() if data.target_date else None
    if "archived" in fields:
        sets["archived_at"] = stamp() if data.archived else None
    if sets:
        conn.execute(f"UPDATE goals SET {', '.join(f'{k} = ?' for k in sets)} WHERE id = ?", (*sets.values(), row["id"]))
    return _goal_dict(conn, conn.execute("SELECT * FROM goals WHERE id = ?", (row["id"],)).fetchone())


def delete_goal(conn, goal_id: str, user_id: str) -> None:
    row = _own_goal(conn, goal_id, user_id)
    conn.execute("UPDATE plans SET goal_id = NULL WHERE goal_id = ?", (row["id"],))
    conn.execute("DELETE FROM goals WHERE id = ?", (row["id"],))


# ---- saved filters --------------------------------------------------------------------------

def list_filters(conn, user_id: str) -> list[dict]:
    return [
        {"id": r["id"], "name": r["name"], "query": json.loads(r["query"])}
        for r in conn.execute("SELECT * FROM saved_filters WHERE user_id = ? ORDER BY created_at", (user_id,))
    ]


def create_filter(conn, user_id: str, data) -> dict:
    if conn.execute("SELECT COUNT(*) FROM saved_filters WHERE user_id = ?", (user_id,)).fetchone()[0] >= MAX_FILTERS:
        raise ApiError(400, "too_many_filters", limit=MAX_FILTERS)
    fid = str(uuid.uuid4())
    query = data.query.model_dump(mode="json")
    conn.execute(
        "INSERT INTO saved_filters(id, user_id, name, query, created_at) VALUES (?,?,?,?,?)",
        (fid, user_id, data.name, json.dumps(query, ensure_ascii=False), stamp()),
    )
    return {"id": fid, "name": data.name, "query": query}


def delete_filter(conn, filter_id: str, user_id: str) -> None:
    if not conn.execute("DELETE FROM saved_filters WHERE id = ? AND user_id = ?", (filter_id, user_id)).rowcount:
        raise not_found("filter")


# ---- steps assigned to me ---------------------------------------------------------------------

def my_steps(conn, user_id: str) -> list[dict]:
    return [
        dict(r)
        for r in conn.execute(
            """SELECT s.id, s.text, s.status, s.due_at, p.id AS plan_id, p.title AS plan_title FROM steps s
               JOIN plans p ON p.id = s.plan_id WHERE s.assignee_id = ? AND s.status = 'todo'
               AND p.deleted_at IS NULL AND p.status IN ('active', 'returned')
               ORDER BY COALESCE(s.due_at, '9999'), p.title""",
            (user_id,),
        )
    ]


# ---- manual time entries --------------------------------------------------------------------

def list_time(conn, plan) -> list[dict]:
    return [
        dict(r)
        for r in conn.execute(
            """SELECT t.id, t.started_at, t.ended_at, t.seconds, t.note, t.manual, u.name AS user_name
               FROM time_entries t LEFT JOIN users u ON u.id = t.user_id WHERE t.plan_id = ? ORDER BY t.started_at DESC""",
            (plan["id"],),
        )
    ]


def _recount(conn, plan_id: str) -> None:
    conn.execute(
        "UPDATE plans SET tracked_seconds = (SELECT COALESCE(SUM(seconds), 0) FROM time_entries WHERE plan_id = ?) WHERE id = ?",
        (plan_id, plan_id),
    )


def add_time(conn, plan, user_id: str, data) -> dict:
    if data.started_at > timeutil.now():
        raise ApiError(400, "time_in_future")
    seconds = data.minutes * 60
    ended = data.started_at + timedelta(seconds=seconds)
    conn.execute(
        "INSERT INTO time_entries(plan_id, user_id, started_at, ended_at, seconds, note, manual) VALUES (?,?,?,?,?,?,1)",
        (plan["id"], user_id, timeutil.to_iso(data.started_at), timeutil.to_iso(ended), seconds, data.note),
    )
    _recount(conn, plan["id"])
    return {"entries": list_time(conn, plan)}


def delete_time(conn, entry_id: int, user_id: str) -> str:
    row = conn.execute("SELECT * FROM time_entries WHERE id = ?", (entry_id,)).fetchone()
    if row is None:
        raise not_found("time_entry")
    if row["user_id"] != user_id:
        raise forbidden("not_author")
    conn.execute("DELETE FROM time_entries WHERE id = ?", (entry_id,))
    _recount(conn, row["plan_id"])
    return row["plan_id"]


# ---- reactions -------------------------------------------------------------------------------

def toggle_reaction(conn, comment_id: str, user_id: str, emoji: str) -> dict:
    exists = conn.execute(
        "SELECT 1 FROM comment_reactions WHERE comment_id = ? AND user_id = ? AND emoji = ?", (comment_id, user_id, emoji)
    ).fetchone()
    if exists:
        conn.execute("DELETE FROM comment_reactions WHERE comment_id = ? AND user_id = ? AND emoji = ?", (comment_id, user_id, emoji))
    else:
        conn.execute("INSERT INTO comment_reactions(comment_id, user_id, emoji) VALUES (?,?,?)", (comment_id, user_id, emoji))
    return reactions_for(conn, [comment_id], user_id)[comment_id]


def reactions_for(conn, comment_ids: list[str], user_id: str) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {cid: [] for cid in comment_ids}
    if not comment_ids:
        return out
    marks = ",".join("?" * len(comment_ids))
    for r in conn.execute(
        f"""SELECT comment_id, emoji, COUNT(*) AS n, SUM(CASE WHEN user_id = ? THEN 1 ELSE 0 END) AS mine
            FROM comment_reactions WHERE comment_id IN ({marks}) GROUP BY comment_id, emoji ORDER BY MIN(rowid)""",
        (user_id, *comment_ids),
    ):
        out[r["comment_id"]].append({"emoji": r["emoji"], "count": r["n"], "mine": bool(r["mine"])})
    return out
