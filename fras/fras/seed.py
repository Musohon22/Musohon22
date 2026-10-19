"""`python -m fras seed-demo`: a demo factory to click through every screen.

Data goes through the real API in-process (same validation, RBAC, audit and attendance engine as
production); only user accounts are inserted directly so they get known passwords. Everything is
fictional. Face enrolments use synthetic frames for the DEV provider — they are not faces.
"""

from __future__ import annotations

import base64
import random
import uuid
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from . import db as dbm
from .biometrics.synthetic import frames_for
from .config import Settings
from .db import Database
from .inproc import Client, DeviceClient
from .security import crypto, passwords
from .services import tenancy
from .util import new_id, now_iso

PASSWORD = "Demo-Parol-2026"
TZ = ZoneInfo("Asia/Tashkent")
LAST = ["Karimov", "Rahimov", "Toshmatov", "Yusupov", "Aliyev", "Qodirov", "Saidov", "Ergashev", "Nazarov", "Xolmatov",
        "Sobirov", "Jo'rayev", "Mirzayev", "Ismoilov", "Hamidov", "Usmonov", "Abdullayev", "Rustamov"]
FIRST = ["Akmal", "Dilshod", "Jasur", "Bekzod", "Sardor", "Otabek", "Aziz", "Sherzod", "Ulug'bek", "Nodir",
         "Malika", "Dilnoza", "Gulnora", "Nilufar", "Shahnoza", "Madina", "Zarina", "Feruza"]
FEMALE = set(FIRST[10:])


def _female(last: str) -> str:
    return last + "a" if last.endswith("ov") or last.endswith("ev") else last


def _ok(r, *codes):
    if r.status not in (codes or (200, 201, 202)):
        raise RuntimeError(f"seed step failed: {r.status} {r.body[:400]!r}")
    return r.json()


def _local(d: date, minutes: int) -> str:
    dt = datetime(d.year, d.month, d.day, tzinfo=TZ) + timedelta(minutes=minutes)
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


class _SeedClient(Client):
    """Bulk seeding is one operator doing thousands of calls; per-user rate limits do not apply."""

    def request(self, *a, **kw):
        from .ratelimit import limiter
        limiter._buckets.clear()
        return super().request(*a, **kw)


def _user(conn, tenant_id: str, login: str, name: str, role: str, scope_type="global", scope_id=None, employee_id=None):
    uid = new_id()
    conn.execute("INSERT INTO users (id, tenant_id, login, email, name, password_hash, status, mfa_enabled, employee_id, "
                 "language, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                 (uid, tenant_id, login, login if "@" in login else None, name, passwords.hash_secret(PASSWORD), "active",
                  0, employee_id, "uz", now_iso()))
    conn.execute("INSERT INTO user_roles (id, tenant_id, user_id, role_code, scope_type, scope_id, created_by, created_at) "
                 "VALUES (?,?,?,?,?,?,?,?)", (new_id(), tenant_id, uid, role, scope_type, scope_id, "seed", now_iso()))
    return uid


