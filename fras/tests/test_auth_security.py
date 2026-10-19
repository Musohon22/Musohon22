"""Authentication, MFA, sessions, RBAC/scope, audit chain, idempotency, tenant isolation."""



from fras.security import totp
from fras.services import tenancy
from tests.helpers import PASSWORD, Client, FrasTestCase


class AuthTests(FrasTestCase):
    def test_bad_password_and_lockout(self):
        c = Client(self.env.app)
        for _ in range(5):
            r = c.post("/api/v1/auth/login", {"org": "acme", "login": "admin@acme.uz", "password": "wrong"})
            self.assertEqual(r.status, 401)
        r = c.post("/api/v1/auth/login", {"org": "acme", "login": "admin@acme.uz", "password": PASSWORD})
        self.assertEqual(r.status, 423, r)
        with self.env.db.tx() as conn:
            alerts = conn.execute("SELECT kind FROM security_alerts").fetchall()
            hist = conn.execute("SELECT COUNT(*) AS n FROM login_history WHERE success = 0").fetchone()["n"]
        self.assertIn("login_failures", [a["kind"] for a in alerts])
        self.assertGreaterEqual(hist, 5)

    def test_unknown_org_and_user_same_error(self):
        c = Client(self.env.app)
        a = c.post("/api/v1/auth/login", {"org": "nope", "login": "x", "password": "y"})
        b = c.post("/api/v1/auth/login", {"org": "acme", "login": "nobody", "password": "y"})
        self.assertEqual(a.json()["error"]["code"], b.json()["error"]["code"])

    def test_mfa_required_for_privileged_role(self):
        self.settings.relax_mfa = False
        r = self.hr.get("/api/v1/employees")
        self.assertEqual(r.status, 403)
        self.assertEqual(r.json()["error"]["code"], "MFA_SETUP_REQUIRED")
        setup = self.hr.post("/api/v1/me/mfa/setup").json()
        r = self.hr.post("/api/v1/me/mfa/enable", {"code": totp.now_code(setup["secret"])})
        self.assertEqual(r.status, 200, r)
        codes = r.json()["backup_codes"]
        self.assertEqual(len(codes), 10)
        # new login now needs the second factor
        c = Client(self.env.app)
        r = c.post("/api/v1/auth/login", {"org": "acme", "login": "hr@acme.uz", "password": PASSWORD})
        self.assertTrue(r.json()["mfa_required"])
        bad = c.post("/api/v1/auth/mfa", {"mfa_token": r.json()["mfa_token"], "code": "000000"})
        self.assertEqual(bad.status, 401)
        ok = c.post("/api/v1/auth/mfa", {"mfa_token": r.json()["mfa_token"], "code": totp.now_code(setup["secret"])})
        self.assertEqual(ok.status, 200)
        c.token = ok.json()["access_token"]
        self.assertEqual(c.get("/api/v1/employees").status, 200)
        # backup code works once
        r = c.post("/api/v1/auth/login", {"org": "acme", "login": "hr@acme.uz", "password": PASSWORD})
        self.assertEqual(c.post("/api/v1/auth/mfa", {"mfa_token": r.json()["mfa_token"], "code": codes[0]}).status, 200)
        r = c.post("/api/v1/auth/login", {"org": "acme", "login": "hr@acme.uz", "password": PASSWORD})
        self.assertEqual(c.post("/api/v1/auth/mfa", {"mfa_token": r.json()["mfa_token"], "code": codes[0]}).status, 401)

    def test_refresh_rotation_and_reuse_detection(self):
        c = Client(self.env.app)
        c.post("/api/v1/auth/login", {"org": "acme", "login": "admin@acme.uz", "password": PASSWORD})
        old_cookie = c.cookies["fras_refresh"]
        self.assertEqual(c.post("/api/v1/auth/refresh").status, 403)   # missing anti-CSRF header
        r = c.post("/api/v1/auth/refresh", headers={"x-requested-with": "fras"})
        self.assertEqual(r.status, 200, r)
        c.token = r.json()["access_token"]
        self.assertEqual(c.get("/api/v1/me").status, 200)
        # replaying the old refresh token is rejected
        c2 = Client(self.env.app)
        c2.cookies["fras_refresh"] = old_cookie
        self.assertEqual(c2.post("/api/v1/auth/refresh", headers={"x-requested-with": "fras"}).status, 401)

    def test_logout_revokes_session(self):
        c = self.env.login("admin@acme.uz")
        self.assertEqual(c.post("/api/v1/auth/logout").status, 200)
        r = c.get("/api/v1/me")
        self.assertEqual(r.status, 401)
        self.assertEqual(r.json()["error"]["code"], "SESSION_REVOKED")

    def test_invite_flow(self):
        r = self.admin.post("/api/v1/users", {"name": "Operator", "email": "op@acme.uz",
                                              "roles": [{"role_code": "hr_operator", "scope_type": "global"}]})
        self.assertEqual(r.status, 201, r)
        tok = r.json()["invite_link"].split("token=")[1]
        self.assertEqual(Client(self.env.app).post("/api/v1/auth/accept-invite",
                                                   {"org": "acme", "token": tok, "password": "short"}).status, 422)
        ok = Client(self.env.app).post("/api/v1/auth/accept-invite", {"org": "acme", "token": tok, "password": PASSWORD})
        self.assertEqual(ok.status, 200)
        self.env.login("op@acme.uz")


