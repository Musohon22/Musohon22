"""Test helpers: an in-process ASGI client (no httpx needed) and a seeded environment."""

from __future__ import annotations

import asyncio
import base64
import json
import os
import shutil
import tempfile
import time
import unittest
from datetime import date
from pathlib import Path
from urllib.parse import urlencode

from fras.config import Settings
from fras.http import device_message
from fras.security import crypto
from fras.services import tenancy
from fras.util import new_id, now_iso

PASSWORD = "Test-Parol-2026"


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


class Env:
    """Fresh database + app + one tenant with a site, departments, shifts and users per role."""

    def __init__(self, plan: str = "professional"):
        self.dir = tempfile.mkdtemp(prefix="fras-test-")
        os.environ["FRAS_ENV"] = "test"
        self.settings = Settings(env="test", db_path=str(Path(self.dir) / "t.db"), data_dir=self.dir,
                                 secret_key="test-secret-key-0123456789abcdef",
                                 master_key=base64.b64decode(base64.b64encode(b"k" * 32)), biometric_provider="dev",
                                 web_dir=str(Path(__file__).resolve().parent.parent / "web"))
        from fras.app import create_app
        self.app = create_app(self.settings, run_jobs=False)
        self.state = self.app.state.fras
        self.db = self.state.db
        with self.db.tx() as conn:
            res = tenancy.create_tenant(conn, self.settings.master_key, slug="acme", name="Acme Zavod",
                                        plan_code=plan, admin_email="admin@acme.uz", admin_name="Admin",
                                        admin_password=PASSWORD)
        self.tenant_id = res["tenant_id"]
        self.admin_id = res["admin_user_id"]
        self.client = Client(self.app)

    def login(self, login: str, password: str = PASSWORD, org: str = "acme") -> Client:
        c = Client(self.app)
        r = c.post("/api/v1/auth/login", {"org": org, "login": login, "password": password})
        assert r.status == 200, r
        c.token = r.json()["access_token"]
        return c

    def add_user(self, login: str, role: str, scope_type: str = "global", scope_id: str | None = None,
                 employee_id: str | None = None, mfa: bool = False) -> str:
        from fras.security import passwords
        uid = new_id()
        with self.db.tx() as conn:
            conn.execute("INSERT INTO users (id, tenant_id, login, email, name, password_hash, status, mfa_enabled, "
                         "employee_id, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                         (uid, self.tenant_id, login, login if "@" in login else None, login, passwords.hash_secret(PASSWORD),
                          "active", 1 if mfa else 0, employee_id, now_iso()))
            conn.execute("INSERT INTO user_roles (id, tenant_id, user_id, role_code, scope_type, scope_id, created_at) "
                         "VALUES (?,?,?,?,?,?,?)", (new_id(), self.tenant_id, uid, role, scope_type, scope_id, now_iso()))
        return uid

    def cleanup(self):
        from fras.http import _dek_cache, _sub_cache
        _dek_cache.clear()
        _sub_cache.clear()
        shutil.rmtree(self.dir, ignore_errors=True)


class FrasTestCase(unittest.TestCase):
    plan = "professional"

    def setUp(self):
        from fras.ratelimit import limiter
        limiter._buckets.clear()
        self.env = Env(self.plan)
        self.state = self.env.state
        self.settings = self.env.settings
        self.settings.relax_mfa = True   # role-based MFA enforcement has its own test
        self.admin = self.env.login("admin@acme.uz")
        self.hr_id = self.env.add_user("hr@acme.uz", "hr_manager")
        self.hr = self.env.login("hr@acme.uz")

    def tearDown(self):
        self.env.cleanup()

    # -- builders
    def make_org(self):
        a = self.admin
        site = a.post("/api/v1/org/sites", {"code": "Z1", "name": "Zavod-1", "timezone": "Asia/Tashkent"})
        assert site.status == 201, site
        self.site_id = site.json()["id"]
        ap = a.post("/api/v1/org/access-points", {"site_id": self.site_id, "name": "Asosiy darvoza", "direction": "both"})
        assert ap.status == 201, ap
        self.ap_id = ap.json()["id"]
        d1 = a.post("/api/v1/org/departments", {"site_id": self.site_id, "code": "SEX-1", "name": "1-sex"})
        d2 = a.post("/api/v1/org/departments", {"site_id": self.site_id, "code": "SEX-2", "name": "2-sex"})
        self.dept1, self.dept2 = d1.json()["id"], d2.json()["id"]
        return self.site_id

    def make_employee(self, no: str, dept: str | None = None, team: str = "A", **extra) -> dict:
        body = {"personnel_no": no, "last_name": "Karimov", "first_name": "Akmal" + no[-2:].replace("-", "x"),
                "site_id": self.site_id, "department_id": dept or self.dept1, "team": team,
                "hire_date": date(2025, 1, 10).isoformat(), **extra}
        body["first_name"] = "".join(ch for ch in body["first_name"] if ch.isalpha()) or "Akmal"
        r = self.hr.post("/api/v1/employees", body)
        assert r.status == 201, r
        return r.json()

    def make_shift(self, code="D1", start="08:00", end="17:00", breaks=None, **kw):
        body = {"code": code, "name": f"Smena {code}", "start_time": start, "end_time": end,
                "breaks": breaks if breaks is not None else [{"start": "12:00", "end": "13:00", "paid": False}], **kw}
        r = self.hr.post("/api/v1/shifts/templates", body)
        assert r.status == 201, r
        return r.json()

    def assign(self, emp_id: str, day: date, code: str | None):
        r = self.hr.put("/api/v1/shifts/schedule/cell", {"employee_id": emp_id, "work_date": day.isoformat(),
                                                            "shift_code": code, "reason": "test setup reason"})
        assert r.status == 200, r

    def make_device(self) -> DeviceClient:
        r = self.admin.post("/api/v1/devices", {"name": "T-1", "type": "terminal", "site_id": self.site_id,
                                                "access_point_id": self.ap_id, "direction": "both", "serial": "SN-1"})
        assert r.status == 201, r
        code = r.json()["activation_code"]
        priv, pub = crypto.generate_device_keys()
        _, enc_pub = crypto.x25519_from_seed(priv)
        self.device_seed = priv
        act = self.admin.post("/api/v1/gateway/activate", {"code": code, "serial": "SN-1",
                                                           "public_key": base64.b64encode(pub).decode(),
                                                           "enc_public_key": base64.b64encode(enc_pub).decode(),
                                                           "firmware": "1.0.0"})
        assert act.status == 200, act
        self.device_id = act.json()["device_id"]
        return DeviceClient(Client(self.env.app), self.device_id, priv)
