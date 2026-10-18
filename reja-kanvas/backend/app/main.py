import asyncio
import contextlib
import json
import logging
import sqlite3
import uuid

from pydantic import ValidationError
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, PlainTextResponse, Response
from starlette.routing import Route

from . import (
    account, analytics, attachments, comments, config, db, dependencies, exporting, extras, plans,
    quickadd, security, shares, stats, templates, tracking, workflow,
)
from . import schemas as s
from .errors import ApiError, not_found

log = logging.getLogger("reja")


def endpoint(fn=None, *, auth: bool = True, body=None):
    """Wraps a handler with: one DB session, auth, body validation, uniform JSON errors.
    Handler signature: fn(request, conn, user, data) -> (payload | (payload, status))."""

    def deco(handler):
        async def route(request: Request):
            with db.session() as conn:
                user = _current_user(request, conn) if auth else None
                data = None
                if body is not None:
                    try:
                        raw = await request.json()
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        raise ApiError(400, "bad_json")
                    data = body.model_validate(raw)
                result = await handler(request, conn, user, data)
            if isinstance(result, Response):
                return result
            status = 200
            if isinstance(result, tuple):
                result, status = result
            if result is None:
                return Response(status_code=204)
            return JSONResponse(result, status_code=status)

        return route

    return deco(fn) if fn else deco


def _current_user(request: Request, conn) -> sqlite3.Row:
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        raise ApiError(401, "auth_required")
    user_id, version = security.decode_token(header[7:].strip())
    user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    # A password change or "sign out everywhere" bumps token_version and voids older tokens.
    if user is None or user["token_version"] != version:
        raise ApiError(401, "invalid_token")
    return user


def _me(user) -> dict:
    return {k: user[k] for k in ("id", "email", "name", "tz", "lang", "created_at")}


def _pid(request: Request, key: str = "plan_id") -> str:
    return request.path_params[key]


# ---- auth & profile ----------------------------------------------------------------------

@endpoint(auth=False, body=s.RegisterIn)
async def register(request, conn, user, data):
    if conn.execute("SELECT 1 FROM users WHERE email = ?", (data.email,)).fetchone():
        raise ApiError(409, "email_taken")
    uid = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO users(id, email, name, password_hash, tz, lang, created_at) VALUES (?,?,?,?,?,?,?)",
        (uid, data.email, data.name, security.hash_password(data.password), data.tz, data.lang, plans.stamp()),
    )
    row = conn.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
    return {"token": security.create_token(uid), "user": _me(row)}, 201


@endpoint(auth=False, body=s.LoginIn)
async def login(request, conn, user, data):
    security.login_limiter.check(data.email)
    row = conn.execute("SELECT * FROM users WHERE email = ?", (data.email,)).fetchone()
    if row is None or not security.verify_password(data.password, row["password_hash"]):
        security.login_limiter.fail(data.email)
        raise ApiError(401, "bad_credentials")
    security.login_limiter.reset(data.email)
    return {"token": security.create_token(row["id"], row["token_version"]), "user": _me(row)}


@endpoint
async def me(request, conn, user, data):
    return _me(user)


@endpoint(body=s.MeUpdate)
async def update_me(request, conn, user, data):
    sets = data.model_dump(exclude_none=True)
    if sets:
        conn.execute(f"UPDATE users SET {', '.join(f'{k} = ?' for k in sets)} WHERE id = ?", (*sets.values(), user["id"]))
    return _me(conn.execute("SELECT * FROM users WHERE id = ?", (user["id"],)).fetchone())


@endpoint
async def lookup_user(request, conn, user, data):
    email = request.query_params.get("email", "").strip().lower()
    row = conn.execute("SELECT id, name, email FROM users WHERE email = ?", (email,)).fetchone()
    if row is None or row["id"] == user["id"]:
        raise ApiError(404, "user_not_found")
    return dict(row)


# ---- plans -------------------------------------------------------------------------------

@endpoint
async def list_plans(request, conn, user, data):
    archived = request.query_params.get("archived") == "1"
    return {"plans": plans.list_for_owner(conn, user["id"], request.query_params.get("q"), archived=archived)}


@endpoint(body=s.PlanCreate)
async def create_plan(request, conn, user, data):
    return plans.create(conn, user["id"], data), 201