class PermissionTests(FrasTestCase):
    def setUp(self):
        super().setUp()
        self.make_org()
        self.e1 = self.make_employee("A-1001", self.dept1, team="A", phone="+998901112233", pinfl="12345678901234")
        self.e2 = self.make_employee("B-2001", self.dept2, team="B")

    def test_super_admin_cannot_edit_employees(self):
        r = self.admin.patch(f"/api/v1/employees/{self.e1['id']}", {"version": 1, "first_name": "Ali"})
        self.assertEqual(r.status, 403)

    def test_scope_and_masking_for_shift_lead(self):
        self.env.add_user("lead@acme.uz", "shift_lead", "team", f"{self.dept1}:A")
        lead = self.env.login("lead@acme.uz")
        items = lead.get("/api/v1/employees").json()["items"]
        self.assertEqual([i["id"] for i in items], [self.e1["id"]])
        self.assertNotIn("phone", items[0])
        self.assertNotIn("pinfl_masked", items[0])
        self.assertEqual(lead.get(f"/api/v1/employees/{self.e2['id']}").status, 403)
        hr_view = self.hr.get(f"/api/v1/employees/{self.e1['id']}").json()
        self.assertEqual(hr_view["pinfl_masked"], "••••••••••1234")
        self.assertNotIn("pinfl", hr_view)

    def test_site_admin_cannot_grant_super_admin(self):
        self.env.add_user("sa2@acme.uz", "site_admin", "site", self.site_id)
        za = self.env.login("sa2@acme.uz")
        r = za.post("/api/v1/users", {"name": "Xodim X", "email": "x@acme.uz",
                                      "roles": [{"role_code": "super_admin", "scope_type": "global"}]})
        self.assertEqual(r.status, 403)
        r = za.post("/api/v1/users", {"name": "Xodim Y", "email": "y@acme.uz",
                                      "roles": [{"role_code": "hr_operator", "scope_type": "global"}]})
        self.assertEqual(r.json()["error"]["code"], "SCOPE_TOO_WIDE")

    def test_last_super_admin_cannot_be_removed(self):
        u = self.admin.get(f"/api/v1/users/{self.env.admin_id}").json()
        r = self.admin.delete(f"/api/v1/users/{self.env.admin_id}/roles/{u['roles'][0]['id']}")
        self.assertEqual(r.json()["error"]["code"], "LAST_SUPER_ADMIN")

    def test_auditor_is_read_only(self):
        self.env.add_user("au@acme.uz", "auditor")
        au = self.env.login("au@acme.uz")
        self.assertEqual(au.get("/api/v1/audit").status, 200)
        self.assertEqual(au.post("/api/v1/employees", {}).status, 403)
        self.assertEqual(au.get("/api/v1/employees").status, 200)

    def test_optimistic_lock(self):
        r1 = self.hr.patch(f"/api/v1/employees/{self.e1['id']}", {"version": 1, "first_name": "Ali"})
        self.assertEqual(r1.status, 200, r1)
        r2 = self.hr.patch(f"/api/v1/employees/{self.e1['id']}", {"version": 1, "first_name": "Vali"})
        self.assertEqual(r2.json()["error"]["code"], "VERSION_CONFLICT")

    def test_duplicate_personnel_number_message(self):
        r = self.hr.post("/api/v1/employees", {"personnel_no": "A-1001", "last_name": "Test", "first_name": "Test",
                                               "site_id": self.site_id, "department_id": self.dept1,
                                               "hire_date": "2025-01-01"})
        self.assertEqual(r.status, 409)
        self.assertIn("A-1001", r.json()["error"]["message"])

    def test_validation_error_shape(self):
        r = self.hr.post("/api/v1/employees", {"personnel_no": "!!", "last_name": "", "first_name": "A",
                                               "site_id": self.site_id, "department_id": self.dept1,
                                               "hire_date": "2025-01-01", "pin": "1234"})
        self.assertEqual(r.status, 422)
        fields = {f["field"] for f in r.json()["error"]["details"]["fields"]}
        self.assertIn("personnel_no", fields)
        self.assertIn("last_name", fields)

    def test_trivial_pin_rejected(self):
        r = self.hr.post("/api/v1/employees", {"personnel_no": "C-1", "last_name": "Test", "first_name": "Test",
                                               "site_id": self.site_id, "department_id": self.dept1,
                                               "hire_date": "2025-01-01", "pin": "1234"})
        self.assertEqual(r.json()["error"]["code"], "PIN_WEAK")


