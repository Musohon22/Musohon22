"""In-process ASGI client (no network, no httpx). Used by the test suite and by `fras seed-demo`,
so demo data goes through the same validation, RBAC and audit as real requests."""

from __future__ import annotations

import asyncio
import json
import time
from urllib.parse import urlencode

from .http import device_message
from .security import crypto


class Resp:
    def __init__(self, status: int, headers: dict, body: bytes):
        self.status = status
        self.headers = headers
        self.body = body

    def json(self):
        return json.loads(self.body or b"null")

    def __repr__(self):
        return f"<Resp {self.status} {self.body[:300]!r}>"


class Client:
    def __init__(self, app):
        self.app = app
        self.token: str | None = None
        self.cookies: dict[str, str] = {}

    def request(self, method: str, path: str, json_body=None, headers: dict | None = None, query: dict | None = None,
                raw: bytes | None = None, content_type: str = "application/json") -> Resp:
        body = raw if raw is not None else (json.dumps(json_body).encode() if json_body is not None else b"")
        hdrs = {"host": "test", **({"content-type": content_type} if body else {})}
        if self.token:
            hdrs["authorization"] = f"Bearer {self.token}"
        if self.cookies:
            hdrs["cookie"] = "; ".join(f"{k}={v}" for k, v in self.cookies.items())
        hdrs.update({k.lower(): v for k, v in (headers or {}).items()})
        qs = urlencode(query or {}, doseq=True)
        scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": method,
                 "path": path, "raw_path": path.encode(), "query_string": qs.encode(), "root_path": "",
                 "scheme": "http", "server": ("test", 80), "client": ("127.0.0.1", 5000),
                 "headers": [(k.encode(), str(v).encode()) for k, v in hdrs.items()]}
        out = {"status": 0, "headers": {}, "body": b""}
        sent = {"done": False}

        async def receive():
            if sent["done"]:
                await asyncio.sleep(0.01)
                return {"type": "http.disconnect"}
            sent["done"] = True
            return {"type": "http.request", "body": body, "more_body": False}

        async def send(message):
            if message["type"] == "http.response.start":
                out["status"] = message["status"]
                for k, v in message.get("headers", []):
                    key = k.decode().lower()
                    if key == "set-cookie":
                        name, _, rest = v.decode().partition("=")
                        self.cookies[name] = rest.split(";", 1)[0]
                    out["headers"][key] = v.decode()
            elif message["type"] == "http.response.body":
                out["body"] += message.get("body", b"")

        asyncio.run(self.app(scope, receive, send))
        return Resp(out["status"], out["headers"], out["body"])

    def get(self, path, **kw):
        return self.request("GET", path, **kw)

    def post(self, path, json_body=None, **kw):
        return self.request("POST", path, json_body if json_body is not None else {}, **kw)

    def put(self, path, json_body=None, **kw):
        return self.request("PUT", path, json_body, **kw)

    def patch(self, path, json_body=None, **kw):
        return self.request("PATCH", path, json_body, **kw)

    def delete(self, path, **kw):
        return self.request("DELETE", path, **kw)


class DeviceClient:
    """Signs requests like a real terminal (Ed25519 over method, path, timestamp, body hash)."""

    def __init__(self, client: Client, device_id: str, private_key: bytes):
        self.c = client
        self.device_id = device_id
        self.key = private_key

    def call(self, method: str, path: str, payload=None, ts: int | None = None) -> Resp:
        body = json.dumps(payload).encode() if payload is not None else b""
        ts_s = str(ts or int(time.time()))
        sig = crypto.sign(self.key, device_message(method, path, ts_s, body))
        saved = self.c.token
        self.c.token = None
        try:
            return self.c.request(method, path, raw=body if body else None,
                                  headers={"x-device-id": self.device_id, "x-device-ts": ts_s, "x-device-sig": sig})
        finally:
            self.c.token = saved