@endpoint
async def get_plan(request, conn, user, data):
    plan = plans.load_for(conn, _pid(request), user["id"])
    out = plans.serialize(conn, plan, user["id"], detail=True)
    out["blockers"] = workflow.readiness(conn, plan)
    out["open_blockers"] = dependencies.open_blockers(conn, plan["id"])
    return out


@endpoint(body=s.PlanPatch)
async def patch_plan(request, conn, user, data):
    plan = plans.load_for(conn, _pid(request), user["id"], "edit")
    try:
        changes = data.changes()
    except ValueError as exc:
        raise ApiError(422, "validation_error", details=[{"field": "", "msg": str(exc)}])
    out = plans.apply_patch(conn, plan, user["id"], data.base_version, changes)
    out["blockers"] = workflow.readiness(conn, plans.load(conn, plan["id"]))
    return out


@endpoint
async def delete_plan(request, conn, user, data):
    plan = plans.load_for(conn, _pid(request), user["id"], "edit")
    plans.soft_delete(conn, plan, user["id"])
    return None


@endpoint(body=s.BatchMove)
async def batch_move(request, conn, user, data):
    return {"items": plans.batch_move(conn, user["id"], data.items)}


@endpoint
async def restore_plan(request, conn, user, data):
    plan = plans.load_for(conn, _pid(request), user["id"], "edit", include_deleted=True)
    return plans.restore(conn, plan, user["id"])


@endpoint
async def trash(request, conn, user, data):
    return {"plans": plans.list_trash(conn, user["id"])}


@endpoint
async def purge_plan(request, conn, user, data):
    plan = plans.load_for(conn, _pid(request), user["id"], "edit", include_deleted=True)
    if not plan["deleted_at"]:
        raise ApiError(409, "not_in_trash")
    plans.purge(conn, plan["id"])
    return None


@endpoint
async def plan_events(request, conn, user, data):
    plan = plans.load_for(conn, _pid(request), user["id"])
    rows = conn.execute(
        """SELECT e.id, e.kind, e.data, e.created_at, u.name AS user_name FROM events e
           LEFT JOIN users u ON u.id = e.user_id WHERE e.plan_id = ? ORDER BY e.id DESC LIMIT 200""",
        (plan["id"],),
    ).fetchall()
    return {"events": [{**dict(r), "data": json.loads(r["data"])} for r in rows]}


# ---- steps -------------------------------------------------------------------------------

@endpoint(body=s.StepCreate)
async def add_step(request, conn, user, data):
    plan = plans.load_for(conn, _pid(request), user["id"], "edit")
    return plans.add_step(conn, plan, user["id"], data), 201


@endpoint(body=s.StepPatch)
async def patch_step(request, conn, user, data):
    step, plan = plans.load_step(conn, request.path_params["step_id"], user["id"])
    return plans.update_step(conn, step, plan, user["id"], data)


@endpoint
async def delete_step(request, conn, user, data):
    step, plan = plans.load_step(conn, request.path_params["step_id"], user["id"])
    plans.delete_step(conn, step, plan)
    return None


# ---- workflow ----------------------------------------------------------------------------

@endpoint(body=s.SubmitIn)
async def submit(request, conn, user, data):
    return workflow.submit(conn, plans.load_for(conn, _pid(request), user["id"], "edit"), user["id"], data)


@endpoint
async def approve(request, conn, user, data):
    return workflow.approve(conn, plans.load_for(conn, _pid(request), user["id"]), user["id"])


@endpoint(body=s.RejectIn)
async def reject(request, conn, user, data):
    return workflow.reject(conn, plans.load_for(conn, _pid(request), user["id"]), user["id"], data)


@endpoint(body=s.ReopenIn)
async def reopen(request, conn, user, data):
    return workflow.reopen(conn, plans.load_for(conn, _pid(request), user["id"]), user["id"], data)


@endpoint
async def cancel(request, conn, user, data):
    return workflow.cancel(conn, plans.load_for(conn, _pid(request), user["id"], "edit"), user["id"])


@endpoint
async def overdue(request, conn, user, data):
    return {"plans": workflow.overdue(conn, user)}


@endpoint(body=s.RescheduleIn)
async def reschedule(request, conn, user, data):
    return {"plans": workflow.reschedule(conn, user, data)}


