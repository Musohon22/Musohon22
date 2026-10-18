"""Discussion on a plan between its owner and approvers, with @mentions."""

import re
import uuid

from .errors import ApiError, not_found
from .plans import load_for, notify, stamp

_MENTION = re.compile(r"@([^\s@]+@[^\s@]+\.[^\s@,;:!?]+)")
EDIT_WINDOW_SECONDS = 15 * 60


def participants(plan) -> set[str]:
    return {u for u in (plan["owner_id"], plan["approver_id"], plan["backup_approver_id"]) if u}


def _row(conn, comment_id: str):
    return conn.execute(
        """SELECT c.id, c.plan_id, c.user_id, c.body, c.created_at, c.edited_at, u.name AS user_name
           FROM comments c LEFT JOIN users u ON u.id = c.user_id WHERE c.id = ?""",
        (comment_id,),
    ).fetchone()


def list_for(conn, plan) -> list[dict]:
    return [
        dict(r)
        for r in conn.execute(
            """SELECT c.id, c.plan_id, c.user_id, c.body, c.created_at, c.edited_at, u.name AS user_name
               FROM comments c LEFT JOIN users u ON u.id = c.user_id WHERE c.plan_id = ? ORDER BY c.created_at""",
            (plan["id"],),
        )
    ]


def add(conn, plan, user_id: str, body: str) -> dict:
    cid = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO comments(id, plan_id, user_id, body, created_at) VALUES (?,?,?,?,?)",
        (cid, plan["id"], user_id, body, stamp()),
    )
    people = participants(plan)
    mentioned: set[str] = set()
    for email in _MENTION.findall(body):
        row = conn.execute("SELECT id FROM users WHERE email = ?", (email.lower(),)).fetchone()
        # Only people who can already see the plan are notified; a mention never grants access.
        if row and row["id"] in people and row["id"] != user_id:
            mentioned.add(row["id"])
            notify(conn, row["id"], plan["id"], "mentioned", title=plan["title"])
    for uid in people - mentioned - {user_id}:
        notify(conn, uid, plan["id"], "commented", title=plan["title"])
    return dict(_row(conn, cid))


def load_own(conn, comment_id: str, user_id: str):
    row = _row(conn, comment_id)
    if row is None:
        raise not_found("comment")
    load_for(conn, row["plan_id"], user_id)  # must still see the plan
    if row["user_id"] != user_id:
        raise ApiError(403, "not_author")
    return row


def edit(conn, row, body: str) -> dict:
    from . import timeutil

    age = (timeutil.now() - timeutil.parse_iso(row["created_at"])).total_seconds()
    if age > EDIT_WINDOW_SECONDS:
        raise ApiError(409, "edit_window_passed")
    conn.execute("UPDATE comments SET body = ?, edited_at = ? WHERE id = ?", (body, stamp(), row["id"]))
    return dict(_row(conn, row["id"]))


def delete(conn, row) -> None:
    conn.execute("DELETE FROM comments WHERE id = ?", (row["id"],))
