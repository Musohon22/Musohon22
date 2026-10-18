"""Teams, boards and free canvas items (notes, frames).

A board is a canvas. Every user has an implicit personal board (board_id NULL) and may create
more; team boards are shared by every member of the team. Roles: owner > admin > member > viewer.
Viewers see team boards; members and above also edit the plans on them."""

import uuid

from .errors import ApiError, forbidden, not_found
from .plans import board_access, load, log_event, notify, serialize, stamp, team_role, user_brief

ROLE_RANK = {"viewer": 0, "member": 1, "admin": 2, "owner": 3}
MAX_TEAMS = 20
MAX_MEMBERS = 200
MAX_BOARDS = 50


def _team_row(conn, team_id: str, user_id: str, need: str = "viewer"):
    try:
        team_id = str(uuid.UUID(team_id))
    except ValueError:
        raise not_found("team")
    row = conn.execute(
        """SELECT t.*, m.role FROM teams t JOIN team_members m ON m.team_id = t.id
           WHERE t.id = ? AND m.user_id = ?""",
        (team_id, user_id),
    ).fetchone()
    if row is None:
        raise not_found("team")
    if ROLE_RANK[row["role"]] < ROLE_RANK[need]:
        raise forbidden("team_role_required")
    return row


def _team_dict(conn, team_id: str) -> dict:
    team = conn.execute("SELECT id, name, created_at FROM teams WHERE id = ?", (team_id,)).fetchone()
    members = [
        dict(r)
        for r in conn.execute(
            """SELECT u.id, u.name, u.email, m.role, m.joined_at FROM team_members m JOIN users u ON u.id = m.user_id
               WHERE m.team_id = ? ORDER BY CASE m.role WHEN 'owner' THEN 0 WHEN 'admin' THEN 1 WHEN 'member' THEN 2 ELSE 3 END, u.name""",
            (team_id,),
        )
    ]
    return {**dict(team), "members": members}


def list_teams(conn, user_id: str) -> list[dict]:
    rows = conn.execute(
        "SELECT t.id, m.role FROM teams t JOIN team_members m ON m.team_id = t.id WHERE m.user_id = ? ORDER BY t.name",
        (user_id,),
    ).fetchall()
    return [{**_team_dict(conn, r["id"]), "my_role": r["role"]} for r in rows]


def create_team(conn, user_id: str, name: str) -> dict:
    count = conn.execute("SELECT COUNT(*) FROM team_members WHERE user_id = ?", (user_id,)).fetchone()[0]
    if count >= MAX_TEAMS:
        raise ApiError(400, "too_many_teams", limit=MAX_TEAMS)
    tid = str(uuid.uuid4())
    now = stamp()
    conn.execute("INSERT INTO teams(id, name, created_by, created_at) VALUES (?,?,?,?)", (tid, name, user_id, now))
    conn.execute("INSERT INTO team_members(team_id, user_id, role, joined_at) VALUES (?,?,?,?)", (tid, user_id, "owner", now))
    conn.execute("INSERT INTO boards(id, team_id, name, created_at) VALUES (?,?,?,?)", (str(uuid.uuid4()), tid, name, now))
    return {**_team_dict(conn, tid), "my_role": "owner"}


def rename_team(conn, team_id: str, user_id: str, name: str) -> dict:
    team = _team_row(conn, team_id, user_id, "admin")
    conn.execute("UPDATE teams SET name = ? WHERE id = ?", (name, team["id"]))
    return {**_team_dict(conn, team["id"]), "my_role": team["role"]}


def add_member(conn, team_id: str, user_id: str, email: str, role: str) -> dict:
    team = _team_row(conn, team_id, user_id, "admin")
    target = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
    if target is None:
        raise ApiError(404, "user_not_found")
    if conn.execute("SELECT 1 FROM team_members WHERE team_id = ? AND user_id = ?", (team["id"], target["id"])).fetchone():
        raise ApiError(409, "already_member")
    count = conn.execute("SELECT COUNT(*) FROM team_members WHERE team_id = ?", (team["id"],)).fetchone()[0]
    if count >= MAX_MEMBERS:
        raise ApiError(400, "too_many_members", limit=MAX_MEMBERS)
    conn.execute(
        "INSERT INTO team_members(team_id, user_id, role, joined_at) VALUES (?,?,?,?)",
        (team["id"], target["id"], role, stamp()),
    )
    notify(conn, target["id"], None, "team_added", team=team["name"])
    return {**_team_dict(conn, team["id"]), "my_role": team["role"]}


def set_role(conn, team_id: str, user_id: str, member_id: str, role: str) -> dict:
    team = _team_row(conn, team_id, user_id, "admin")
    current = conn.execute("SELECT role FROM team_members WHERE team_id = ? AND user_id = ?", (team["id"], member_id)).fetchone()
    if current is None:
        raise not_found("member")
    # Only the owner hands out or takes away ownership and admin rights.
    if (role in ("owner", "admin") or current["role"] in ("owner", "admin")) and team["role"] != "owner":
        raise forbidden("team_role_required")
    if role == "owner":
        conn.execute("UPDATE team_members SET role = 'admin' WHERE team_id = ? AND user_id = ?", (team["id"], user_id))
    elif current["role"] == "owner":
        raise ApiError(400, "team_needs_owner")
    conn.execute("UPDATE team_members SET role = ? WHERE team_id = ? AND user_id = ?", (role, team["id"], member_id))
    return {**_team_dict(conn, team["id"]), "my_role": "admin" if role == "owner" else team["role"]}