@endpoint
async def approvals(request, conn, user, data):
    return {"plans": plans.list_awaiting_me(conn, user["id"])}


# ---- attachments -------------------------------------------------------------------------

@endpoint
async def upload(request, conn, user, data):
    plan = plans.load_for(conn, _pid(request), user["id"], "edit")
    if plan["status"] in plans.LOCKED_STATUSES:
        raise ApiError(409, "plan_locked", status=plan["status"])
    length = request.headers.get("content-length")
    if length and length.isdigit() and int(length) > config.MAX_UPLOAD_BYTES + 64 * 1024:
        raise ApiError(413, "file_too_large", limit=config.MAX_UPLOAD_BYTES)
    form = await request.form(max_files=1, max_fields=5)
    try:
        file = form.get("file")
        if file is None or isinstance(file, str):
            raise ApiError(400, "file_missing")
        return await attachments.save(conn, plan, user["id"], file), 201
    finally:
        await form.close()


def _load_attachment(conn, request, user, need="view"):
    row = conn.execute("SELECT * FROM attachments WHERE id = ?", (request.path_params["att_id"],)).fetchone()
    if row is None:
        raise not_found("attachment")
    return row, plans.load_for(conn, row["plan_id"], user["id"], need)


@endpoint
async def download(request, conn, user, data):
    att, _ = _load_attachment(conn, request, user)
    path = config.UPLOAD_DIR / att["stored_name"]
    if not path.exists():
        raise not_found("attachment")
    return FileResponse(
        path, media_type=att["mime"], filename=att["filename"],
        headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private, max-age=3600"},
    )


@endpoint
async def delete_attachment(request, conn, user, data):
    att, plan = _load_attachment(conn, request, user, "edit")
    if plan["status"] in plans.LOCKED_STATUSES:
        raise ApiError(409, "plan_locked", status=plan["status"])
    attachments.remove(conn, att, plan, user["id"])
    return None


# ---- sharing -----------------------------------------------------------------------------

@endpoint(body=s.ShareCreate)
async def create_share(request, conn, user, data):
    return shares.create(conn, plans.load_for(conn, _pid(request), user["id"], "edit"), user["id"], data), 201


@endpoint
async def list_shares(request, conn, user, data):
    return {"shares": shares.list_for(conn, plans.load_for(conn, _pid(request), user["id"], "edit"))}


@endpoint
async def revoke_share(request, conn, user, data):
    shares.revoke(conn, request.path_params["token"], user["id"])
    return None


@endpoint(auth=False)
async def shared_view(request, conn, user, data):
    row, plan = shares.resolve(conn, request.path_params["token"])
    return shares.public_view(conn, row, plan)


@endpoint(auth=False, body=s.SharedPatch)
async def shared_patch(request, conn, user, data):
    row, plan = shares.resolve(conn, request.path_params["token"])
    return shares.shared_patch(conn, row, plan, data)


# ---- stats, notifications, templates ----------------------------------------------------

@endpoint
async def get_stats(request, conn, user, data):
    return stats.summary(conn, user)


@endpoint
async def notifications(request, conn, user, data):
    rows = conn.execute(
        """SELECT n.id, n.plan_id, n.kind, n.data, n.read_at, n.created_at FROM notifications n
           WHERE n.user_id = ? ORDER BY n.id DESC LIMIT 100""",
        (user["id"],),
    ).fetchall()
    return {"notifications": [{**dict(r), "data": json.loads(r["data"])} for r in rows]}


@endpoint(body=s.ReadNotifications)
async def read_notifications(request, conn, user, data):
    if data.ids:
        marks = ",".join("?" * len(data.ids))
        conn.execute(
            f"UPDATE notifications SET read_at = ? WHERE user_id = ? AND read_at IS NULL AND id IN ({marks})",
            (plans.stamp(), user["id"], *data.ids),
        )
    else:
        conn.execute("UPDATE notifications SET read_at = ? WHERE user_id = ? AND read_at IS NULL", (plans.stamp(), user["id"]))
    return None


@endpoint
async def list_templates(request, conn, user, data):
    return {"templates": templates.catalog(), "mine": extras.list_templates(conn, user["id"])}


