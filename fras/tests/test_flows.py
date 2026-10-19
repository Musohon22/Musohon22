"""End-to-end API flows: devices → events → summaries → corrections → periods → reports; biometrics; billing."""

import base64
import io
import json
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import numpy as np
from PIL import Image, ImageFilter

from fras.security import crypto
from fras.services import billing_svc
from tests.helpers import Client, FrasTestCase

TZ = ZoneInfo("Asia/Tashkent")


def frames_for(seed: int, n: int = 3, still: bool = False) -> list[str]:
    rng = np.random.default_rng(seed)
    base = Image.fromarray((rng.random((520, 680)) * 255).astype("uint8")).filter(ImageFilter.GaussianBlur(3))
    arr = np.asarray(base).astype(np.float32)
    arr = (arr - arr.mean()) / arr.std() * 40 + 135
    out = []
    for i in range(n):
        shift = 0 if still else i
        a = np.roll(arr, (shift * 2, shift * 3), axis=(0, 1))[20:500, 20:660]
        img = Image.fromarray(np.stack([a, a, a], -1).clip(0, 255).astype("uint8"))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=92)
        out.append("data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode())
    return out


def local(d: date, hm: str) -> str:
    h, m = map(int, hm.split(":"))
    return datetime(d.year, d.month, d.day, h, m, tzinfo=TZ).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


class DeviceFlowTests(FrasTestCase):
    def setUp(self):
        super().setUp()
        self.make_org()
        self.make_shift("D1", "08:00", "17:00")
        self.emp = self.make_employee("A-1001")
        self.day = date.today() - timedelta(days=1)
        self.assign(self.emp["id"], self.day, "D1")
        self.dev = self.make_device()
        self.seq = 0

    def event(self, hm: str, direction: str, result="accepted", day=None, employee=True, **kw):
        self.seq += 1
        return {"event_id": str(uuid.uuid4()), "seq": self.seq,
                "employee_id": self.emp["id"] if employee else None, "direction": direction, "method": "face",
                "result": result, "score": 0.81, "liveness_score": 0.93, "captured_at": local(day or self.day, hm), **kw}

    def test_heartbeat_and_commands(self):
        hb = {"firmware": "1.0.1", "health": {"camera_fps": 25, "disk_pct": 40}, "outbox_size": 0, "gallery_version": 0,
              "applied_config_version": 0, "device_time": datetime.now(timezone.utc).isoformat()}
        r = self.dev.call("POST", "/api/v1/gateway/heartbeat", hb)
        self.assertEqual(r.status, 200, r)
        self.assertEqual(r.json()["status"], "online")
        self.assertIsNotNone(r.json()["config"])
        cmd = self.admin.post(f"/api/v1/devices/{self.device_id}/commands", {"type": "restart", "reason": "kamera qotib qoldi"})
        self.assertEqual(cmd.status, 202, cmd)
        r = self.dev.call("POST", "/api/v1/gateway/heartbeat", hb)
        cmds = r.json()["commands"]
        self.assertEqual([c["type"] for c in cmds], ["restart"])
        ack = self.dev.call("POST", f"/api/v1/gateway/commands/{cmds[0]['id']}/ack", {"status": "acked", "result": {}})
        self.assertEqual(ack.status, 200)
        bad = {**hb, "health": {"camera_fps": 4}}
        self.assertEqual(self.dev.call("POST", "/api/v1/gateway/heartbeat", bad).json()["status"], "degraded")

    def test_signature_and_replay_protection(self):
        r = self.dev.call("POST", "/api/v1/gateway/heartbeat", {"device_time": "x"}, ts=int(time.time()) - 600)
        self.assertEqual(r.json()["error"]["code"], "DEVICE_REPLAY")
        forged = Client(self.env.app).request("POST", "/api/v1/gateway/events", raw=b'{"events":[]}', headers={
            "x-device-id": self.device_id, "x-device-ts": str(int(time.time())), "x-device-sig": base64.b64encode(b"0" * 64).decode()})
        self.assertEqual(forged.json()["error"]["code"], "DEVICE_AUTH_INVALID")
        # activation code is single use
        act = Client(self.env.app).post("/api/v1/gateway/activate", {"code": "AAAAAAAA", "public_key": "x", "enc_public_key": "y"})
        self.assertEqual(act.status, 401)

    def test_events_dedup_and_summary(self):
        batch = [self.event("07:56", "in"), self.event("17:05", "out")]
        r = self.dev.call("POST", "/api/v1/gateway/events", {"events": batch})
        self.assertEqual(r.json()["accepted"], 2, r)
        again = self.dev.call("POST", "/api/v1/gateway/events", {"events": batch})
        self.assertEqual((again.json()["accepted"], again.json()["duplicates"]), (0, 2))
        events = self.hr.get("/api/v1/attendance/events", query={"from": self.day.isoformat()}).json()
        self.assertEqual(events["total"], 2)
        self.assertTrue(all(e["late_arrival"] for e in events["items"]))   # yesterday's events arrive late = offline
        sums = self.hr.get("/api/v1/attendance/daily-summaries",
                           query={"from": self.day.isoformat(), "to": self.day.isoformat()}).json()
        s = sums["days"][self.emp["id"]][self.day.isoformat()]
        self.assertEqual(s["status"], "present")
        self.assertEqual(s["worked_min"], 8 * 60)

    def test_offline_batch_out_of_order_and_clock_suspect(self):
        future = (datetime.now(timezone.utc) + timedelta(hours=3)).isoformat()
        batch = [self.event("17:00", "out"), self.event("08:20", "in"),
                 {**self.event("09:00", "in"), "captured_at": future}]
        r = self.dev.call("POST", "/api/v1/gateway/events", {"events": batch})
        self.assertEqual(r.json()["accepted"], 3)
        s = self.hr.get("/api/v1/attendance/daily-summaries", query={"from": self.day.isoformat(),
                                                                     "to": self.day.isoformat()}).json()
        day = s["days"][self.emp["id"]][self.day.isoformat()]
        self.assertEqual(day["status"], "late")
        self.assertEqual(day["late_min"], 20)
        sus = self.hr.get("/api/v1/attendance/events", query={"from": date.today().isoformat(),
                                                              "to": (date.today() + timedelta(days=1)).isoformat(),
                                                              "tab": "suspicious"}).json()
        self.assertEqual(sus["total"], 1)

    def test_pad_creates_alert_and_unknown_repeat(self):
        self.env.add_user("sec@acme.uz", "security")
        today = date.today()
        batch = [self.event("09:00", "in", result="pad", day=today, employee=False)]
        batch += [self.event(f"09:0{i}", "in", result="unknown", day=today, employee=False) for i in range(1, 4)]
        self.dev.call("POST", "/api/v1/gateway/events", {"events": batch})
        sec = self.env.login("sec@acme.uz")
        kinds = {a["kind"] for a in sec.get("/api/v1/security/alerts").json()["items"]}
        self.assertIn("pad_attempt", kinds)
        self.assertIn("unknown_repeat", kinds)
        notes = sec.get("/api/v1/notifications").json()
        self.assertGreater(notes["unread"], 0)

    def test_correction_maker_checker_and_preview(self):
        self.dev.call("POST", "/api/v1/gateway/events", {"events": [self.event("08:00", "in")]})
        self.env.add_user("op@acme.uz", "hr_operator")
        op = self.env.login("op@acme.uz")
        body = {"employee_id": self.emp["id"], "work_date": self.day.isoformat(), "kind": "add_event",
                "new_time": local(self.day, "17:00"), "direction": "out", "reason_code": "missed_checkout",
                "comment": "Xodim chiqishda kartani unutgan, smena boshlig'i tasdiqladi"}
        prev = op.post("/api/v1/attendance/corrections/preview", body).json()
        self.assertEqual(prev["after"]["worked_min"], 480)
        c = op.post("/api/v1/attendance/corrections", body)
        self.assertEqual(c.status, 201, c)
        cid = c.json()["id"]
        # operator cannot approve; HR manager can
        self.assertEqual(op.post(f"/api/v1/attendance/corrections/{cid}/approve", {}).status, 403)
        queue = self.hr.get("/api/v1/approvals").json()
        self.assertEqual(queue["counts"]["correction"], 1)
        ok = self.hr.post(f"/api/v1/attendance/corrections/{cid}/approve", {"comment": "ok"})
        self.assertEqual(ok.status, 200, ok)
        self.assertEqual(ok.json()["summary"]["status"], "present")
        # raw events untouched (append-only)
        evs = self.hr.get("/api/v1/attendance/events", query={"from": self.day.isoformat()}).json()
        self.assertEqual(evs["total"], 1)

    def test_self_approval_forbidden(self):
        body = {"employee_id": self.emp["id"], "work_date": self.day.isoformat(), "kind": "set_day_status",
                "day_status": "business_trip", "reason_code": "business_task", "comment": "Toshkentga xizmat safari bo'ldi"}
        c = self.hr.post("/api/v1/attendance/corrections", body).json()
        r = self.hr.post(f"/api/v1/attendance/corrections/{c['id']}/approve", {})
        self.assertEqual(r.json()["error"]["code"], "SELF_APPROVAL_FORBIDDEN")

    def test_period_close_locks_and_late_event_flagged(self):
        start = self.day - timedelta(days=self.day.weekday())
        p = self.hr.post("/api/v1/attendance/periods", {"site_id": self.site_id, "start_date": start.isoformat(),
                                                        "end_date": self.day.isoformat()}).json()
        self.hr.post("/api/v1/attendance/corrections", {
            "employee_id": self.emp["id"], "work_date": self.day.isoformat(), "kind": "set_day_status",
            "day_status": "present", "reason_code": "other", "comment": "Ochiq qolgan tuzatish so'rovi"})
        r = self.hr.post(f"/api/v1/attendance/periods/{p['id']}/close", {})
        self.assertEqual(r.json()["error"]["code"], "PERIOD_HAS_OPEN_ITEMS")
        self.assertEqual(r.json()["error"]["details"]["checklist"]["pending_corrections"], 1)
        self.assertEqual(self.hr.post(f"/api/v1/attendance/periods/{p['id']}/close", {"force": True}).json()["error"]["code"],
                         "NOTE_REQUIRED")
        r = self.hr.post(f"/api/v1/attendance/periods/{p['id']}/close", {"force": True, "note": "Test yopish, sababi bor"})
        self.assertEqual(r.status, 200, r)
        body = {"employee_id": self.emp["id"], "work_date": self.day.isoformat(), "kind": "set_day_status",
                "day_status": "present", "reason_code": "other", "comment": "Yopilgan davrga tuzatish urinish"}
        self.assertEqual(self.hr.post("/api/v1/attendance/corrections", body).json()["error"]["code"], "PERIOD_LOCKED")
        self.dev.call("POST", "/api/v1/gateway/events", {"events": [self.event("08:00", "in")]})
        an = self.hr.get("/api/v1/attendance/anomalies").json()["items"]
        self.assertIn("late_event_after_close", [a["kind"] for a in an])
        # reopen needs a second HR manager
        rq = self.hr.post(f"/api/v1/attendance/periods/{p['id']}/reopen-request", {"reason": "Kechikkan hodisalar keldi"})
        self.assertEqual(rq.status, 200)
        self.assertEqual(self.hr.post(f"/api/v1/attendance/periods/{p['id']}/reopen-approve").status, 403)
        self.env.add_user("hr2@acme.uz", "hr_manager")
        hr2 = self.env.login("hr2@acme.uz")
        self.assertEqual(hr2.post(f"/api/v1/attendance/periods/{p['id']}/reopen-approve").status, 200)

    def test_reports_and_export(self):
        self.dev.call("POST", "/api/v1/gateway/events", {"events": [self.event("08:15", "in"), self.event("17:00", "out")]})
        r = self.hr.post("/api/v1/reports/run", {"type": "lateness", "params": {"from": self.day.isoformat(),
                                                                                 "to": self.day.isoformat()}})
        self.assertEqual(r.status, 200, r)
        self.assertEqual(r.json()["rows"][0][4], 15)
        ts = self.hr.post("/api/v1/reports/run", {"type": "timesheet", "params": {"month": self.day.strftime("%Y-%m")}}).json()
        self.assertIn(str(self.day.day), ts["columns"])
        for fmt in ("xlsx", "csv", "pdf"):
            ex = self.hr.post("/api/v1/reports/export", {"type": "payroll", "format": fmt,
                                                         "params": {"from": self.day.isoformat(), "to": self.day.isoformat()}})
            self.assertEqual(ex.status, 202, ex)
            eid = ex.json()["export_id"]
            for _ in range(50):
                st = self.hr.get(f"/api/v1/exports/{eid}").json()["status"]
                if st != "running":
                    break
                time.sleep(0.05)
            self.assertEqual(st, "ready")
            dl = self.hr.get(f"/api/v1/exports/{eid}/download")
            self.assertEqual(dl.status, 200)
            self.assertGreater(len(dl.body), 100)
        audit = self.admin.get("/api/v1/audit", query={"action": "report.exported"}).json()
        self.assertEqual(audit["total"], 3)

    def test_leave_and_absence(self):
        lv = self.hr.post("/api/v1/leaves", {"employee_id": self.emp["id"], "type": "vacation",
                                             "start_date": self.day.isoformat(), "end_date": self.day.isoformat(),
                                             "reason": "Oilaviy sabab"})
        self.assertEqual(lv.status, 201, lv)
        self.env.add_user("bb@acme.uz", "dept_head", "department", self.dept1)
        bb = self.env.login("bb@acme.uz")
        self.assertEqual(bb.post(f"/api/v1/leaves/{lv.json()['id']}/approve", {}).status, 200)
        s = self.hr.get("/api/v1/attendance/daily-summaries", query={"from": self.day.isoformat(),
                                                                     "to": self.day.isoformat()}).json()
        self.assertEqual(s["days"][self.emp["id"]][self.day.isoformat()]["status"], "leave")
        over = self.hr.post("/api/v1/leaves", {"employee_id": self.emp["id"], "type": "vacation",
                                               "start_date": (self.day + timedelta(days=30)).isoformat(),
                                               "end_date": (self.day + timedelta(days=60)).isoformat(),
                                               "reason": "Uzun ta'til"})
        self.assertEqual(over.json()["error"]["code"], "LEAVE_BALANCE")

    def test_dashboard_and_feed(self):
        today = date.today()
        self.assign(self.emp["id"], today, "D1")
        self.dev.call("POST", "/api/v1/gateway/events", {"events": [self.event("07:50", "in", day=today)]})
        s = self.hr.get("/api/v1/dashboard/summary").json()
        self.assertEqual(s["kpi"]["arrived"]["value"], 1)
        self.assertEqual(s["kpi"]["in_now"]["value"], 1)
        self.assertEqual(len(self.hr.get("/api/v1/dashboard/feed").json()["items"]), 1)
        self.assertEqual(s["kpi"]["devices"]["online"], 1)

    def test_schedule_rotation_and_conflicts(self):
        self.make_shift("N1", "22:00", "06:00", breaks=[{"floating_min": 30, "paid": False}])
        rot = self.hr.post("/api/v1/shifts/rotations", {"name": "2/2", "pattern": ["D1", "D1", "N1", "N1", "OFF", "OFF"]})
        self.assertEqual(rot.status, 201, rot)
        start = date.today() + timedelta(days=7)
        pv = self.hr.post(f"/api/v1/shifts/rotations/{rot.json()['id']}/apply",
                          {"department_id": self.dept1, "start_date": start.isoformat(),
                           "end_date": (start + timedelta(days=13)).isoformat(), "preview": True}).json()
        self.assertEqual(pv["assignments"], 14)
        # D1 17:00 → N1 22:00 next day is fine; N1 ends 06:00 then D1 08:00 would be a short rest
        r = self.hr.put("/api/v1/shifts/schedule/cell", {"employee_id": self.emp["id"], "work_date": start.isoformat(),
                                                         "shift_code": "N1"})
        self.hr.put("/api/v1/shifts/schedule/cell", {"employee_id": self.emp["id"],
                                                     "work_date": (start + timedelta(days=1)).isoformat(), "shift_code": "D1"})
        grid = self.hr.get("/api/v1/shifts/schedule", query={"from": start.isoformat(),
                                                             "to": (start + timedelta(days=3)).isoformat()}).json()
        self.assertTrue(any(c["kind"] == "short_rest" for c in grid["conflicts"]))
        self.assertEqual(r.status, 200)
        v2 = self.hr.put("/api/v1/shifts/templates/D1", {"code": "D1", "name": "Kunduzgi", "start_time": "08:30",
                                                         "end_time": "17:30", "valid_from": start.isoformat()})
        self.assertEqual(v2.json()["version"], 2)


class BiometricTests(FrasTestCase):
    def setUp(self):
        super().setUp()
        self.make_org()
        self.emp = self.make_employee("A-1001")
        self.emp2 = self.make_employee("A-1002")

    def consent(self, emp_id):
        pdf = base64.b64encode(b"%PDF-1.4 test consent").decode()
        r = self.hr.post("/api/v1/biometrics/consents", {"employee_id": emp_id, "decision": "granted",
                                                         "method": "paper_scan", "document": pdf, "explained": True})
        self.assertEqual(r.status, 201, r)

    def test_consent_required(self):
        r = self.hr.post("/api/v1/biometrics/enrollments", {"employee_id": self.emp["id"], "frames": frames_for(1)})
        self.assertEqual(r.json()["error"]["code"], "CONSENT_REQUIRED")

    def test_enroll_quality_and_gallery(self):
        self.consent(self.emp["id"])
        q = self.hr.post("/api/v1/biometrics/quality", {"frame": frames_for(1)[0]}).json()
        self.assertTrue(q["ok"], q)
        r = self.hr.post("/api/v1/biometrics/enrollments", {"employee_id": self.emp["id"], "frames": frames_for(1)})
        self.assertEqual(r.status, 201, r)
        self.assertEqual(r.json()["status"], "active")
        self.assertTrue(r.json()["provider_dev"])
        prof = self.hr.get(f"/api/v1/employees/{self.emp['id']}").json()["biometric"]["profile"]
        self.assertEqual(prof["status"], "active")
        # gallery package decrypts only with the device key and carries no full names
        dev = self.make_device()
        pkg = dev.call("GET", "/api/v1/gateway/gallery").json()
        _, _ = crypto.x25519_from_seed(self.device_seed)
        priv, _ = crypto.x25519_from_seed(self.device_seed)
        data = json.loads(crypto.open_device_package(priv, pkg["package"]))
        person = next(p for p in data["people"] if p["employee_id"] == self.emp["id"])
        self.assertIsNotNone(person["template"])
        self.assertTrue(person["name"].endswith("."))
        self.assertIn("accept", data["thresholds"])

    def test_photo_attack_rejected_and_alerted(self):
        self.consent(self.emp["id"])
        r = self.hr.post("/api/v1/biometrics/enrollments", {"employee_id": self.emp["id"], "frames": frames_for(1, still=True)})
        self.assertEqual(r.json()["error"]["code"], "ENR-E20")
        with self.env.db.tx() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) AS n FROM security_alerts WHERE kind = 'pad_attempt'").fetchone()["n"], 1)
            self.assertEqual(conn.execute("SELECT COUNT(*) AS n FROM biometric_profiles").fetchone()["n"], 0)

    def test_duplicate_face_goes_to_review(self):
        self.consent(self.emp["id"])
        self.consent(self.emp2["id"])
        self.hr.post("/api/v1/biometrics/enrollments", {"employee_id": self.emp["id"], "frames": frames_for(5)})
        r = self.hr.post("/api/v1/biometrics/enrollments", {"employee_id": self.emp2["id"], "frames": frames_for(5)})
        self.assertEqual(r.json()["status"], "review")
        self.assertNotIn("matched", json.dumps(r.json()))      # operator does not learn who it matched
        self.env.add_user("sec@acme.uz", "security")
        sec = self.env.login("sec@acme.uz")
        reviews = sec.get("/api/v1/biometrics/reviews").json()["items"]
        self.assertEqual(len(reviews), 1)
        d = sec.post(f"/api/v1/biometrics/reviews/{reviews[0]['id']}/decide",
                     {"decision": "same_person", "comment": "Bir odam ikki tabel"})
        self.assertEqual(d.status, 200)
        dups = self.hr.get("/api/v1/employees/duplicates").json()["items"]
        self.assertEqual(dups[0]["reason"], "face")

    def test_revoke_and_withdraw(self):
        self.consent(self.emp["id"])
        self.hr.post("/api/v1/biometrics/enrollments", {"employee_id": self.emp["id"], "frames": frames_for(1)})
        bad = self.hr.post(f"/api/v1/biometrics/profiles/{self.emp['id']}/revoke", {"reason": "wrong_profile", "confirm": "ha"})
        self.assertEqual(bad.json()["error"]["code"], "CONFIRMATION_REQUIRED")
        ok = self.hr.post(f"/api/v1/biometrics/profiles/{self.emp['id']}/revoke",
                          {"reason": "wrong_profile", "confirm": "O'CHIRISH"})
        self.assertEqual(ok.status, 200)
        with self.env.db.tx() as conn:
            row = conn.execute("SELECT template_enc FROM biometric_profiles").fetchone()
        self.assertIsNone(row["template_enc"])     # crypto-erased

    def test_declined_consent_requires_alternative(self):
        r = self.hr.post("/api/v1/biometrics/consents", {"employee_id": self.emp["id"], "decision": "declined",
                                                         "method": "e_signature", "explained": True})
        self.assertEqual(r.json()["error"]["code"], "ALT_METHOD_REQUIRED")
        r = self.hr.post("/api/v1/biometrics/consents", {"employee_id": self.emp["id"], "decision": "declined",
                                                         "method": "e_signature", "explained": True,
                                                         "alt_card_no": "CARD-77", "alt_pin": "4826"})
        self.assertEqual(r.status, 201, r)
        emp = self.hr.get(f"/api/v1/employees/{self.emp['id']}").json()
        self.assertEqual(emp["biometric_status"], "declined")
        self.assertTrue(emp["has_pin"])


