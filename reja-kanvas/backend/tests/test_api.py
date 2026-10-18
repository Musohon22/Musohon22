import os
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

_TMP = tempfile.mkdtemp(prefix="reja-test-")
os.environ["REJA_DATA_DIR"] = _TMP
os.environ["REJA_SECRET_KEY"] = "test-secret"

from starlette.testclient import TestClient  # noqa: E402

from app import config, db, timeutil  # noqa: E402
from app.main import create_app  # noqa: E402
from app.stats import streak  # noqa: E402

config.JOB_INTERVAL_SECONDS = 0
NOON = datetime(2026, 10, 14, 7, 0, tzinfo=timezone.utc)  # Wednesday 12:00 in Tashkent

PDF = b"%PDF-1.4\n%test\n"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


class ApiTest(unittest.TestCase):
    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(_TMP, ignore_errors=True)

    def setUp(self):
        for path in (config.DB_PATH, config.UPLOAD_DIR):
            if path.is_dir():
                shutil.rmtree(path)
            elif path.exists():
                path.unlink()
        timeutil.freeze(NOON)
        self.client = TestClient(create_app(), raise_server_exceptions=True)
        self.client.__enter__()
        self.ali = self.register("ali@example.com", "Ali")
        self.aziza = self.register("aziza@example.com", "Aziza")
        self.bobur = self.register("bobur@example.com", "Bobur")

    def tearDown(self):
        self.client.__exit__(None, None, None)
        timeutil.freeze(None)

    # helpers -------------------------------------------------------------------------
    def register(self, email, name):
        r = self.client.post("/api/auth/register", json={"email": email, "name": name, "password": "parol12345"})
        self.assertEqual(r.status_code, 201, r.text)
        body = r.json()
        return {"id": body["user"]["id"], "h": {"Authorization": f"Bearer {body['token']}"}}

    def req(self, who, method, path, expect=200, **kw):
        r = self.client.request(method, path, headers=who["h"], **kw)
        self.assertEqual(r.status_code, expect, f"{method} {path}: {r.text}")
        return r.json() if r.content else None

    def plan(self, who=None, **fields):
        body = {"title": "Taqdimot", **fields}
        return self.req(who or self.ali, "POST", "/api/plans", 201, json=body)

    def run_jobs(self):
        from app import workflow
        with db.session() as conn:
            return workflow.run_jobs(conn)

    # auth ------------------------------------------------------------------------------
    def test_auth_errors(self):
        r = self.client.post("/api/auth/register", json={"email": "ALI@example.com", "name": "x", "password": "parol12345"})
        self.assertEqual(r.json()["error"], "email_taken")
        r = self.client.post("/api/auth/login", json={"email": "ali@example.com", "password": "notright"})
        self.assertEqual((r.status_code, r.json()["error"]), (401, "bad_credentials"))
        self.assertEqual(self.client.get("/api/plans").json()["error"], "auth_required")
        r = self.client.get("/api/plans", headers={"Authorization": "Bearer junk"})
        self.assertEqual(r.json()["error"], "invalid_token")

    def test_login_rate_limit(self):
        for _ in range(config.LOGIN_MAX_FAILURES):
            self.client.post("/api/auth/login", json={"email": "bobur@example.com", "password": "wrongwrong"})
        r = self.client.post("/api/auth/login", json={"email": "bobur@example.com", "password": "parol12345"})
        self.assertEqual(r.status_code, 429)

    def test_validation(self):
        r = self.client.post("/api/plans", headers=self.ali["h"], json={"title": "x" * 201})
        self.assertEqual(r.status_code, 422)
        self.assertEqual(r.json()["details"][0]["field"], "title")
        r = self.client.post("/api/plans", headers=self.ali["h"], json={"title": "a", "due_at": "2026-10-14T10:00:00"})
        self.assertEqual(r.status_code, 422)
        r = self.client.post("/api/plans", headers=self.ali["h"], content=b"{not json")
        self.assertEqual(r.json()["error"], "bad_json")

    # plans -----------------------------------------------------------------------------
    def test_create_is_idempotent_for_offline_retries(self):
        pid = "7d3c2a64-8a8e-4c55-9d7a-0c1b8c3b9b11"
        a = self.plan(id=pid, steps=["bir", "ikki"])
        b = self.req(self.ali, "POST", "/api/plans", 201, json={"id": pid, "title": "Taqdimot"})
        self.assertEqual(a["id"], b["id"])
        self.assertEqual(len(self.req(self.ali, "GET", "/api/plans")["plans"]), 1)
        # someone else cannot hijack that id
        r = self.client.post("/api/plans", headers=self.aziza["h"], json={"id": pid, "title": "x"})
        self.assertEqual(r.json()["error"], "id_taken")

    def test_strangers_get_404(self):
        p = self.plan()
        self.req(self.bobur, "GET", f"/api/plans/{p['id']}", 404)
        self.req(self.bobur, "PATCH", f"/api/plans/{p['id']}", 404, json={"base_version": 1, "title": "x"})
        self.req(self.bobur, "GET", "/api/plans/not-a-uuid", 404)

    def test_html_is_sanitized(self):
        dirty = (
            '<p onclick="x()">Salom <script>alert(1)</script><b>qalin</b>'
            '<a href="javascript:alert(1)">yomon</a><a href="https://ok.uz" target="x">ok</a>'
            '<span style="color: #f00; position: fixed">rang</span><img src=x onerror=alert(1)></p>'
            '<ul data-type="taskList"><li data-type="taskItem" data-checked="true"><label><input type="checkbox" checked></label><div><p>t</p></div></li></ul>'
        )
        p = self.plan(body_html=dirty)
        body = self.req(self.ali, "GET", f"/api/plans/{p['id']}")["body_html"]
        self.assertNotIn("script", body)
        self.assertNotIn("onclick", body)
        self.assertNotIn("javascript", body)
        self.assertNotIn("<img", body)
        self.assertNotIn("position", body)
        self.assertIn('style="color: #f00"', body)
        self.assertIn('href="https://ok.uz" target="_blank" rel="noopener noreferrer nofollow"', body)
        self.assertIn('<li data-type="taskItem" data-checked="true">', body)
        self.assertIn('<input type="checkbox" checked>', body)

    def test_search_across_scripts(self):
        self.plan(title="O‘qish rejasi")
        self.plan(title="Режа тузиш")
        self.plan(title="Sport")
        titles = lambda q: {p["title"] for p in self.req(self.ali, "GET", "/api/plans", params={"q": q})["plans"]}
        self.assertEqual(titles("oqish"), {"O‘qish rejasi"})
        self.assertEqual(titles("ўқиш"), {"O‘qish rejasi"})
        self.assertEqual(titles("reja"), {"O‘qish rejasi", "Режа тузиш"})

    # concurrent edits ------------------------------------------------------------------
    def test_non_overlapping_edits_merge(self):
        p = self.plan()
        a = self.req(self.ali, "PATCH", f"/api/plans/{p['id']}", json={"base_version": 1, "title": "Yangi nom"})
        self.assertEqual(a["version"], 2)
        # second device still on version 1 edits a different field: merged, no conflict
        b = self.req(self.ali, "PATCH", f"/api/plans/{p['id']}", json={"base_version": 1, "goal": "Shartnoma"})
        self.assertEqual((b["title"], b["goal"], b["version"]), ("Yangi nom", "Shartnoma", 3))

    def test_overlapping_edit_conflicts_with_server_copy(self):
        p = self.plan()
        self.req(self.ali, "PATCH", f"/api/plans/{p['id']}", json={"base_version": 1, "title": "Telefondan"})
        r = self.req(self.ali, "PATCH", f"/api/plans/{p['id']}", 409, json={"base_version": 1, "title": "Kompyuterdan"})
        self.assertEqual(r["error"], "conflict")
        self.assertEqual(r["fields"], ["title"])
        self.assertEqual(r["server"]["title"], "Telefondan")
        # resolving: resend against the server version
        ok = self.req(self.ali, "PATCH", f"/api/plans/{p['id']}", json={"base_version": r["server"]["version"], "title": "Kompyuterdan"})
        self.assertEqual(ok["title"], "Kompyuterdan")
        # sending the same value someone else already saved is not a conflict
        self.req(self.ali, "PATCH", f"/api/plans/{p['id']}", json={"base_version": 1, "title": "Kompyuterdan"})

    def test_position_is_last_write_wins(self):
        p = self.plan()
        self.req(self.ali, "PATCH", f"/api/plans/{p['id']}", json={"base_version": 1, "x": 100, "y": 50})
        out = self.req(self.ali, "PATCH", f"/api/plans/{p['id']}", json={"base_version": 1, "x": 300, "y": 80})
        self.assertEqual((out["x"], out["y"], out["version"]), (300, 80, 1))
        moved = self.req(self.ali, "POST", "/api/plans/batch-move", json={"items": [{"id": p["id"], "x": 1, "y": 2}]})
        self.assertEqual(moved["items"][0]["x"], 1)

    # trash -----------------------------------------------------------------------------
    def test_trash_restore_and_purge(self):
        p = self.plan()
        self.req(self.ali, "DELETE", f"/api/plans/{p['id']}", 204)
        self.assertEqual(self.req(self.ali, "GET", "/api/plans")["plans"], [])
        trash = self.req(self.ali, "GET", "/api/trash")["plans"]
        self.assertEqual(trash[0]["purge_at"], timeutil.to_iso(NOON + timedelta(days=30)))
        self.req(self.ali, "POST", f"/api/plans/{p['id']}/restore")
        self.assertEqual(len(self.req(self.ali, "GET", "/api/plans")["plans"]), 1)
        self.req(self.ali, "DELETE", f"/api/plans/{p['id']}", 204)
        timeutil.freeze(NOON + timedelta(days=31))
        self.assertEqual(self.req(self.ali, "GET", "/api/trash")["plans"], [])
        self.req(self.ali, "POST", f"/api/plans/{p['id']}/restore", 404)

    # completion workflow ---------------------------------------------------------------
    def test_confirm_blocked_until_steps_done_cancelled_steps_ignored(self):
        p = self.plan(steps=["bir", "ikki", "uch"])
        steps = self.req(self.ali, "GET", f"/api/plans/{p['id']}")["steps"]
        r = self.req(self.ali, "POST", f"/api/plans/{p['id']}/submit", 400, json={})
        self.assertEqual((r["error"], r["remaining"]), ("steps_incomplete", 3))
        self.req(self.ali, "PATCH", f"/api/steps/{steps[0]['id']}", json={"status": "done"})
        self.req(self.ali, "PATCH", f"/api/steps/{steps[1]['id']}", json={"status": "done"})
        self.req(self.ali, "PATCH", f"/api/steps/{steps[2]['id']}", json={"status": "cancelled"})
        detail = self.req(self.ali, "GET", f"/api/plans/{p['id']}")
        self.assertEqual(detail["progress"], {"done": 2, "total": 2, "cancelled": 1})
        self.assertEqual(detail["blockers"], [])
        done = self.req(self.ali, "POST", f"/api/plans/{p['id']}/submit", json={"rating": "excellent"})
        self.assertEqual(done["status"], "done")

    def test_late_completion_is_marked(self):
        p = self.plan(due_at=timeutil.to_iso(NOON - timedelta(hours=2, minutes=5)))
        done = self.req(self.ali, "POST", f"/api/plans/{p['id']}/submit", json={})
        self.assertEqual(done["late_minutes"], 125)
        early = self.plan(due_at=timeutil.to_iso(NOON + timedelta(hours=1)))
        self.assertEqual(self.req(self.ali, "POST", f"/api/plans/{early['id']}/submit", json={})["late_minutes"], 0)

    def test_undo_confirmation_and_locking(self):
        p = self.plan()
        self.req(self.ali, "POST", f"/api/plans/{p['id']}/submit", json={})
        r = self.req(self.ali, "PATCH", f"/api/plans/{p['id']}", 409, json={"base_version": 1, "title": "x"})
        self.assertEqual(r["error"], "plan_locked")
        # colour and position still editable on a finished plan
        self.req(self.ali, "PATCH", f"/api/plans/{p['id']}", json={"base_version": 1, "color": "mint", "x": 9})
        back = self.req(self.ali, "POST", f"/api/plans/{p['id']}/reopen", json={"reason": "undo"})
        self.assertEqual((back["status"], back["completed_at"]), ("active", None))
        kinds = [e["kind"] for e in self.req(self.ali, "GET", f"/api/plans/{p['id']}/events")["events"]]
        self.assertEqual(kinds[:3], ["undone", "edited", "completed"])

    def test_proof_required(self):
        p = self.plan(require_proof=True)
        self.assertEqual(self.req(self.ali, "POST", f"/api/plans/{p['id']}/submit", 400, json={})["error"], "proof_required")
        self.req(self.ali, "POST", f"/api/plans/{p['id']}/attachments", 201, files={"file": ("natija.pdf", PDF, "application/pdf")})
        self.assertEqual(self.req(self.ali, "POST", f"/api/plans/{p['id']}/submit", json={})["status"], "done")
        # proof is frozen once confirmed
        r = self.req(self.ali, "POST", f"/api/plans/{p['id']}/attachments", 409, files={"file": ("b.pdf", PDF, "application/pdf")})
        self.assertEqual(r["error"], "plan_locked")

    def test_upload_validation(self):
        p = self.plan()
        up = lambda name, data, expect: self.req(self.ali, "POST", f"/api/plans/{p['id']}/attachments", expect, files={"file": (name, data, "x/y")})
        self.assertEqual(up("virus.exe", b"MZ", 400)["error"], "file_type_not_allowed")
        self.assertEqual(up("fake.pdf", b"<html>", 400)["error"], "file_content_mismatch")
        self.assertEqual(up("empty.png", b"", 400)["error"], "file_empty")
        old = config.MAX_UPLOAD_BYTES
        config.MAX_UPLOAD_BYTES = 40
        try:
            self.assertEqual(up("big.png", PNG + b"\x00" * 64, 413)["error"], "file_too_large")
        finally:
            config.MAX_UPLOAD_BYTES = old
        ok = up("../../etc/rasm.png", PNG, 201)
        self.assertEqual(ok["filename"], "rasm.png")
        r = self.client.get(f"/api/attachments/{ok['id']}", headers=self.ali["h"])
        self.assertEqual((r.status_code, r.content, r.headers["x-content-type-options"]), (200, PNG, "nosniff"))
        self.req(self.bobur, "GET", f"/api/attachments/{ok['id']}", 404)
        self.assertEqual(len(list(config.UPLOAD_DIR.iterdir())), 1)  # rejected uploads leave no files

    def test_approval_flow_with_rejection(self):
        p = self.plan(approver_id=self.aziza["id"])
        sub = self.req(self.ali, "POST", f"/api/plans/{p['id']}/submit", json={"final_note": "Tayyor"})
        self.assertEqual(sub["status"], "pending_approval")
        # the owner cannot approve their own plan, a stranger cannot even see it
        self.assertEqual(self.req(self.ali, "POST", f"/api/plans/{p['id']}/approve", 403)["error"], "not_approver")
        self.req(self.bobur, "POST", f"/api/plans/{p['id']}/approve", 404)
        self.assertEqual(self.req(self.aziza, "GET", "/api/approvals")["plans"][0]["id"], p["id"])
        self.req(self.aziza, "POST", f"/api/plans/{p['id']}/reject", 422, json={"reason": ""})
        ret = self.req(self.aziza, "POST", f"/api/plans/{p['id']}/reject", json={"reason": "3-slayd yo'q"})
        self.assertEqual((ret["status"], ret["return_reason"]), ("returned", "3-slayd yo'q"))
        kinds = [n["kind"] for n in self.req(self.ali, "GET", "/api/notifications")["notifications"]]
        self.assertIn("returned", kinds)
        # fix and resubmit, then approve
        self.req(self.ali, "PATCH", f"/api/plans/{p['id']}", json={"base_version": 1, "goal": "tuzatildi"})
        self.req(self.ali, "POST", f"/api/plans/{p['id']}/submit", json={})
        done = self.req(self.aziza, "POST", f"/api/plans/{p['id']}/approve")
        self.assertEqual(done["status"], "done")
        self.assertEqual(done["approved_by"]["name"], "Aziza")

    def test_withdraw_pending(self):
        p = self.plan(approver_id=self.aziza["id"])
        self.req(self.ali, "POST", f"/api/plans/{p['id']}/submit", json={})
        self.assertEqual(self.req(self.ali, "POST", f"/api/plans/{p['id']}/reopen", json={"reason": "withdraw"})["status"], "active")
        self.assertEqual(self.req(self.aziza, "GET", "/api/approvals")["plans"], [])

    def test_silent_approver_reminder_then_escalation(self):
        p = self.plan(approver_id=self.aziza["id"], backup_approver_id=self.bobur["id"])
        self.req(self.ali, "POST", f"/api/plans/{p['id']}/submit", json={})
        self.assertEqual(self.req(self.bobur, "POST", f"/api/plans/{p['id']}/approve", 403)["error"], "not_escalated_yet")
        timeutil.freeze(NOON + timedelta(hours=25))
        self.assertEqual(self.run_jobs()["reminded"], 1)
        self.assertEqual(self.run_jobs()["reminded"], 0)  # only once
        timeutil.freeze(NOON + timedelta(hours=49))
        self.assertEqual(self.run_jobs()["escalated"], 1)
        self.assertEqual(self.req(self.bobur, "GET", "/api/approvals")["plans"][0]["id"], p["id"])
        owner_kinds = [n["kind"] for n in self.req(self.ali, "GET", "/api/notifications")["notifications"]]
        self.assertIn("approver_silent", owner_kinds)
        self.assertEqual(self.req(self.bobur, "POST", f"/api/plans/{p['id']}/approve")["status"], "done")

    def test_approver_validation(self):
        self.assertEqual(self.req(self.ali, "POST", "/api/plans", 400, json={"title": "x", "approver_id": self.ali["id"]})["error"], "approver_is_owner")
        r = self.req(self.ali, "POST", "/api/plans", 400, json={"title": "x", "approver_id": self.aziza["id"], "backup_approver_id": self.aziza["id"]})
        self.assertEqual(r["error"], "backup_same_as_approver")
        self.assertEqual(self.req(self.ali, "GET", "/api/users/lookup", params={"email": "AZIZA@example.com"})["name"], "Aziza")
        self.req(self.ali, "GET", "/api/users/lookup", 404, params={"email": "ali@example.com"})

    # time ------------------------------------------------------------------------------
    def test_overdue_pile_and_reschedule(self):
        yesterday = NOON - timedelta(days=1)
        a = self.plan(title="A", due_at=timeutil.to_iso(yesterday.replace(hour=4, minute=30)))  # 09:30 Tashkent
        b = self.plan(title="B", due_at=timeutil.to_iso(yesterday))
        c = self.plan(title="C", due_at=timeutil.to_iso(yesterday))
        self.plan(title="Today", due_at=timeutil.to_iso(NOON - timedelta(hours=3)))  # overdue but today: not in pile
        pile = self.req(self.ali, "GET", "/api/plans/overdue")["plans"]
        self.assertEqual([p["title"] for p in pile], ["A", "B", "C"])
        moved = self.req(self.ali, "POST", "/api/plans/reschedule", json={"ids": [a["id"]], "action": "today"})["plans"]
        self.assertEqual(moved[0]["due_at"], "2026-10-14T04:30:00Z")  # same local time, today
        self.req(self.ali, "POST", "/api/plans/reschedule", json={"ids": [b["id"]], "action": "date", "date": "2026-10-20"})
        self.req(self.ali, "POST", "/api/plans/reschedule", json={"ids": [c["id"]], "action": "cancel"})
        self.assertEqual(self.req(self.ali, "GET", "/api/plans/overdue")["plans"], [])
        self.req(self.ali, "POST", "/api/plans/reschedule", 400, json={"ids": [b["id"]], "action": "date"})

    def test_due_reminder_once(self):
        self.plan(due_at=timeutil.to_iso(NOON + timedelta(minutes=50)), remind_minutes=60)
        self.plan(due_at=timeutil.to_iso(NOON + timedelta(hours=5)), remind_minutes=60)
        self.assertEqual(self.run_jobs()["due_reminders"], 1)
        self.assertEqual(self.run_jobs()["due_reminders"], 0)

    def test_stats_respect_user_timezone(self):
        # 20:30 UTC on the 13th is already the 14th in Tashkent (UTC+5)
        self.plan(due_at="2026-10-13T20:30:00Z")
        self.plan(due_at="2026-10-14T10:00:00Z")
        p = self.plan(due_at="2026-10-14T12:00:00Z")
        self.req(self.ali, "POST", f"/api/plans/{p['id']}/submit", json={})
        st = self.req(self.ali, "GET", "/api/stats")
        self.assertEqual((st["today"], st["today_total"], st["today_done"], st["streak"]), ("2026-10-14", 3, 1, 1))
        self.req(self.ali, "PATCH", "/api/me", json={"tz": "America/New_York"})
        self.assertEqual(self.req(self.ali, "GET", "/api/stats")["today"], "2026-10-14")
        self.req(self.ali, "PATCH", "/api/me", 422, json={"tz": "Mars/Base"})

    def test_streak_with_weekly_freeze(self):
        d = lambda n: datetime(2026, 10, n).date()
        self.assertEqual(streak(set(), d(14)), (0, False))
        # today not done yet: streak still counts up to yesterday
        self.assertEqual(streak({d(12), d(13)}, d(14)), (2, False))
        # one missed day this week is forgiven
        self.assertEqual(streak({d(14), d(12), d(11)}, d(14)), (3, True))
        # two missed days in the same week break it (12th and 13th are both in week 42)
        self.assertEqual(streak({d(14), d(11), d(10)}, d(14))[0], 1)
        # misses in different weeks are each forgiven (11th is the Sunday of week 41)
        self.assertEqual(streak({d(14), d(13), d(12), d(10)}, d(14))[0], 4)
        # yesterday and today both missed: streak is over
        self.assertEqual(streak({d(11), d(12)}, d(14))[0], 0)

    # sharing ---------------------------------------------------------------------------
    def test_share_links(self):
        p = self.plan(approver_id=self.aziza["id"])
        view = self.req(self.ali, "POST", f"/api/plans/{p['id']}/shares", 201, json={"role": "view", "expires_in_days": 1})
        edit = self.req(self.ali, "POST", f"/api/plans/{p['id']}/shares", 201, json={"role": "edit"})
        pub = self.client.get(f"/api/shared/{view['token']}").json()
        self.assertEqual(pub["title"], "Taqdimot")
        self.assertNotIn("approver", pub)
        self.assertNotIn("email", str(pub))
        r = self.client.patch(f"/api/shared/{view['token']}", json={"base_version": 1, "title": "x"})
        self.assertEqual(r.json()["error"], "view_only")
        r = self.client.patch(f"/api/shared/{edit['token']}", json={"base_version": 1, "title": "Mehmon tahriri"})
        self.assertEqual(r.json()["title"], "Mehmon tahriri")
        self.req(self.aziza, "DELETE", f"/api/shares/{edit['token']}", 404)  # only the owner revokes
        self.req(self.ali, "DELETE", f"/api/shares/{edit['token']}", 204)
        self.assertEqual(self.client.get(f"/api/shared/{edit['token']}").json()["error"], "share_revoked")
        timeutil.freeze(NOON + timedelta(days=2))
        self.assertEqual(self.client.get(f"/api/shared/{view['token']}").json()["error"], "share_expired")

    # templates & empty state -----------------------------------------------------------
    def test_templates_do_not_overlap_existing_cards(self):
        self.plan(x=40, y=90)
        made = self.req(self.ali, "POST", "/api/templates/student/apply", 201)["plans"]
        self.assertEqual(len(made), 4)
        today_cards = sorted(p["y"] for p in made if p["x"] == 40)
        self.assertGreater(today_cards[0], 90)
        self.assertEqual(today_cards[1] - today_cards[0], 200)
        self.req(self.ali, "POST", "/api/templates/nope/apply", 404)

    def test_health(self):
        self.assertTrue(self.client.get("/api/health").json()["ok"])


if __name__ == "__main__":
    unittest.main()