class IntegrityTests(FrasTestCase):
    def test_audit_chain_detects_tampering(self):
        self.make_org()
        ok = self.admin.post("/api/v1/audit/verify").json()
        self.assertTrue(ok["ok"])
        with self.env.db.tx() as conn:
            conn.execute("DROP TRIGGER trg_audit_no_update")
            conn.execute("UPDATE audit_logs SET action = 'tampered' WHERE seq = (SELECT MIN(seq) FROM audit_logs)")
        r = self.admin.post("/api/v1/audit/verify").json()
        self.assertFalse(r["ok"])
        with self.env.db.tx() as conn:
            kinds = [a["kind"] for a in conn.execute("SELECT kind FROM security_alerts").fetchall()]
        self.assertIn("audit_chain_broken", kinds)

    def test_audit_append_only_trigger(self):
        self.make_org()
        import sqlite3
        with self.assertRaises(sqlite3.IntegrityError):
            with self.env.db.tx() as conn:
                conn.execute("DELETE FROM audit_logs")

    def test_idempotency_key(self):
        self.make_org()
        body = {"site_id": self.site_id, "code": "SEX-9", "name": "9-sex"}
        r1 = self.admin.post("/api/v1/org/departments", body, headers={"idempotency-key": "k1"})
        r2 = self.admin.post("/api/v1/org/departments", body, headers={"idempotency-key": "k1"})
        self.assertEqual(r1.status, 201)
        self.assertEqual(r2.status, 201)
        self.assertEqual(r1.json()["id"], r2.json()["id"])
        self.assertEqual(r2.headers.get("idempotent-replay"), "true")
        r3 = self.admin.post("/api/v1/org/departments", {**body, "code": "SEX-8"}, headers={"idempotency-key": "k1"})
        self.assertEqual(r3.json()["error"]["code"], "IDEMPOTENCY_KEY_REUSED")

    def test_tenant_isolation(self):
        self.make_org()
        emp = self.make_employee("A-1")
        with self.env.db.tx() as conn:
            tenancy.create_tenant(conn, self.settings.master_key, slug="other", name="Other", plan_code="business",
                                  admin_email="boss@other.uz", admin_name="Boss", admin_password=PASSWORD)
        other = self.env.login("boss@other.uz", org="other")
        self.assertEqual(other.get(f"/api/v1/employees/{emp['id']}").status, 404)
        self.assertEqual(other.get("/api/v1/org/tree").json()["sites"], [])
        self.assertEqual(other.get("/api/v1/attendance/events", query={"employee_id": emp["id"]}).json()["total"], 0)

    def test_security_headers(self):
        r = self.admin.get("/api/v1/me")
        self.assertEqual(r.headers["x-frame-options"], "DENY")
        self.assertIn("default-src 'self'", r.headers["content-security-policy"])
        self.assertIn("x-request-id", r.headers)



