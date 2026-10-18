import secrets
from datetime import timedelta

from . import timeutil
from .errors import ApiError
from .plans import apply_patch, can_edit_role, load, log_event, role_of, serialize, stamp


def create(conn, plan, user_id: str, data) -> dict:
    token = secrets.token_urlsafe(24)
    expires = timeutil.to_iso(timeutil.now() + timedelta(days=data.expires_in_days))
    conn.execute(
        "INSERT INTO share_links(token, plan_id, role, created_by, expires_at, created_at) VALUES (?,?,?,?,?,?)",
        (token, plan["id"], data.role, user_id, expires, stamp()),
    )
    log_event(conn, plan["id"], user_id, "shared", role=data.role, expires_at=expires)
    return {"token": token, "role": data.role, "expires_at": expires, "revoked_at": None}


def list_for(conn, plan) -> list[dict]:
    return [
        dict(r)
        for r in conn.execute(
            "SELECT token, role, expires_at, revoked_at, created_at FROM share_links WHERE plan_id = ? ORDER BY created_at DESC",
            (plan["id"],),
        )
    ]


def revoke(conn, token: str, user_id: str) -> None:
    row = conn.execute("SELECT * FROM share_links WHERE token = ?", (token,)).fetchone()
    if row is None:
        raise ApiError(404, "share_not_found")
    plan = conn.execute("SELECT * FROM plans WHERE id = ?", (row["plan_id"],)).fetchone()
    if plan is None or not can_edit_role(role_of(conn, plan, user_id)):
        raise ApiError(404, "share_not_found")
    if row["revoked_at"] is None:
        conn.execute("UPDATE share_links SET revoked_at = ? WHERE token = ?", (stamp(), token))
        log_event(conn, row["plan_id"], user_id, "share_revoked")


def resolve(conn, token: str):
    row = conn.execute("SELECT * FROM share_links WHERE token = ?", (token,)).fetchone()
    if row is None:
        raise ApiError(404, "share_not_found")
    if row["revoked_at"]:
        raise ApiError(410, "share_revoked")
    if timeutil.parse_iso(row["expires_at"]) <= timeutil.now():
        raise ApiError(410, "share_expired")
    plan = load(conn, row["plan_id"])
    return row, plan


def public_view(conn, row, plan) -> dict:
    data = serialize(conn, plan, None, detail=True)
    # A shared link shows the plan, not who is involved or what files are attached.
    for key in (
        "owner_id", "approver_id", "backup_approver_id", "approver", "backup_approver", "approved_by",
        "attachments", "chain", "current_approver", "approval_chain", "signatures", "goal_id", "board_id",
    ):
        data.pop(key, None)
    data["owner"] = {"name": data["owner"]["name"]} if data.get("owner") else None
    for step in data.get("steps", []):
        step.pop("assignee_id", None)
    data["share_role"] = row["role"]
    data["share_expires_at"] = row["expires_at"]
    return data


def shared_patch(conn, row, plan, data) -> dict:
    if row["role"] != "edit":
        raise ApiError(403, "view_only")
    apply_patch(conn, plan, None, data.base_version, data.changes(), via="share")
    return public_view(conn, row, load(conn, plan["id"]))
