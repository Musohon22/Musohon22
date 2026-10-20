"""ASGI application factory."""

from __future__ import annotations

import asyncio
import contextlib
import importlib
from pathlib import Path

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, RedirectResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from .config import Settings, load_settings
from .db import Database
from .http import ROUTES, make_endpoint
from .live import broker

MODULES = [
    "auth", "org", "employees", "biometrics", "devices", "gateway", "attendance", "corrections", "shifts",
    "leaves", "reports", "users", "audit", "alerts", "notifications", "settings", "integrations", "portal",
    "live", "platform", "billing", "roi", "dashboard", "system", "passkeys",
]


class State:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.db = Database(settings.db_path)
        self.telegram_codes: dict[str, tuple[str, float]] = {}
        self.biometrics = None   # lazily created provider


class SecurityHeaders:
    """Baseline security headers for every response."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                headers = message.setdefault("headers", [])
                extra = {
                    b"x-content-type-options": b"nosniff",
                    b"x-frame-options": b"DENY",
                    b"referrer-policy": b"same-origin",
                    b"permissions-policy": b"camera=(self), microphone=(), geolocation=()",
                    b"content-security-policy": (b"default-src 'self'; img-src 'self' data: blob:; "
                                                 b"media-src 'self' blob:; style-src 'self' 'unsafe-inline'; "
                                                 b"script-src 'self'; connect-src 'self'; frame-ancestors 'none'"),
                }
                existing = {k.lower() for k, _ in headers}
                for k, v in extra.items():
                    if k not in existing:
                        headers.append((k, v))
            await send(message)

        await self.app(scope, receive, send_wrapper)


def _spa(web_dir: Path, name: str):
    index = web_dir / name / "index.html"

    async def handler(request: Request):
        if not index.exists():
            return Response("UI not built", status_code=404)
        return FileResponse(index, headers={"Cache-Control": "no-cache"})
    return handler


def create_app(settings: Settings | None = None, *, run_jobs: bool = True) -> Starlette:
    settings = settings or load_settings()
    state = State(settings)
    state.db.migrate()
    with state.db.tx() as conn:
        from .services.tenancy import seed_plans
        seed_plans(conn)

    for name in MODULES:
        importlib.import_module(f"fras.modules.{name}")

    routes = []
    seen = set()
    # Static segments must win over path parameters (/employees/duplicates vs /employees/{id}).
    for spec in sorted(ROUTES, key=lambda s: s.path.count("{")):
        key = (spec.method, spec.path)
        if key in seen:
            continue
        seen.add(key)
        routes.append(Route(spec.path, make_endpoint(spec, state), methods=[spec.method]))

    from .modules.live import live_stream
    routes.append(Route("/api/v1/live/stream", live_stream(state), methods=["GET"]))

    async def health(request: Request):
        return JSONResponse({"status": "ok"})

    async def not_found_api(request: Request):
        return JSONResponse({"error": {"code": "NOT_FOUND", "message": "Unknown endpoint"}}, status_code=404)

    web_dir = Path(settings.web_dir)
    routes += [
        Route("/healthz", health),
        Route("/", lambda r: RedirectResponse("/app/")),
        Mount("/assets", StaticFiles(directory=str(web_dir / "assets"), check_dir=False)),
    ]
    for ui in ("app", "me", "terminal", "platform"):
        folder = {"app": "admin", "me": "portal", "terminal": "terminal", "platform": "platform"}[ui]
        routes.append(Mount(f"/{ui}/static", StaticFiles(directory=str(web_dir / folder), check_dir=False)))
        routes.append(Route(f"/{ui}", _spa(web_dir, folder)))
        routes.append(Route(f"/{ui}/{{rest:path}}", _spa(web_dir, folder)))
    routes.append(Mount("/roi/static", StaticFiles(directory=str(web_dir / "public"), check_dir=False)))
    routes.append(Route("/roi", _spa(web_dir, "public")))
    routes.append(Route("/api/{rest:path}", not_found_api, methods=["GET", "POST", "PUT", "PATCH", "DELETE"]))

    @contextlib.asynccontextmanager
    async def lifespan(app):
        broker.bind(asyncio.get_running_loop())
        task = None
        if run_jobs:
            from .jobs import run_scheduler
            task = asyncio.create_task(run_scheduler(state))
        yield
        if task:
            task.cancel()

    app = Starlette(routes=routes, middleware=[Middleware(SecurityHeaders)], lifespan=lifespan)
    app.state.fras = state
    return app
