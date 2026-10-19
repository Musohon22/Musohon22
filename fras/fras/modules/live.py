"""Live feed over Server-Sent Events: /api/v1/live/stream?token=<access token>.

EventSource cannot set headers, so the short-lived access token travels as a
query parameter; it is validated exactly like a bearer token and the stream is
filtered server-side to the caller's scope (masking applied before sending).
"""

from __future__ import annotations

import asyncio
import json

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse

from ..errors import ApiError
from ..http import Ctx, _auth_bearer
from ..live import broker

KEEPALIVE_S = 20


def live_stream(state):
    async def endpoint(request: Request):
        token = request.query_params.get("token", "")

        def auth():
            conn = state.db.connect()
            try:
                p = _auth_bearer(state, conn, f"Bearer {token}", "tenant")
                if "attendance.read" not in p.perms and "alert.read" not in p.perms:
                    raise ApiError(403, "FORBIDDEN", "No access to the live feed")
                ctx = Ctx(state, conn, p, {}, {}, {}, {})
                emp_sql, params = ctx.employee_filter("attendance.read", "e")
                scope = {"global": ctx.is_global("attendance.read"), "sites": ctx.site_ids("attendance.read"),
                         "employee_sql": (emp_sql, params),
                         "masked": not (ctx.can("employee.read_sensitive") or ctx.is_global("attendance.read")),
                         "alerts": ctx.can("alert.read")}
                return p, scope
            finally:
                state.db.release(conn)

        try:
            principal, scope = await run_in_threadpool(auth)
        except ApiError as e:
            return JSONResponse({"error": {"code": e.code, "message": e.message}}, status_code=e.status)

        allowed_cache: dict[str, bool] = {}

        def employee_allowed(emp_id: str) -> bool:
            if emp_id in allowed_cache:
                return allowed_cache[emp_id]
            conn = state.db.connect()
            try:
                sql, params = scope["employee_sql"]
                ok = conn.execute(f"SELECT 1 FROM employees e WHERE e.id = ? AND {sql}", [emp_id, *params]).fetchone()
                allowed_cache[emp_id] = ok is not None
                return allowed_cache[emp_id]
            finally:
                state.db.release(conn)

        channel = f"tenant:{principal.tenant_id}"
        queue = broker.subscribe(channel)

        async def gen():
            try:
                yield "retry: 5000\n\n"
                while True:
                    if await request.is_disconnected():
                        break
                    try:
                        msg = await asyncio.wait_for(queue.get(), timeout=KEEPALIVE_S)
                    except asyncio.TimeoutError:
                        yield ": keepalive\n\n"
                        continue
                    if msg["type"] == "event" and not scope["global"]:
                        if msg.get("employee_id"):
                            if not await run_in_threadpool(employee_allowed, msg["employee_id"]):
                                continue
                        elif scope["sites"] is not None and msg.get("site_id") not in scope["sites"]:
                            continue
                    if msg["type"] == "alert" and not scope["alerts"]:
                        continue
                    if msg["type"] == "event" and scope["masked"] and msg.get("name"):
                        last, _, first = msg["name"].partition(" ")
                        msg = {**msg, "name": f"{last} {first[:1]}."}
                    yield f"event: {msg['type']}\ndata: {json.dumps(msg, ensure_ascii=False)}\n\n"
            finally:
                broker.unsubscribe(channel, queue)

        return StreamingResponse(gen(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
    return endpoint
