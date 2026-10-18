"""Password change, signing out everywhere, and deleting an account with all its data."""

import json

from . import auth_extra, security
from .errors import ApiError
from .plans import notify, purge


def _bump(conn, user_id: str) -> int:
    conn.execute("UPDATE users SET token_version = token_version + 1 WHERE id = ?", (user_id,))
    return conn.execute("SELECT token_version FROM users WHERE id = ?", (user_id,)).fetchone()[0]


def change_password(conn, user, current: str, new: str, session_id: str | None = None) -> str:
    if not security.verify_password(current, user["password_hash"]):
        raise ApiError(403, "bad_password")
    conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (security.hash_password(new), user["id"]))
    auth_extra.revoke_other_sessions(conn, user["id"], session_id)
    return security.create_token(user["id"], _bump(conn, user["id"]), session_id)


def sign_out_everywhere(conn, user, session_id: str | None = None) -> str:
    """Ends every other session; this device stays signed in with a fresh token."""
    auth_extra.revoke_other_sessions(conn, user["id"], session_id)
    return security.create_token(user["id"], _bump(conn, user["id"]), session_id)


def delete_account(conn, user, password: str) -> None:
    if not security.verify_password(password, user["password_hash"]):
        raise ApiError(403, "bad_password")
    uid = user["id"]
    # Plans this person was approving go back to their owners instead of hanging forever.
    for plan in conn.execute(
        "SELECT * FROM plans WHERE (approver_id = ? OR backup_approver_id = ?) AND owner_id != ?", (uid, uid, uid)
    ).fetchall():
        if plan["status"] == "pending_approval" and plan["approver_id"] == uid:
            conn.execute(
                "UPDATE plans SET status = 'active', submitted_at = NULL, escalated_at = NULL, approval_reminded_at = NULL WHERE id = ?",
                (plan["id"],),
            )
            notify(conn, plan["owner_id"], plan["id"], "approver_left", title=plan["title"])
        conn.execute(
            """UPDATE plans SET approver_id = CASE WHEN approver_id = ? THEN backup_approver_id ELSE approver_id END,
               backup_approver_id = NULL WHERE id = ? AND (approver_id = ? OR backup_approver_id = ?)""",
            (uid, plan["id"], uid, uid),
        )
    conn.execute("UPDATE plans SET approved_by = NULL WHERE approved_by = ?", (uid,))
    # Later approval stages simply drop this person.
    for plan in conn.execute("SELECT id, approval_chain FROM plans WHERE approval_chain LIKE ?", (f'%"{uid}"%',)).fetchall():
        chain = [u for u in json.loads(plan["approval_chain"]) if u != uid]
        conn.execute("UPDATE plans SET approval_chain = ?, approval_stage = MIN(approval_stage, ?) WHERE id = ?", (json.dumps(chain), len(chain), plan["id"]))
    # Teams they own pass to the next admin (or member); a team left empty is removed.
    for team in conn.execute("SELECT team_id FROM team_members WHERE user_id = ? AND role = 'owner'", (uid,)).fetchall():
        heir = conn.execute(
            """SELECT user_id FROM team_members WHERE team_id = ? AND user_id != ?
               ORDER BY CASE role WHEN 'admin' THEN 0 WHEN 'member' THEN 1 ELSE 2 END, joined_at LIMIT 1""",
            (team["team_id"], uid),
        ).fetchone()
        if heir:
            conn.execute("UPDATE team_members SET role = 'owner' WHERE team_id = ? AND user_id = ?", (team["team_id"], heir["user_id"]))
        else:
            conn.execute("DELETE FROM teams WHERE id = ?", (team["team_id"],))
    for row in conn.execute("SELECT id FROM plans WHERE owner_id = ?", (uid,)).fetchall():
        purge(conn, row["id"])
    # History on other people's plans stays, without the name; everything personal goes.
    conn.execute("UPDATE events SET user_id = NULL WHERE user_id = ?", (uid,))
    conn.execute("DELETE FROM notifications WHERE user_id = ?", (uid,))
    conn.execute("DELETE FROM share_links WHERE created_by = ?", (uid,))
    conn.execute("DELETE FROM users WHERE id = ?", (uid,))