@endpoint
async def apply_template(request, conn, user, data):
    key = request.path_params["key"]
    if key.startswith("u:"):
        return {"plans": extras.apply_template(conn, user, key)}, 201
    return {"plans": templates.apply(conn, user, key)}, 201


@endpoint
async def delete_my_template(request, conn, user, data):
    extras.delete_template(conn, user["id"], request.path_params["key"])
    return None


# ---- new: dependencies, comments, timer, duplicate, archive -------------------------------

@endpoint(body=s.DependencyIn)
async def add_dependency(request, conn, user, data):
    plan = plans.load_for(conn, _pid(request), user["id"], "edit")
    return {"blocked_by": dependencies.add(conn, plan, user["id"], data.blocker_id)}, 201


@endpoint
async def remove_dependency(request, conn, user, data):
    plan = plans.load_for(conn, _pid(request), user["id"], "edit")
    return {"blocked_by": dependencies.remove(conn, plan, user["id"], request.path_params["blocker_id"])}


@endpoint
async def list_comments(request, conn, user, data):
    return {"comments": comments.list_for(conn, plans.load_for(conn, _pid(request), user["id"]))}


@endpoint(body=s.CommentIn)
async def add_comment(request, conn, user, data):
    return comments.add(conn, plans.load_for(conn, _pid(request), user["id"]), user["id"], data.body), 201


@endpoint(body=s.CommentIn)
async def edit_comment(request, conn, user, data):
    return comments.edit(conn, comments.load_own(conn, request.path_params["comment_id"], user["id"]), data.body)


@endpoint
async def delete_comment(request, conn, user, data):
    comments.delete(conn, comments.load_own(conn, request.path_params["comment_id"], user["id"]))
    return None


@endpoint
async def timer_start(request, conn, user, data):
    plan = plans.load_for(conn, _pid(request), user["id"], "edit")
    tracking.start(conn, plan, user["id"])
    return plans.serialize(conn, plans.load(conn, plan["id"]), user["id"], detail=True)


@endpoint
async def timer_stop(request, conn, user, data):
    plan = plans.load_for(conn, _pid(request), user["id"], "edit")
    seconds = tracking.stop(conn, user["id"]) if plan["timer_started_at"] else 0
    out = plans.serialize(conn, plans.load(conn, plan["id"]), user["id"], detail=True)
    out["booked_seconds"] = seconds
    return out


@endpoint
async def duplicate_plan(request, conn, user, data):
    return extras.duplicate(conn, plans.load_for(conn, _pid(request), user["id"], "edit"), user["id"]), 201


@endpoint(body=s.TemplateSave)
async def save_as_template(request, conn, user, data):
    plan = plans.load_for(conn, _pid(request), user["id"], "edit")
    return extras.save_template(conn, plan, user["id"], data.name), 201


@endpoint
async def archive_plan(request, conn, user, data):
    return extras.archive(conn, plans.load_for(conn, _pid(request), user["id"], "edit"), user["id"], True)


@endpoint
async def unarchive_plan(request, conn, user, data):
    return extras.archive(conn, plans.load_for(conn, _pid(request), user["id"], "edit"), user["id"], False)


@endpoint
async def archive_finished(request, conn, user, data):
    return {"archived": extras.archive_finished(conn, user["id"])}


# ---- new: quick add, analytics, export/import, calendar, account --------------------------

@endpoint(body=s.ParseIn)
async def parse_text(request, conn, user, data):
    return quickadd.parse(data.text, user["tz"])


@endpoint
async def get_analytics(request, conn, user, data):
    try:
        days = min(365, max(7, int(request.query_params.get("days", "30"))))
    except ValueError:
        days = 30
    return analytics.report(conn, user, days)


@endpoint
async def export_json(request, conn, user, data):
    return JSONResponse(
        exporting.export_json(conn, user),
        headers={"Content-Disposition": 'attachment; filename="reja-export.json"'},
    )


@endpoint
async def export_csv(request, conn, user, data):
    return PlainTextResponse(
        exporting.export_csv(conn, user),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="reja-export.csv"'},
    )


@endpoint(body=s.ImportIn)
async def import_json(request, conn, user, data):
    return exporting.import_json(conn, user, data), 201