class PortalTests(FrasTestCase):
    def test_employee_portal_dispute_flow(self):
        self.make_org()
        self.make_shift()
        emp = self.make_employee("A-1001")
        day = date.today() - timedelta(days=1)
        self.assign(emp["id"], day, "D1")
        grant = self.hr.post(f"/api/v1/employees/{emp['id']}/portal-access")
        self.assertEqual(grant.status, 201, grant)
        tok = grant.json()["activation_link"].split("token=")[1]
        Client(self.env.app).post("/api/v1/auth/accept-invite", {"org": "acme", "token": tok, "password": "Xodim-Parol-2026"})
        me = self.env.login("a-1001", password="Xodim-Parol-2026")
        self.assertEqual(me.get("/api/v1/portal/home").status, 200)
        self.assertEqual(me.get("/api/v1/employees").status, 403)   # no admin access
        att = me.get("/api/v1/portal/attendance").json()
        self.assertTrue(any(d["can_dispute"] for d in att["days"]))
        d = me.post("/api/v1/portal/disputes", {"work_date": day.isoformat(), "kind": "set_day_status",
                                                 "day_status": "business_trip", "comment": "Men xizmat safarida edim"})
        self.assertEqual(d.status, 201, d)
        q = self.hr.get("/api/v1/approvals").json()
        self.assertEqual(q["counts"]["dispute"], 1)
        self.assertEqual(self.hr.post(f"/api/v1/attendance/corrections/{d.json()['id']}/approve", {}).status, 200)
        notes = me.get("/api/v1/notifications").json()
        self.assertGreater(notes["unread"], 0)
        lv = me.post("/api/v1/portal/leaves", {"type": "sick", "start_date": date.today().isoformat(),
                                               "end_date": date.today().isoformat(), "reason": "Kasal"})
        self.assertEqual(lv.status, 201, lv)
        self.assertEqual(me.get("/api/v1/portal/hours.pdf").status, 200)


