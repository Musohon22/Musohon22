"""Local kiosk API (127.0.0.1 only). The terminal UI talks to this, never directly to the cloud,
so the gate keeps working when the network is down."""

from __future__ import annotations

from pathlib import Path

from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from .agent import Agent

WEB = Path(__file__).resolve().parents[2] / "web"


def create_kiosk_app(agent: Agent) -> Starlette:
    async def status(request: Request):
        info = agent.store.get("info", {}) or {}
        return JSONResponse({
            "activated": agent.activated, "online": agent.online, "last_sync": agent.last_sync,
            "outbox": agent.store.pending_count(), "outbox_fill_pct": round(100 * agent.store.fill_ratio(), 2),
            "gallery_version": agent.gallery.version, "people": len(agent.gallery.allowed),
            "site": (info.get("site") or {}).get("name"), "gate": (info.get("access_point") or {}).get("name"),
            "direction": info.get("direction", "in"), "camera_ok": agent.camera_ok,
            "provider_dev": agent.provider.is_dev, "config": agent.config})

    async def attempt(request: Request):
        body = await request.json()
        frames = body.get("frames") or []
        if not 1 <= len(frames) <= 5:
            return JSONResponse({"error": "1–5 frames required"}, status_code=422)
        res = await run_in_threadpool(agent.attempt, frames, body.get("direction"), body.get("session", "kiosk"))
        return JSONResponse(res)

    async def card(request: Request):
        body = await request.json()
        res = await run_in_threadpool(agent.card_pin, str(body.get("card_no", "")), body.get("pin"), body.get("direction"))
        return JSONResponse(res)

    async def help_(request: Request):
        body = await request.json() if await request.body() else {}
        return JSONResponse(agent.call_help(body.get("direction")))

    async def index(request: Request):
        return FileResponse(WEB / "terminal" / "index.html")

    return Starlette(routes=[
        Route("/api/status", status), Route("/api/attempt", attempt, methods=["POST"]),
        Route("/api/card", card, methods=["POST"]), Route("/api/help", help_, methods=["POST"]),
        Route("/", index), Route("/terminal", index),
        Mount("/terminal/static", StaticFiles(directory=str(WEB / "terminal"), check_dir=False)),
        Mount("/assets", StaticFiles(directory=str(WEB / "assets"), check_dir=False)),
    ])
