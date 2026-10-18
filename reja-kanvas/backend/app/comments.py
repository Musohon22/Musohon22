"""Discussion on a plan between its owner and approvers, with @mentions."""

import re
import uuid

from .errors import ApiError, not_found
from .plans import approval_chain, load_for, notify, stamp

_MENTION = re.compile(r"@([^\s@]+@[^\s@]+\.[^\s@,;:!?]+)")
EDIT_WINDOW_SECONDS = 15 * 60


def participants(conn, plan) -> set[str]:
    """Everyone who can see the plan: owner, approvers, backup, and the board's team."""
    people = {u for u in (plan["owner_id"], *approval_chain(plan), plan["backup_approver_id"]) if u}
    if plan["board_id"]:
        people |= {
            r["user_id"]
            for r in conn.execute(
                "SELECT m.user_id FROM boards b JOIN team_members m ON m.team_id = b.team_id WHERE b.id = ?",
                (plan["board_id"],),
            )
        }
    return people


def _row(conn, comment_id: str):
    return conn.execute(
        """SELECT c.id, c.plan_id, c.user_id, c.body, c.created_at, c.edited_at, u.name AS user_name
           FROM comments c LEFT JOIN users u ON u.id = c.user_id WHERE c.id = ?""",
        (comment_id,),
    ).fetchone()


def load_visible(conn, comment_id: str, user_id: str):
    row = _row(conn, comment_id)
    if row is None:
        raise not_found("comment")
    load_for(conn, row["plan_id"], user_id)
    return row


def list_for(conn, plan, user_id: str | None = None) -> list[dict]:
    from .planning import reactions_for

    items = [
        dict(r)
        for r in conn.execute(
            """SELECT c.id, c.plan_id, c.user_id, c.body, c.created_at, c.edited_at, u.name AS user_name
               FROM comments c LEFT JOIN users u ON u.id = c.user_id WHERE c.plan_id = ? ORDER BY c.created_at""",
            (plan["id"],),
        )
    ]
    reactions = reactions_for(conn, [c["id"] for c in items], user_id or "")
    for c in items:
        c["reactions"] = reactions[c["id"]]
    return items


def add(conn, plan, user_id: str, body: str) -> dict:
    cid = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO comments(id, plan_id, user_id, body, created_at) VALUES (?,?,?,?,?)",
        (cid, plan["id"], user_id, body, stamp()),
    )
    people = participants(conn, plan)
    mentioned: set[str] = set()
    for email in _MENTION.findall(body):
        row = conn.execute("SELECT id FROM users WHERE email = ?", (email.lower(),)).fetchone()
        # Only people who can already see the plan are notified; a mention never grants access.
        if row and row["id"] in people and row["id"] != user_id:
            mentioned.add(row["id"])
            notify(conn, row["id"], plan["id"], "mentioned", title=plan["title"])
    # Plain comments notify the people directly on the plan; the wider team only when mentioned.
    direct = {u for u in (plan["owner_id"], *approval_chain(plan), plan["backup_approver_id"]) if u}
    for uid in direct - mentioned - {user_id}:
        notify(conn, uid, plan["id"], "commented", title=plan["title"])
    from . import webhooks

    webhooks.enqueue(conn, plan["owner_id"], "comment.created", {"plan_id": plan["id"], "plan_title": plan["title"], "body": body})
    return {**dict(_row(conn, cid)), "reactions": []}


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