def remove_member(conn, team_id: str, user_id: str, member_id: str) -> None:
    leaving_self = member_id == user_id
    team = _team_row(conn, team_id, user_id, "viewer" if leaving_self else "admin")
    target = conn.execute("SELECT role FROM team_members WHERE team_id = ? AND user_id = ?", (team["id"], member_id)).fetchone()
    if target is None:
        raise not_found("member")
    if target["role"] == "owner":
        raise ApiError(400, "team_needs_owner")
    if target["role"] == "admin" and not leaving_self and team["role"] != "owner":
        raise forbidden("team_role_required")
    conn.execute("DELETE FROM team_members WHERE team_id = ? AND user_id = ?", (team["id"], member_id))
    # Their plans on this team's boards go back to their own canvas rather than vanish.
    conn.execute(
        """UPDATE plans SET board_id = NULL WHERE owner_id = ? AND board_id IN (SELECT id FROM boards WHERE team_id = ?)""",
        (member_id, team["id"]),
    )


def delete_team(conn, team_id: str, user_id: str) -> None:
    team = _team_row(conn, team_id, user_id, "owner")
    conn.execute("UPDATE plans SET board_id = NULL WHERE board_id IN (SELECT id FROM boards WHERE team_id = ?)", (team["id"],))
    conn.execute("DELETE FROM canvas_items WHERE board_id IN (SELECT id FROM boards WHERE team_id = ?)", (team["id"],))
    conn.execute("DELETE FROM teams WHERE id = ?", (team["id"],))


def colleagues(conn, user_id: str) -> list[dict]:
    """Everyone sharing a team with the user: offered first when picking approvers or assignees."""
    return [
        dict(r)
        for r in conn.execute(
            """SELECT DISTINCT u.id, u.name, u.email FROM team_members me
               JOIN team_members other ON other.team_id = me.team_id JOIN users u ON u.id = other.user_id
               WHERE me.user_id = ? AND other.user_id != ? ORDER BY u.name""",
            (user_id, user_id),
        )
    ]


# ---- boards ------------------------------------------------------------------------------------

def list_boards(conn, user_id: str) -> list[dict]:
    personal = [{"id": None, "name": None, "team_id": None, "team_name": None, "role": "owner"}]
    personal += [
        {**dict(r), "team_name": None, "role": "owner"}
        for r in conn.execute("SELECT id, name, team_id FROM boards WHERE owner_id = ? ORDER BY created_at", (user_id,))
    ]
    team = [
        dict(r)
        for r in conn.execute(
            """SELECT b.id, b.name, b.team_id, t.name AS team_name, m.role FROM boards b
               JOIN teams t ON t.id = b.team_id JOIN team_members m ON m.team_id = b.team_id
               WHERE m.user_id = ? ORDER BY t.name, b.created_at""",
            (user_id,),
        )
    ]
    return personal + team


def create_board(conn, user_id: str, name: str, team_id: str | None) -> dict:
    if team_id:
        _team_row(conn, team_id, user_id, "admin")
        count = conn.execute("SELECT COUNT(*) FROM boards WHERE team_id = ?", (team_id,)).fetchone()[0]
    else:
        count = conn.execute("SELECT COUNT(*) FROM boards WHERE owner_id = ?", (user_id,)).fetchone()[0]
    if count >= MAX_BOARDS:
        raise ApiError(400, "too_many_boards", limit=MAX_BOARDS)
    bid = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO boards(id, owner_id, team_id, name, created_at) VALUES (?,?,?,?,?)",
        (bid, None if team_id else user_id, team_id, name, stamp()),
    )
    return next(b for b in list_boards(conn, user_id) if b["id"] == bid)


def _board_admin(conn, board_id: str, user_id: str):
    row = conn.execute("SELECT * FROM boards WHERE id = ?", (board_id,)).fetchone()
    if row is None:
        raise not_found("board")
    if row["owner_id"]:
        if row["owner_id"] != user_id:
            raise not_found("board")
    else:
        _team_row(conn, row["team_id"], user_id, "admin")
    return row


def rename_board(conn, board_id: str, user_id: str, name: str) -> dict:
    row = _board_admin(conn, board_id, user_id)
    conn.execute("UPDATE boards SET name = ? WHERE id = ?", (name, row["id"]))
    return next(b for b in list_boards(conn, user_id) if b["id"] == row["id"])


def delete_board(conn, board_id: str, user_id: str) -> None:
    row = _board_admin(conn, board_id, user_id)
    # Plans are never lost with a board: they return to their owners' main canvas.
    conn.execute("UPDATE plans SET board_id = NULL WHERE board_id = ?", (row["id"],))
    conn.execute("DELETE FROM canvas_items WHERE board_id = ?", (row["id"],))
    conn.execute("DELETE FROM boards WHERE id = ?", (row["id"],))