@endpoint
async def calendar_link(request, conn, user, data):
    rotate = request.method == "POST"
    return {"token": exporting.ics_token(conn, user, rotate=rotate)}


@endpoint(auth=False)
async def calendar_feed(request, conn, user, data):
    token = request.path_params["token"].removesuffix(".ics")
    return Response(
        exporting.calendar_feed(conn, token),
        media_type="text/calendar; charset=utf-8",
        headers={"Cache-Control": "private, max-age=300"},
    )


@endpoint(body=s.PasswordChange)
async def change_password(request, conn, user, data):
    return {"token": account.change_password(conn, user, data.current, data.new)}


@endpoint
async def sign_out_everywhere(request, conn, user, data):
    return {"token": account.sign_out_everywhere(conn, user)}


@endpoint(body=s.DeleteAccount)
async def delete_account(request, conn, user, data):
    account.delete_account(conn, user, data.password)
    return None


@endpoint(auth=False)
async def health(request, conn, user, data):
    conn.execute("SELECT 1").fetchone()
    return {"ok": True, "time": plans.stamp()}


# ---- app ---------------------------------------------------------------------------------

async def api_error(request, exc: ApiError):
    return JSONResponse(exc.to_dict(), status_code=exc.status)


async def validation_error(request, exc: ValidationError):
    details = [{"field": ".".join(str(p) for p in e["loc"]), "msg": e["msg"]} for e in exc.errors()]
    return JSONResponse({"error": "validation_error", "message": "Invalid input", "details": details}, status_code=422)


async def unexpected_error(request, exc: Exception):
    log.exception("unhandled error")
    return JSONResponse({"error": "server_error", "message": "Internal error"}, status_code=500)


def _run_jobs_once() -> None:
    with db.session() as conn:
        workflow.run_jobs(conn)


@contextlib.asynccontextmanager
async def lifespan(app):
    db.init_db()
    stop = asyncio.Event()

    async def loop():
        while not stop.is_set():
            try:
                await asyncio.to_thread(_run_jobs_once)
            except Exception:
                log.exception("background jobs failed")
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=config.JOB_INTERVAL_SECONDS)

    task = asyncio.create_task(loop()) if config.JOB_INTERVAL_SECONDS > 0 else None
    yield
    stop.set()
    if task:
        await task


