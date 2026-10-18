"""Plan dependencies ("do B only after A"), kept free of cycles."""

from .errors import ApiError
from .plans import load_for, log_event, stamp

MAX_BLOCKERS = 20


def _reachable(conn, start: str, target: str) -> bool:
    """Is `target` reachable from `start` by following blocker edges?"""
    seen, stack = set(), [start]
    while stack:
        node = stack.pop()
        if node == target:
            return True
        if node in seen:
            continue
        seen.add(node)
        stack.extend(r["blocker_id"] for r in conn.execute("SELECT blocker_id FROM dependencies WHERE plan_id = ?", (node,)))
    return False


def add(conn, plan, user_id: str, blocker_id: str) -> list[str]:
    blocker = load_for(conn, blocker_id, user_id)
    if blocker["id"] == plan["id"]:
        raise ApiError(400, "dependency_self")
    same_canvas = blocker["board_id"] == plan["board_id"] and (plan["board_id"] or blocker["owner_id"] == plan["owner_id"])
    if not same_canvas:
        raise ApiError(400, "dependency_foreign")
    count = conn.execute("SELECT COUNT(*) FROM dependencies WHERE plan_id = ?", (plan["id"],)).fetchone()[0]
    if count >= MAX_BLOCKERS:
        raise ApiError(400, "too_many_dependencies", limit=MAX_BLOCKERS)
    # Adding plan <- blocker closes a cycle if plan is already (transitively) blocking blocker.
    if _reachable(conn, blocker["id"], plan["id"]):
        raise ApiError(400, "dependency_cycle")
    conn.execute(
        "INSERT OR IGNORE INTO dependencies(plan_id, blocker_id, created_at) VALUES (?,?,?)",
        (plan["id"], blocker["id"], stamp()),
    )
    log_event(conn, plan["id"], user_id, "dependency_added", title=blocker["title"])
    return blockers(conn, plan["id"])


def remove(conn, plan, user_id: str, blocker_id: str) -> list[str]:
    row = conn.execute("SELECT title FROM plans WHERE id = ?", (blocker_id,)).fetchone()
    deleted = conn.execute(
        "DELETE FROM dependencies WHERE plan_id = ? AND blocker_id = ?", (plan["id"], blocker_id)
    ).rowcount
    if deleted:
        log_event(conn, plan["id"], user_id, "dependency_removed", title=row["title"] if row else "")
    return blockers(conn, plan["id"])


def blockers(conn, plan_id: str) -> list[str]:
    return [r["blocker_id"] for r in conn.execute("SELECT blocker_id FROM dependencies WHERE plan_id = ?", (plan_id,))]


def open_blockers(conn, plan_id: str) -> list[dict]:
    """Blockers that are still unfinished (done or cancelled ones no longer block)."""
    return [
        dict(r)
        for r in conn.execute(
            """SELECT p.id, p.title, p.status FROM dependencies d JOIN plans p ON p.id = d.blocker_id
               WHERE d.plan_id = ? AND p.deleted_at IS NULL AND p.status NOT IN ('done', 'cancelled')""",
            (plan_id,),
        )
    ]