def move_plan(conn, plan, user_id: str, board_id: str | None) -> dict:
    if plan["owner_id"] != user_id:
        raise forbidden("owner_only")
    if board_access(conn, board_id, user_id) not in ("owner", "admin", "member"):
        raise ApiError(404, "board_not_found")
    conn.execute("UPDATE plans SET board_id = ?, parent_id = NULL, updated_at = ? WHERE id = ?", (board_id, stamp(), plan["id"]))
    conn.execute("DELETE FROM dependencies WHERE plan_id = ? OR blocker_id = ?", (plan["id"], plan["id"]))
    conn.execute("UPDATE plans SET parent_id = NULL WHERE parent_id = ?", (plan["id"],))
    log_event(conn, plan["id"], user_id, "moved_board")
    return serialize(conn, load(conn, plan["id"]), user_id, detail=True)


def assign_plan(conn, plan, user_id: str, new_owner: str) -> dict:
    """Hand a plan on a team board to another member (the owner, or a team admin, may do this)."""
    if not plan["board_id"]:
        raise ApiError(400, "assign_needs_team_board")
    my_role = team_role(conn, plan["board_id"], user_id)
    if plan["owner_id"] != user_id and my_role not in ("owner", "admin"):
        raise forbidden("team_role_required")
    if team_role(conn, plan["board_id"], new_owner) not in ("owner", "admin", "member"):
        raise ApiError(400, "assignee_not_member")
    if new_owner in (plan["approver_id"], plan["backup_approver_id"]):
        raise ApiError(400, "approver_is_owner")
    previous = plan["owner_id"]
    conn.execute("UPDATE plans SET owner_id = ?, timer_started_at = NULL, updated_at = ? WHERE id = ?", (new_owner, stamp(), plan["id"]))
    log_event(conn, plan["id"], user_id, "assigned", to=(user_brief(conn, new_owner) or {}).get("name", ""))
    notify(conn, new_owner, plan["id"], "assigned", title=plan["title"])
    if previous != user_id:
        notify(conn, previous, plan["id"], "unassigned", title=plan["title"])
    return serialize(conn, load(conn, plan["id"]), user_id, detail=True)


# ---- canvas items -------------------------------------------------------------------------------

ITEM_COLUMNS = "id, board_id, kind, x, y, w, h, text, color, created_at, updated_at"


def _item_board_ok(conn, board_id: str | None, user_id: str, edit: bool) -> None:
    role = board_access(conn, board_id, user_id)
    if role is None or (edit and role not in ("owner", "admin", "member")):
        raise not_found("board")


def list_items(conn, user_id: str) -> list[dict]:
    return [
        dict(r)
        for r in conn.execute(
            f"""SELECT {ITEM_COLUMNS} FROM canvas_items WHERE (board_id IS NULL AND owner_id = ?)
                OR board_id IN (SELECT id FROM boards WHERE owner_id = ?)
                OR board_id IN (SELECT b.id FROM boards b JOIN team_members m ON m.team_id = b.team_id WHERE m.user_id = ?)""",
            (user_id, user_id, user_id),
        )
    ]


def create_item(conn, user_id: str, data) -> dict:
    _item_board_ok(conn, data.board_id, user_id, True)
    iid = data.id or str(uuid.uuid4())
    if conn.execute("SELECT 1 FROM canvas_items WHERE id = ?", (iid,)).fetchone() is None:
        now = stamp()
        conn.execute(
            "INSERT INTO canvas_items(id, owner_id, board_id, kind, x, y, w, h, text, color, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (iid, user_id, data.board_id, data.kind, data.x, data.y, data.w, data.h, data.text, data.color, now, now),
        )
    return dict(conn.execute(f"SELECT {ITEM_COLUMNS} FROM canvas_items WHERE id = ?", (iid,)).fetchone())


def _load_item(conn, item_id: str, user_id: str):
    row = conn.execute("SELECT * FROM canvas_items WHERE id = ?", (item_id,)).fetchone()
    if row is None or (row["board_id"] is None and row["owner_id"] != user_id):
        raise not_found("item")
    _item_board_ok(conn, row["board_id"], user_id, True)
    return row


def update_item(conn, item_id: str, user_id: str, data) -> dict:
    row = _load_item(conn, item_id, user_id)
    sets = data.model_dump(exclude_none=True)
    if sets:
        sets["updated_at"] = stamp()
        conn.execute(f"UPDATE canvas_items SET {', '.join(f'{k} = ?' for k in sets)} WHERE id = ?", (*sets.values(), row["id"]))
    return dict(conn.execute(f"SELECT {ITEM_COLUMNS} FROM canvas_items WHERE id = ?", (row["id"],)).fetchone())


def delete_item(conn, item_id: str, user_id: str) -> None:
    row = _load_item(conn, item_id, user_id)
    conn.execute("DELETE FROM canvas_items WHERE id = ?", (row["id"],))