P = "/api"
routes = [
    Route(f"{P}/health", health, methods=["GET"]),
    Route(f"{P}/auth/register", register, methods=["POST"]),
    Route(f"{P}/auth/login", login, methods=["POST"]),
    Route(f"{P}/me", me, methods=["GET"]),
    Route(f"{P}/me", update_me, methods=["PATCH"]),
    Route(f"{P}/users/lookup", lookup_user, methods=["GET"]),
    Route(f"{P}/stats", get_stats, methods=["GET"]),
    Route(f"{P}/approvals", approvals, methods=["GET"]),
    Route(f"{P}/notifications", notifications, methods=["GET"]),
    Route(f"{P}/notifications/read", read_notifications, methods=["POST"]),
    Route(f"{P}/templates", list_templates, methods=["GET"]),
    Route(f"{P}/templates/{{key}}/apply", apply_template, methods=["POST"]),
    Route(f"{P}/templates/{{key}}", delete_my_template, methods=["DELETE"]),
    Route(f"{P}/parse", parse_text, methods=["POST"]),
    Route(f"{P}/analytics", get_analytics, methods=["GET"]),
    Route(f"{P}/export.json", export_json, methods=["GET"]),
    Route(f"{P}/export.csv", export_csv, methods=["GET"]),
    Route(f"{P}/import", import_json, methods=["POST"]),
    Route(f"{P}/me/calendar", calendar_link, methods=["GET", "POST"]),
    Route(f"{P}/calendar/{{token}}", calendar_feed, methods=["GET"]),
    Route(f"{P}/me/password", change_password, methods=["POST"]),
    Route(f"{P}/me/logout-all", sign_out_everywhere, methods=["POST"]),
    Route(f"{P}/me", delete_account, methods=["DELETE"]),
    Route(f"{P}/plans/archive-finished", archive_finished, methods=["POST"]),
    Route(f"{P}/trash", trash, methods=["GET"]),
    Route(f"{P}/trash/{{plan_id}}", purge_plan, methods=["DELETE"]),
    Route(f"{P}/plans", list_plans, methods=["GET"]),
    Route(f"{P}/plans", create_plan, methods=["POST"]),
    Route(f"{P}/plans/overdue", overdue, methods=["GET"]),
    Route(f"{P}/plans/reschedule", reschedule, methods=["POST"]),
    Route(f"{P}/plans/batch-move", batch_move, methods=["POST"]),
    Route(f"{P}/plans/{{plan_id}}", get_plan, methods=["GET"]),
    Route(f"{P}/plans/{{plan_id}}", patch_plan, methods=["PATCH"]),
    Route(f"{P}/plans/{{plan_id}}", delete_plan, methods=["DELETE"]),
    Route(f"{P}/plans/{{plan_id}}/restore", restore_plan, methods=["POST"]),
    Route(f"{P}/plans/{{plan_id}}/events", plan_events, methods=["GET"]),
    Route(f"{P}/plans/{{plan_id}}/steps", add_step, methods=["POST"]),
    Route(f"{P}/plans/{{plan_id}}/submit", submit, methods=["POST"]),
    Route(f"{P}/plans/{{plan_id}}/approve", approve, methods=["POST"]),
    Route(f"{P}/plans/{{plan_id}}/reject", reject, methods=["POST"]),
    Route(f"{P}/plans/{{plan_id}}/reopen", reopen, methods=["POST"]),
    Route(f"{P}/plans/{{plan_id}}/cancel", cancel, methods=["POST"]),
    Route(f"{P}/plans/{{plan_id}}/attachments", upload, methods=["POST"]),
    Route(f"{P}/plans/{{plan_id}}/shares", create_share, methods=["POST"]),
    Route(f"{P}/plans/{{plan_id}}/shares", list_shares, methods=["GET"]),
    Route(f"{P}/plans/{{plan_id}}/dependencies", add_dependency, methods=["POST"]),
    Route(f"{P}/plans/{{plan_id}}/dependencies/{{blocker_id}}", remove_dependency, methods=["DELETE"]),
    Route(f"{P}/plans/{{plan_id}}/comments", list_comments, methods=["GET"]),
    Route(f"{P}/plans/{{plan_id}}/comments", add_comment, methods=["POST"]),
    Route(f"{P}/plans/{{plan_id}}/timer/start", timer_start, methods=["POST"]),
    Route(f"{P}/plans/{{plan_id}}/timer/stop", timer_stop, methods=["POST"]),
    Route(f"{P}/plans/{{plan_id}}/duplicate", duplicate_plan, methods=["POST"]),
    Route(f"{P}/plans/{{plan_id}}/save-template", save_as_template, methods=["POST"]),
    Route(f"{P}/plans/{{plan_id}}/archive", archive_plan, methods=["POST"]),
    Route(f"{P}/plans/{{plan_id}}/unarchive", unarchive_plan, methods=["POST"]),
    Route(f"{P}/comments/{{comment_id}}", edit_comment, methods=["PATCH"]),
    Route(f"{P}/comments/{{comment_id}}", delete_comment, methods=["DELETE"]),
    Route(f"{P}/steps/{{step_id}}", patch_step, methods=["PATCH"]),
    Route(f"{P}/steps/{{step_id}}", delete_step, methods=["DELETE"]),
    Route(f"{P}/attachments/{{att_id}}", download, methods=["GET"]),
    Route(f"{P}/attachments/{{att_id}}", delete_attachment, methods=["DELETE"]),
    Route(f"{P}/shares/{{token}}", revoke_share, methods=["DELETE"]),
    Route(f"{P}/shared/{{token}}", shared_view, methods=["GET"]),
    Route(f"{P}/shared/{{token}}", shared_patch, methods=["PATCH"]),
]


def create_app() -> Starlette:
    return Starlette(
        routes=routes,
        middleware=[
            Middleware(
                CORSMiddleware,
                allow_origins=config.FRONTEND_ORIGINS,
                allow_methods=["GET", "POST", "PATCH", "DELETE"],
                allow_headers=["Authorization", "Content-Type"],
                max_age=600,
            )
        ],
        exception_handlers={ApiError: api_error, ValidationError: validation_error, Exception: unexpected_error},
        lifespan=lifespan,
    )


app = create_app()