class BillingTests(FrasTestCase):
    plan = "business"

    def test_dunning_never_blocks_attendance(self):
        self.make_org()
        self.make_shift()
        emp = self.make_employee("A-1001")
        dev = self.make_device()
        with self.env.db.tx() as conn:
            sub = billing_svc.current_subscription(conn, self.env.tenant_id)
            inv = billing_svc.issue_invoice(conn, sub, date.today() - timedelta(days=40), date.today())
            conn.execute("UPDATE invoices SET due_at = ? WHERE id = ?",
                         ((datetime.now(timezone.utc) - timedelta(days=35)).isoformat(), inv["id"]))
            self.assertEqual(billing_svc.reconcile_status(conn, self.env.tenant_id), "suspended")
        r = self.hr.post("/api/v1/employees", {"personnel_no": "B-1", "last_name": "Test", "first_name": "Test",
                                               "site_id": self.site_id, "department_id": self.dept1,
                                               "hire_date": "2025-01-01"})
        self.assertEqual(r.status, 402)
        ev = {"event_id": str(uuid.uuid4()), "seq": 1, "employee_id": emp["id"], "direction": "in", "method": "face",
              "result": "accepted", "score": 0.8, "liveness_score": 0.9,
              "captured_at": datetime.now(timezone.utc).isoformat()}
        self.assertEqual(dev.call("POST", "/api/v1/gateway/events", {"events": [ev]}).json()["accepted"], 1)
        self.assertEqual(self.hr.get("/api/v1/attendance/events").status, 200)          # reading works
        self.assertEqual(self.admin.post("/api/v1/system/full-export").status, 200)    # export always open
        with self.env.db.tx() as conn:
            billing_svc.record_payment(conn, dict(inv), inv["amount_cents"], "bank_transfer", "PP-1", "test")
            self.assertEqual(billing_svc.current_subscription(conn, self.env.tenant_id)["status"], "active")

    def test_plan_limits(self):
        self.make_org()
        with self.env.db.tx() as conn:
            conn.execute("UPDATE plans SET limits = json_set(limits, '$.devices', 0) WHERE code = 'business'")
        r = self.admin.post("/api/v1/devices", {"name": "T-9", "type": "terminal", "site_id": self.site_id,
                                                "access_point_id": self.ap_id})
        self.assertEqual(r.json()["error"]["code"], "PLAN_LIMIT")

    def test_roi_public_calculator(self):
        c = Client(self.env.app)
        body = {"employees": 500, "payroll_monthly": 200000, "hr_hour_cost": 4, "hr_hours_now": 60, "fix_hours_now": 25,
                "leakage_pct_now": 0.5, "other_costs_now": 100, "subscription_monthly": 450, "devices_cost": 3600,
                "install_cost": 1200, "integration_cost": 1500}
        r = c.post("/api/v1/public/roi/calculate", body).json()
        self.assertAlmostEqual(r["net_saving_monthly"], 677, delta=1)
        self.assertAlmostEqual(r["payback_months"], 9.3, delta=0.1)
        self.assertEqual(len(r["assumptions"]), 4)
        no_leak = c.post("/api/v1/public/roi/calculate", {**body, "leakage_pct_now": None}).json()
        self.assertTrue(no_leak["excluded"])
        self.assertEqual(no_leak["verdict"], "does_not_pay_back")
