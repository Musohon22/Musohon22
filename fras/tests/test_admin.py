"""Import, settings, platform panel, integrations, backups."""


from fras.security import passwords
from fras.util import new_id, now_iso
from tests.helpers import PASSWORD, Client, FrasTestCase


def multipart(field: str, filename: str, content: bytes) -> tuple[bytes, str]:
    boundary = "----frasboundary"
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{field}\"; filename=\"{filename}\"\r\n"
            f"Content-Type: application/octet-stream\r\n\r\n").encode() + content + f"\r\n--{boundary}--\r\n".encode()
    return body, f"multipart/form-data; boundary={boundary}"


class ImportTests(FrasTestCase):
    def test_csv_import_preview_apply_idempotent(self):
        self.make_org()
        csv = ("personnel_no,last_name,first_name,site_code,department_code,hire_date,team\n"
               "A-1,Karimov,Akmal,Z1,SEX-1,2025-01-01,A\n"
               "A-2,Valiyeva,Dilnoza,Z1,SEX-2,2025-02-01,B\n"
               "A-3,Bad,Row,NOPE,SEX-1,2025-02-01,B\n"
               "A-1,Karimov,Akmal,Z1,SEX-1,2025-01-01,A\n").encode()
        body, ctype = multipart("file", "staff.csv", csv)
        r = self.hr.request("POST", "/api/v1/employees/imports", raw=body, content_type=ctype)
        self.assertEqual(r.status, 201, r)
        s = r.json()["summary"]
        self.assertEqual((s["new"], s["error"]), (2, 2))
        ap = self.hr.post(f"/api/v1/employees/imports/{r.json()['id']}/apply")
        self.assertEqual(ap.json()["created"], 2)
        self.assertEqual(self.hr.post(f"/api/v1/employees/imports/{r.json()['id']}/apply").status, 409)
        r2 = self.hr.request("POST", "/api/v1/employees/imports", raw=body, content_type=ctype)
        self.assertEqual(r2.json()["summary"]["new"], 0)        # same file again: nothing new
        tpl = self.hr.get("/api/v1/employees/import-template")
        self.assertEqual(tpl.status, 200)
        self.assertTrue(tpl.body[:2] == b"PK")


class SettingsTests(FrasTestCase):
    def test_versioned_settings_and_floors(self):
        r = self.hr.put("/api/v1/settings/attendance_rules", {"value": {"debounce_min": 3}})
        self.assertEqual(r.status, 200, r)
        self.assertEqual(r.json()["version"], 1)
        self.assertEqual(self.hr.get("/api/v1/settings/attendance_rules").json()["value"]["debounce_min"], 3)
        self.assertEqual(self.hr.put("/api/v1/settings/attendance_rules", {"value": {"nope": 1}}).status, 422)
        low = self.admin.put("/api/v1/settings/retention", {"value": {"events_days": 30}})
        self.assertEqual(low.json()["error"]["code"], "RETENTION_BELOW_FLOOR")
        weak = self.admin.put("/api/v1/settings/biometric_policy", {"value": {"profile": "lenient"}})
        self.assertEqual(weak.json()["error"]["code"], "SECOND_APPROVAL_REQUIRED")
        strict = self.admin.put("/api/v1/settings/biometric_policy", {"value": {"profile": "strict"}})
        self.assertEqual(strict.status, 200)
        self.assertEqual(len(self.hr.get("/api/v1/settings/attendance_rules/history").json()["items"]), 1)
        sim = self.hr.post("/api/v1/settings/attendance_rules/simulate", {"value": {"debounce_min": 5}, "days": 7})
        self.assertEqual(sim.status, 200, sim)


class PlatformTests(FrasTestCase):
    def setUp(self):
        super().setUp()
        with self.env.db.tx() as conn:
            conn.execute("INSERT INTO platform_users (id, email, name, password_hash, role, status, created_at) "
                         "VALUES (?,?,?,?,?,?,?)", (new_id(), "owner@fras.uz", "Owner", passwords.hash_secret(PASSWORD),
                                                     "owner", "active", now_iso()))
        self.p = Client(self.env.app)
        r = self.p.post("/api/v1/platform/auth/login", {"email": "owner@fras.uz", "password": PASSWORD})
        self.p.token = r.json()["access_token"]

    def test_tenant_lifecycle_and_mrr(self):
        r = self.p.post("/api/v1/platform/tenants", {"slug": "beta", "name": "Beta Tekstil", "plan_code": "business",
                                                     "admin_email": "hr@beta.uz", "admin_name": "Beta HR"})
        self.assertEqual(r.status, 201, r)
        self.assertIn("token=", r.json()["invite_link"])
        dash = self.p.get("/api/v1/platform/dashboard").json()
        self.assertEqual(dash["tenants"], 2)
        self.assertGreater(dash["mrr_cents"], 0)
        tenants = self.p.get("/api/v1/platform/tenants").json()["items"]
        beta = next(t for t in tenants if t["slug"] == "beta")
        card = self.p.get(f"/api/v1/platform/tenants/{beta['id']}").json()
        self.assertIn("health", card)
        self.assertNotIn("employees", card)          # operator sees no employee data
        run = self.p.post("/api/v1/platform/invoices/run").json()
        self.assertGreaterEqual(run["invoices_issued"], 2)
        inv = self.p.get("/api/v1/platform/invoices").json()["items"][0]
        pay = self.p.post(f"/api/v1/platform/invoices/{inv['id']}/payments",
                          {"amount_cents": inv["amount_cents"], "method": "bank_transfer", "reference": "PP-77"})
        self.assertTrue(pay.json()["fully_paid"])
        # tenant tokens are not valid on the platform realm and vice versa
        self.assertEqual(self.admin.get("/api/v1/platform/dashboard").status, 401)
        self.assertEqual(self.p.get("/api/v1/employees").status, 401)

    def test_ticket_and_cancel_feedback(self):
        t = self.admin.post("/api/v1/support/tickets", {"subject": "Terminal ishlamayapti", "body": "Darvoza 2 javob bermaydi",
                                                        "priority": "high"})
        self.assertEqual(t.status, 201, t)
        tickets = self.p.get("/api/v1/platform/tickets").json()["items"]
        self.assertEqual(len(tickets), 1)
        c = self.admin.post("/api/v1/billing/cancel", {"reason": "price", "comment": "qimmat"})
        self.assertEqual(c.status, 200, c)
        churn = self.p.get("/api/v1/platform/churn").json()
        self.assertEqual(churn["reasons"][0]["reason"], "price")


class IntegrationTests(FrasTestCase):
    def test_api_key_scopes(self):
        k = self.admin.post("/api/v1/integrations/api-keys", {"name": "1C", "scopes": ["attendance.read"]})
        self.assertEqual(k.status, 201, k)
        c = Client(self.env.app)
        ok = c.get("/api/v1/attendance/events", headers={"x-api-key": k.json()["key"]})
        self.assertEqual(ok.status, 200, ok)
        self.assertEqual(c.get("/api/v1/employees", headers={"x-api-key": k.json()["key"]}).status, 401)
        self.admin.post(f"/api/v1/integrations/api-keys/{k.json()['id']}/revoke")
        self.assertEqual(c.get("/api/v1/attendance/events", headers={"x-api-key": k.json()["key"]}).status, 401)

    def test_backup_and_restore_test(self):
        b = self.admin.post("/api/v1/system/backups")
        self.assertEqual(b.status, 201, b)
        t = self.admin.post(f"/api/v1/system/backups/{b.json()['id']}/restore-test").json()
        self.assertTrue(t["ok"], t)
        self.assertEqual(t["integrity"], "ok")