def seed_demo(settings: Settings, database: Database, employees: int = 60, days: int = 14) -> list[str]:
    from .app import create_app
    rnd = random.Random(2026)
    out: list[str] = []
    relax = settings.relax_mfa
    settings.relax_mfa = True        # seeding acts as admins without TOTP; restored below
    try:
        app = create_app(settings, run_jobs=False)
        with database.tx() as conn:
            if dbm.one(conn, "SELECT 1 AS x FROM tenants WHERE slug = 'demo'"):
                return ["demo tenant already exists — delete the database file to reseed"]
            if not dbm.one(conn, "SELECT 1 AS x FROM platform_users WHERE email = 'owner@fras.local'"):
                conn.execute("INSERT INTO platform_users (id, email, name, password_hash, role, totp_secret, mfa_enabled, "
                             "status, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                             (new_id(), "owner@fras.local", "Platforma egasi", passwords.hash_secret(PASSWORD), "owner",
                              None, 0, "active", now_iso()))
            res = tenancy.create_tenant(conn, settings.master_key, slug="demo", name="Demo Tekstil Zavodi",
                                        plan_code="professional", admin_email="admin@demo.uz", admin_name="Demo Admin",
                                        admin_password=PASSWORD, legal_name="\"Demo Tekstil\" MChJ", tin="301234567")
            tenant_id = res["tenant_id"]
            # two more customers so the platform panel has something to show
            tenancy.create_tenant(conn, settings.master_key, slug="beta", name="Beta Qurilish", plan_code="business",
                                  admin_email="admin@beta.uz", admin_name="Beta Admin", trial_days=14)
            tenancy.create_tenant(conn, settings.master_key, slug="gamma", name="Gamma Oziq-ovqat", plan_code="starter",
                                  admin_email="admin@gamma.uz", admin_name="Gamma Admin", billing_cycle="monthly")

        def login(who: str) -> Client:
            c = _SeedClient(app)
            r = _ok(c.post("/api/v1/auth/login", {"org": "demo", "login": who, "password": PASSWORD}))
            c.token = r["access_token"]
            return c

        admin = login("admin@demo.uz")
        site = _ok(admin.post("/api/v1/org/sites", {"code": "Z1", "name": "Chilonzor zavodi", "timezone": "Asia/Tashkent",
                                                    "address": "Toshkent, Chilonzor tumani"}))
        site_id = site["id"]
        gate1 = _ok(admin.post("/api/v1/org/access-points", {"site_id": site_id, "name": "Asosiy darvoza", "direction": "both"}))
        gate2 = _ok(admin.post("/api/v1/org/access-points", {"site_id": site_id, "name": "Ombor kirishi", "direction": "both"}))
        depts = {}
        for code, name in [("SEX-1", "Tikuv sexi"), ("SEX-2", "Bichish sexi"), ("OMB", "Ombor"), ("ADM", "Ma'muriyat")]:
            depts[code] = _ok(admin.post("/api/v1/org/departments", {"site_id": site_id, "code": code, "name": name}))["id"]
        for p in ["Tikuvchi", "Bichuvchi", "Omborchi", "Usta", "Buxgalter"]:
            _ok(admin.post("/api/v1/org/positions", {"name": p}))

        with database.tx() as conn:
            _user(conn, tenant_id, "hr@demo.uz", "Nigora Hasanova (HR)", "hr_manager")
            _user(conn, tenant_id, "operator@demo.uz", "Kamola Yo'ldosheva (HR operator)", "hr_operator", "site", site_id)
            _user(conn, tenant_id, "sex1@demo.uz", "Rustam Olimov (sex boshlig'i)", "dept_head", "department", depts["SEX-1"])
            _user(conn, tenant_id, "smena@demo.uz", "Botir Salimov (smena boshlig'i)", "shift_lead", "team", f"{depts['SEX-1']}:A")
            _user(conn, tenant_id, "security@demo.uz", "Anvar Qosimov (xavfsizlik)", "security")
            _user(conn, tenant_id, "auditor@demo.uz", "Auditor", "auditor")
        hr = login("hr@demo.uz")

        _ok(hr.post("/api/v1/shifts/templates", {"code": "D1", "name": "Kunduzgi", "start_time": "08:00", "end_time": "17:00",
                                                  "breaks": [{"start": "12:00", "end": "13:00", "paid": False}], "color": "blue"}))
        _ok(hr.post("/api/v1/shifts/templates", {"code": "N1", "name": "Tungi", "start_time": "20:00", "end_time": "08:00",
                                                  "breaks": [{"start": "00:00", "end": "00:30", "paid": False}], "color": "indigo"}))
        _ok(hr.post("/api/v1/shifts/templates", {"code": "A1", "name": "Ma'muriy", "start_time": "09:00", "end_time": "18:00",
                                                  "breaks": [{"start": "13:00", "end": "14:00", "paid": False}], "color": "teal"}))

        # employees
        emps = []
        dept_cycle = ["SEX-1"] * 5 + ["SEX-2"] * 3 + ["OMB"] * 2 + ["ADM"]
        for i in range(employees):
            dcode = dept_cycle[i % len(dept_cycle)]
            first = FIRST[i % len(FIRST)]
            last = LAST[(i * 7) % len(LAST)]
            body = {"personnel_no": f"T-{1001 + i}", "last_name": _female(last) if first in FEMALE else last, "first_name": first,
                    "site_id": site_id, "department_id": depts[dcode], "team": "A" if i % 3 else "B",
                    "hire_date": (date.today() - timedelta(days=200 + i * 9)).isoformat(),
                    "phone": f"+99890{1000000 + i * 37:07d}", "language": "ru" if i % 9 == 0 else "uz"}
            if i % 4 == 0:
                body.update(card_no=f"{40000 + i}", pin=f"{(1357 + i * 11) % 10000:04d}")
            e = _ok(hr.post("/api/v1/employees", body))
            e["_dept"] = dcode
            e["_pin"] = body.get("pin")
            e["_card"] = body.get("card_no")
            emps.append(e)

        # schedule: D1 Mon–Sat for production, A1 Mon–Fri for admin; night shift for team B of SEX-2
        start, end = date.today() - timedelta(days=days), date.today() + timedelta(days=21)
        for code, dept, wd in [("D1", "SEX-1", [0, 1, 2, 3, 4, 5]), ("D1", "OMB", [0, 1, 2, 3, 4, 5]), ("A1", "ADM", [0, 1, 2, 3, 4])]:
            _ok(hr.post("/api/v1/shifts/schedule/bulk", {"department_id": depts[dept], "shift_code": code, "start_date": start.isoformat(),
                                                         "end_date": end.isoformat(), "weekdays": wd, "preview": False}))
        rot = _ok(hr.post("/api/v1/shifts/rotations", {"name": "2 kun + 2 tun + 2 dam", "pattern": ["D1", "D1", "N1", "N1", "OFF", "OFF"]}))
        _ok(hr.post(f"/api/v1/shifts/rotations/{rot['id']}/apply", {"department_id": depts["SEX-2"], "team_offsets": {"A": 0, "B": 3},
                                                                     "start_date": start.isoformat(), "end_date": end.isoformat(), "preview": False}))

        # biometric consent + enrolment for ~70% (synthetic frames; DEV provider only)
        pdf = base64.b64encode(b"%PDF-1.4 demo consent form").decode()
        enrolled = 0
        for i, e in enumerate(emps):
            if i % 10 in (3, 7):
                continue
            if i % 10 == 9:
                _ok(hr.post("/api/v1/biometrics/consents", {"employee_id": e["id"], "decision": "declined", "method": "paper_scan",
                                                            "document": pdf, "explained": True, "alt_card_no": f"{50000 + i}",
                                                            "alt_pin": f"{(2468 + i * 13) % 10000:04d}"}))
                e["_card"], e["_pin"] = f"{50000 + i}", f"{(2468 + i * 13) % 10000:04d}"
                continue
            _ok(hr.post("/api/v1/biometrics/consents", {"employee_id": e["id"], "decision": "granted", "method": "paper_scan",
                                                        "document": pdf, "explained": True}))
            r = hr.post("/api/v1/biometrics/enrollments", {"employee_id": e["id"], "frames": frames_for(10_000 + i, 3)})
            if r.status == 201:
                enrolled += 1

        # terminal: registered + activated with a key generated here (simulates device history)
        dev = _ok(admin.post("/api/v1/devices", {"name": "Asosiy darvoza T-1", "type": "terminal", "site_id": site_id,
                                                 "access_point_id": gate1["id"], "direction": "both", "serial": "DEMO-T1"}))
        priv, pub = crypto.generate_device_keys()
        _, enc_pub = crypto.x25519_from_seed(priv)
        act = _ok(_SeedClient(app).post("/api/v1/gateway/activate", {"code": dev["activation_code"], "serial": "DEMO-T1",
                                                                 "public_key": base64.b64encode(pub).decode(),
                                                                 "enc_public_key": base64.b64encode(enc_pub).decode(),
                                                                 "firmware": "1.0.0"}))
        dc = DeviceClient(_SeedClient(app), act["device_id"], priv)
        # a second terminal left un-activated, for `python -m fras_edge activate --code …`
        dev2 = _ok(admin.post("/api/v1/devices", {"name": "Ombor terminali T-2", "type": "terminal", "site_id": site_id,
                                                  "access_point_id": gate2["id"], "direction": "both", "serial": "DEMO-T2"}))

        # attendance history
        with database.tx() as conn:
            sched = {(r["employee_id"], r["work_date"]): r["shift_code"] for r in dbm.all_(
                conn, "SELECT employee_id, work_date, shift_code FROM shift_assignments WHERE tenant_id = ?", (tenant_id,))}
        starts = {"D1": (8 * 60, 17 * 60), "A1": (9 * 60, 18 * 60), "N1": (20 * 60, 32 * 60)}
        batch, seq = [], 0
        today = date.today()
        now_local = datetime.now(TZ)

        def add(emp_id, d, minute, direction, result="accepted", method="face", score=None):
            nonlocal seq
            ts = _local(d, minute)
            if ts > datetime.now(timezone.utc).isoformat():
                return
            seq += 1
            batch.append({"event_id": str(uuid.uuid4()), "seq": seq, "employee_id": emp_id, "direction": direction,
                          "method": method, "result": result,
                          "score": score if score is not None else (round(rnd.uniform(0.62, 0.9), 3) if method == "face" else None),
                          "liveness_score": round(rnd.uniform(0.8, 0.99), 3) if method == "face" else None, "captured_at": ts})

        for back in range(days, -1, -1):
            d = today - timedelta(days=back)
            for i, e in enumerate(emps):
                code = sched.get((e["id"], d.isoformat()))
                if not code:
                    continue
                s0, e0 = starts[code]
                roll = rnd.random()
                if roll < 0.05:
                    continue                                   # absent
                method = "card_pin" if (e["_card"] and i % 10 in (3, 7)) else "face"
                late = rnd.random() < 0.12
                in_m = s0 + (rnd.randint(6, 45) if late else -rnd.randint(1, 25))
                add(e["id"], d, in_m, "in", method=method)
                if back == 0 and now_local.hour * 60 + now_local.minute < e0 + 15:
                    continue                                   # still at work today
                if roll < 0.09:
                    continue                                   # forgot to check out → missing_out anomaly
                out_m = e0 + (rnd.randint(40, 120) if rnd.random() < 0.1 else rnd.randint(0, 20))
                add(e["id"], d, out_m, "out", method=method)
            # a few suspicious attempts
            if back % 4 == 1:
                add(None, d, 8 * 60 + 3, "in", result="unknown", score=0.31)
            if back == 2:
                add(None, d, 7 * 60 + 55, "in", result="pad", score=None)
        batch.sort(key=lambda ev: ev["captured_at"])
        for n, ev in enumerate(batch, start=1):
            ev["seq"] = n
        for k in range(0, len(batch), 400):
            _ok(dc.call("POST", "/api/v1/gateway/events", {"events": batch[k:k + 400]}))
        _ok(dc.call("POST", "/api/v1/gateway/heartbeat", {"firmware": "1.0.0", "health": {"camera_fps": 25, "disk_pct": 31},
                                                          "outbox_size": 0, "gallery_version": 0, "applied_config_version": 0,
                                                          "device_time": datetime.now(timezone.utc).isoformat()}))

        # requests waiting for approval
        e0 = emps[1]
        _ok(hr.post("/api/v1/leaves", {"employee_id": emps[5]["id"], "type": "vacation", "start_date": (today + timedelta(days=10)).isoformat(),
                                       "end_date": (today + timedelta(days=16)).isoformat(), "reason": "Oilaviy ta'til"}))
        _ok(hr.post("/api/v1/leaves", {"employee_id": emps[8]["id"], "type": "sick", "start_date": (today - timedelta(days=3)).isoformat(),
                                       "end_date": (today - timedelta(days=2)).isoformat(), "reason": "Kasallik varaqasi bor"}))
        ops = login("operator@demo.uz")
        yday = today - timedelta(days=1)
        if sched.get((e0["id"], yday.isoformat())) in starts:
            _ok(ops.post("/api/v1/attendance/corrections", {"employee_id": e0["id"], "work_date": yday.isoformat(), "kind": "add_event",
                                                            "new_time": _local(yday, starts[sched[(e0['id'], yday.isoformat())]][1]),
                                                            "direction": "out", "reason_code": "missed_checkout",
                                                            "comment": "Xodim chiqishni qayd qilishni unutgan, usta tasdiqladi"}))

        # employee portal account for the first employee
        portal_emp = emps[0]
        with database.tx() as conn:
            _user(conn, tenant_id, portal_emp["personnel_no"].lower(), f"{portal_emp['last_name']} {portal_emp['first_name']}",
                  "employee", "self", portal_emp["id"], employee_id=portal_emp["id"])

        # ROI baseline for the in-app ROI dashboard
        _ok(admin.put("/api/v1/roi/baseline", {"inputs": {"employees": employees, "payroll_monthly": employees * 350,
                                                          "hr_hour_cost": 4, "hr_hours_now": 60, "fix_hours_now": 25,
                                                          "subscription_monthly": round(employees * 0.75, 2), "devices_cost": 1200,
                                                          "install_cost": 400}}))
        # one support ticket
        _ok(admin.post("/api/v1/support/tickets", {"subject": "Ombor terminalini ulash", "body": "Ikkinchi terminalni qanday faollashtiramiz?",
                                                   "priority": "normal"}))

        card_emp = next(e for e in emps if e["_card"])
        out += [
            "Demo ma'lumotlar yaratildi (hammasi o'ylab topilgan).",
            f"  Xodimlar: {employees}, biometrik ro'yxatdan o'tgan (DEV sintetik): {enrolled}, hodisalar: {len(batch)}",
            "",
            f"Hamma parollar: {PASSWORD}",
            "  Boshqaruv paneli  /app/      tashkilot kodi: demo",
            "    admin@demo.uz (Super Admin), hr@demo.uz (HR menejer), operator@demo.uz (HR operator),",
            "    sex1@demo.uz (bo'lim boshlig'i), smena@demo.uz (smena boshlig'i), security@demo.uz, auditor@demo.uz",
            f"  Xodim portali     /me/       tashkilot: demo, login: {portal_emp['personnel_no'].lower()}",
            "  Platforma         /platform/ owner@fras.local",
            "  ROI kalkulyatori  /roi",
            "  Terminal (demo)   /terminal/",
            "",
            f"Ikkinchi terminal faollashtirish kodi: {dev2['activation_code']}",
            f"  python -m fras_edge --server {settings.public_base_url} activate --code {dev2['activation_code']}",
            f"Karta/PIN namunasi: karta {card_emp['_card']}, PIN {card_emp['_pin']} ({card_emp['last_name']} {card_emp['first_name']})",
        ]
        return out
    finally:
        settings.relax_mfa = relax
