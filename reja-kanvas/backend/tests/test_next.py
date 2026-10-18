import hashlib
import hmac
import json
import os
import unittest
from datetime import timedelta

from tests import test_api as base

from app import auth_extra, db, emails, mailer, timeutil, webhooks  # noqa: E402
from app.sanitize import sanitize_html  # noqa: E402

NOON = base.NOON
SIG = "data:image/png;base64," + "iVBORw0KGgo" * 10


class NextTest(unittest.TestCase):
    setUp = base.ApiTest.setUp
    tearDown = base.ApiTest.tearDown
    register = base.ApiTest.register
    req = base.ApiTest.req
    plan = base.ApiTest.plan

    def team_with(self, *members, role="member"):
        team = self.req(self.ali, "POST", "/api/teams", 201, json={"name": "Sotuv"})
        for who, email in members:
            self.req(self.ali, "POST", f"/api/teams/{team['id']}/members", 201, json={"email": email, "role": role})
        board = next(b for b in self.req(self.ali, "GET", "/api/boards")["boards"] if b["team_id"] == team["id"])
        return team, board

    # teams & boards -------------------------------------------------------------------------
    def test_team_board_sharing_and_roles(self):
        team, board = self.team_with((self.aziza, "aziza@example.com"))
        self.req(self.ali, "POST", f"/api/teams/{team['id']}/members", 201, json={"email": "bobur@example.com", "role": "viewer"})
        self.assertIn("team_added", [n["kind"] for n in self.req(self.aziza, "GET", "/api/notifications")["notifications"]])
        p = self.plan(board_id=board["id"], title="Jamoa rejasi")
        # a member sees and edits it, a viewer only sees it, a stranger gets nothing
        self.assertIn(p["id"], [x["id"] for x in self.req(self.aziza, "GET", "/api/plans")["plans"]])
        self.req(self.aziza, "PATCH", f"/api/plans/{p['id']}", json={"base_version": 1, "goal": "birga"})
        self.assertEqual(self.req(self.bobur, "GET", f"/api/plans/{p['id']}")["my_role"], "viewer")
        self.req(self.bobur, "PATCH", f"/api/plans/{p['id']}", 403, json={"base_version": 2, "goal": "x"})
        outsider = self.register("o@example.com", "Olim")
        self.req(outsider, "GET", f"/api/plans/{p['id']}", 404)
        self.req(outsider, "POST", "/api/plans", 404, json={"title": "x", "board_id": board["id"]})
        # members can create on the board; only admins manage it
        self.req(self.aziza, "POST", "/api/plans", 201, json={"title": "Azizaniki", "board_id": board["id"]})
        self.req(self.aziza, "POST", f"/api/teams/{team['id']}/members", 403, json={"email": "o@example.com"})
        # hand the plan over to Aziza, then remove her: her plans return to her own canvas
        out = self.req(self.ali, "POST", f"/api/plans/{p['id']}/assign", json={"user_id": self.aziza["id"]})
        self.assertEqual(out["owner_id"], self.aziza["id"])
        self.req(self.ali, "POST", f"/api/plans/{p['id']}/assign", 400, json={"user_id": outsider["id"]})
        self.req(self.ali, "DELETE", f"/api/teams/{team['id']}/members/{self.aziza['id']}", 204)
        self.assertIsNone(self.req(self.aziza, "GET", f"/api/plans/{p['id']}")["board_id"])
        self.req(self.ali, "GET", f"/api/plans/{p['id']}", 404)
        # the owner cannot be removed; deleting the team keeps everyone's plans
        me = self.req(self.ali, "GET", "/api/me")
        self.assertEqual(self.req(self.ali, "DELETE", f"/api/teams/{team['id']}/members/{me['id']}", 400)["error"], "team_needs_owner")
        self.req(self.ali, "DELETE", f"/api/teams/{team['id']}", 204)
        self.assertEqual(self.req(self.ali, "GET", "/api/teams")["teams"], [])

    def test_personal_boards_and_moving(self):
        b = self.req(self.ali, "POST", "/api/boards", 201, json={"name": "Uy"})
        p = self.plan(board_id=b["id"])
        self.req(self.aziza, "POST", "/api/plans", 404, json={"title": "x", "board_id": b["id"]})
        moved = self.req(self.ali, "POST", f"/api/plans/{p['id']}/move-board", json={"board_id": None})
        self.assertIsNone(moved["board_id"])
        self.req(self.ali, "DELETE", f"/api/boards/{b['id']}", 204)
        self.assertEqual(len(self.req(self.ali, "GET", "/api/plans")["plans"]), 1)

    def test_canvas_items(self):
        it = self.req(self.ali, "POST", "/api/canvas-items", 201, json={"kind": "note", "x": 0, "y": 0, "w": 200, "h": 120, "text": "Eslatma"})
        self.req(self.ali, "PATCH", f"/api/canvas-items/{it['id']}", json={"x": 40, "text": "Yangi"})
        self.assertEqual(self.req(self.ali, "GET", "/api/canvas-items")["items"][0]["text"], "Yangi")
        self.req(self.aziza, "PATCH", f"/api/canvas-items/{it['id']}", 404, json={"x": 1})
        self.assertEqual(self.req(self.aziza, "GET", "/api/canvas-items")["items"], [])
        self.req(self.ali, "DELETE", f"/api/canvas-items/{it['id']}", 204)

    # multi-stage approval & signatures ----------------------------------------------------
    def test_approval_chain_with_signatures(self):
        p = self.plan(approver_id=self.aziza["id"], approval_chain=[self.bobur["id"]])
        self.req(self.ali, "POST", f"/api/plans/{p['id']}/submit", json={"signature": SIG})
        self.assertEqual(self.req(self.bobur, "GET", "/api/approvals")["plans"], [])  # not his turn yet
        self.req(self.bobur, "POST", f"/api/plans/{p['id']}/approve", 403)
        mid = self.req(self.aziza, "POST", f"/api/plans/{p['id']}/approve", json={"signature": SIG})
        self.assertEqual((mid["status"], mid["approval_stage"], mid["current_approver"]["name"]), ("pending_approval", 1, "Bobur"))
        self.assertIn("stage_approved", [n["kind"] for n in self.req(self.ali, "GET", "/api/notifications")["notifications"]])
        self.assertEqual(self.req(self.bobur, "GET", "/api/approvals")["plans"][0]["id"], p["id"])
        done = self.req(self.bobur, "POST", f"/api/plans/{p['id']}/approve")
        self.assertEqual(done["status"], "done")
        self.assertEqual([s["role"] for s in done["signatures"]], ["owner", "stage1"])
        self.req(self.ali, "POST", f"/api/plans/{p['id']}/submit", 422, json={"signature": "data:text/html,<script>"})

    def test_chain_rejection_resets_and_validation(self):
        p = self.plan(approver_id=self.aziza["id"], approval_chain=[self.bobur["id"]])
        self.req(self.ali, "POST", f"/api/plans/{p['id']}/submit", json={})
        self.req(self.aziza, "POST", f"/api/plans/{p['id']}/approve")
        back = self.req(self.bobur, "POST", f"/api/plans/{p['id']}/reject", json={"reason": "Raqamlar xato"})
        self.assertEqual((back["status"], back["approval_stage"]), ("returned", 0))
        bad = lambda body: self.req(self.ali, "POST", "/api/plans", 400, json={"title": "x", **body})["error"]
        self.assertEqual(bad({"approval_chain": [self.bobur["id"]]}), "chain_without_approver")
        self.assertEqual(bad({"approver_id": self.aziza["id"], "approval_chain": [self.aziza["id"]]}), "chain_duplicate")

    # nesting, steps, goals, filters, time, reactions -------------------------------------
    def test_nested_plans(self):
        parent = self.plan(title="Loyiha")
        child = self.plan(title="Bosqich", parent_id=parent["id"])
        r = self.req(self.ali, "POST", f"/api/plans/{parent['id']}/submit", 400, json={})
        self.assertEqual(r["error"], "children_open")
        self.assertEqual(self.req(self.ali, "GET", f"/api/plans/{parent['id']}")["children"][0]["title"], "Bosqich")
        r = self.req(self.ali, "PATCH", f"/api/plans/{parent['id']}", 400, json={"base_version": 1, "parent_id": child["id"]})
        self.assertEqual(r["error"], "parent_cycle")
        self.req(self.ali, "POST", f"/api/plans/{child['id']}/submit", json={})
        self.assertEqual(self.req(self.ali, "POST", f"/api/plans/{parent['id']}/submit", json={})["status"], "done")
        other = self.plan(who=self.aziza)
        self.assertEqual(self.req(self.ali, "POST", "/api/plans", 400, json={"title": "x", "parent_id": other["id"]})["error"], "parent_not_found")

    def test_steps_due_assignee_order(self):
        team, board = self.team_with((self.aziza, "aziza@example.com"))
        p = self.plan(board_id=board["id"], steps=["a", "b", "c"])
        steps = self.req(self.ali, "GET", f"/api/plans/{p['id']}")["steps"]
        s0 = self.req(self.ali, "PATCH", f"/api/steps/{steps[0]['id']}", json={"assignee_id": self.aziza["id"], "due_at": "2026-10-15T05:00:00Z"})
        self.assertEqual((s0["assignee_id"], s0["due_at"]), (self.aziza["id"], "2026-10-15T05:00:00Z"))
        self.assertEqual(self.req(self.aziza, "GET", "/api/my-steps")["steps"][0]["text"], "a")
        self.assertIn("step_assigned", [n["kind"] for n in self.req(self.aziza, "GET", "/api/notifications")["notifications"]])
        self.req(self.ali, "PATCH", f"/api/steps/{steps[1]['id']}", 400, json={"assignee_id": self.bobur["id"]})
        order = [steps[2]["id"], steps[0]["id"], steps[1]["id"]]
        out = self.req(self.ali, "PUT", f"/api/plans/{p['id']}/steps/order", json={"ids": order})
        self.assertEqual([s["id"] for s in out["steps"]], order)
        self.req(self.ali, "PUT", f"/api/plans/{p['id']}/steps/order", 400, json={"ids": order[:2]})

    def test_goals_filters_time_reactions(self):
        g = self.req(self.ali, "POST", "/api/goals", 201, json={"title": "Sotuvni 20% oshirish", "target_date": "2026-12-31"})
        a = self.plan(goal_id=g["id"])
        self.plan(goal_id=g["id"])
        self.req(self.ali, "POST", f"/api/plans/{a['id']}/submit", json={})
        goal = self.req(self.ali, "GET", "/api/goals")["goals"][0]
        self.assertEqual((goal["plans_total"], goal["plans_done"], goal["progress"]), (2, 1, 0.5))
        self.req(self.aziza, "POST", "/api/plans", 400, json={"title": "x", "goal_id": g["id"]})

        f = self.req(self.ali, "POST", "/api/filters", 201, json={"name": "Shoshilinch ish", "query": {"tags": ["Ish"], "priorities": ["urgent"]}})
        self.assertEqual(self.req(self.ali, "GET", "/api/filters")["filters"][0]["query"]["priorities"], ["urgent"])
        self.req(self.aziza, "DELETE", f"/api/filters/{f['id']}", 404)

        b = self.plan(title="Vaqt")
        out = self.req(self.ali, "POST", f"/api/plans/{b['id']}/time-entries", 201, json={"started_at": "2026-10-14T05:00:00Z", "minutes": 45, "note": "uchrashuv"})
        self.assertEqual(out["entries"][0]["seconds"], 2700)
        self.assertEqual(self.req(self.ali, "GET", f"/api/plans/{b['id']}")["tracked_seconds"], 2700)
        self.req(self.ali, "POST", f"/api/plans/{b['id']}/time-entries", 400, json={"started_at": "2026-10-20T05:00:00Z", "minutes": 5})
        self.req(self.aziza, "DELETE", f"/api/time-entries/{out['entries'][0]['id']}", 403)
        self.req(self.ali, "DELETE", f"/api/time-entries/{out['entries'][0]['id']}")
        self.assertEqual(self.req(self.ali, "GET", f"/api/plans/{b['id']}")["tracked_seconds"], 0)

        c = self.req(self.ali, "POST", f"/api/plans/{b['id']}/comments", 201, json={"body": "Zo'r"})
        r = self.req(self.ali, "POST", f"/api/comments/{c['id']}/reactions", json={"emoji": "👍"})
        self.assertEqual(r["reactions"], [{"emoji": "👍", "count": 1, "mine": True}])
        self.assertEqual(self.req(self.ali, "POST", f"/api/comments/{c['id']}/reactions", json={"emoji": "👍"})["reactions"], [])
        self.req(self.aziza, "POST", f"/api/comments/{c['id']}/reactions", 404, json={"emoji": "👍"})
        self.req(self.ali, "POST", f"/api/comments/{c['id']}/reactions", 422, json={"emoji": "💩"})

    # sessions, 2FA, reset, API keys ------------------------------------------------------
    def test_sessions(self):
        r = self.client.post("/api/auth/login", json={"email": "ali@example.com", "password": "parol12345"})
        phone = {"h": {"Authorization": f"Bearer {r.json()['token']}"}}
        sessions = self.req(self.ali, "GET", "/api/me/sessions")["sessions"]
        self.assertEqual(len(sessions), 2)
        other = next(s for s in sessions if not s["current"])
        self.req(self.ali, "DELETE", f"/api/me/sessions/{other['id']}", 204)
        self.assertEqual(self.req(phone, "GET", "/api/me", 401)["error"], "session_revoked")
        self.req(self.ali, "POST", "/api/auth/logout", 204)
        self.req(self.ali, "GET", "/api/me", 401)

    def test_two_factor_login(self):
        secret = self.req(self.ali, "POST", "/api/me/2fa/setup")["secret"]
        self.assertEqual(self.req(self.ali, "POST", "/api/me/2fa/enable", 400, json={"code": "000000"})["error"], "totp_invalid")
        codes = self.req(self.ali, "POST", "/api/me/2fa/enable", json={"code": auth_extra.totp_now(secret)})["recovery_codes"]
        self.assertEqual(len(codes), 8)
        login = lambda **extra: self.client.post("/api/auth/login", json={"email": "ali@example.com", "password": "parol12345", **extra})
        self.assertEqual(login().json()["error"], "totp_required")
        self.assertEqual(login(code="123456").json()["error"], "totp_invalid")
        self.assertEqual(login(code=auth_extra.totp_now(secret)).status_code, 200)
        self.assertEqual(login(code=codes[0]).status_code, 200)
        self.assertEqual(login(code=codes[0]).json()["error"], "totp_invalid")  # recovery codes work once
        self.assertTrue(self.req(self.ali, "GET", "/api/me")["totp_enabled"])
        self.req(self.ali, "POST", "/api/me/2fa/disable", 204, json={"password": "parol12345", "code": auth_extra.totp_now(secret)})
        self.assertEqual(login().status_code, 200)

    def test_password_reset(self):
        mailer.sent.clear()
        self.req({"h": {}}, "POST", "/api/auth/forgot", 204, json={"email": "nobody@example.com"})
        self.assertEqual(mailer.sent, [])  # no account: nothing sent, same answer
        self.req({"h": {}}, "POST", "/api/auth/forgot", 204, json={"email": "ALI@example.com"})
        link = mailer.sent[-1]["text"]
        token = link.split("token=")[1].split()[0]
        self.req({"h": {}}, "POST", "/api/auth/reset", 400, json={"token": "x" * 20, "password": "yangiparol9"})
        self.req({"h": {}}, "POST", "/api/auth/reset", 204, json={"token": token, "password": "yangiparol9"})
        self.req({"h": {}}, "POST", "/api/auth/reset", 400, json={"token": token, "password": "boshqaparol9"})  # single use
        self.req(self.ali, "GET", "/api/me", 401)  # old sessions end
        self.assertEqual(self.client.post("/api/auth/login", json={"email": "ali@example.com", "password": "yangiparol9"}).status_code, 200)
        timeutil.freeze(NOON + timedelta(hours=2))
        self.req({"h": {}}, "POST", "/api/auth/forgot", 204, json={"email": "ali@example.com"})
        late = mailer.sent[-1]["text"].split("token=")[1].split()[0]
        timeutil.freeze(NOON + timedelta(hours=3, minutes=1))
        self.req({"h": {}}, "POST", "/api/auth/reset", 400, json={"token": late, "password": "yangiparol8"})  # expired

    def test_api_keys(self):
        key = self.req(self.ali, "POST", "/api/me/api-keys", 201, json={"name": "Zapier"})
        bot = {"h": {"Authorization": f"Bearer {key['key']}"}}
        self.req(bot, "POST", "/api/plans", 201, json={"title": "API orqali"})
        self.assertEqual(len(self.req(self.ali, "GET", "/api/plans")["plans"]), 1)
        self.assertEqual(self.req(bot, "POST", "/api/me/password", 403, json={"current": "parol12345", "new": "xxxxxxxx"})["error"], "session_required")
        self.req(bot, "GET", "/api/me/api-keys", 403)
        self.assertNotIn("key", self.req(self.ali, "GET", "/api/me/api-keys")["keys"][0])
        self.req(self.ali, "DELETE", f"/api/me/api-keys/{key['id']}", 204)
        self.req(bot, "GET", "/api/plans", 401)

    # webhooks, email, import, files ------------------------------------------------------
    def test_webhooks(self):
        self.assertEqual(self.req(self.ali, "POST", "/api/me/webhooks", 400, json={"url": "http://example.com/x", "events": ["plan.created"]})["error"], "webhook_https_only")
        self.assertEqual(self.req(self.ali, "POST", "/api/me/webhooks", 400, json={"url": "https://127.0.0.1/x", "events": ["plan.created"]})["error"], "webhook_private_address")
        os.environ["REJA_WEBHOOK_ALLOW_PRIVATE"] = "1"
        calls = []
        real_post = webhooks.post
        try:
            hook = self.req(self.ali, "POST", "/api/me/webhooks", 201, json={"url": "http://localhost:9/h", "events": ["plan.created", "plan.completed"]})
            p = self.plan(title="Signal")
            self.req(self.ali, "POST", f"/api/plans/{p['id']}/submit", json={})
            webhooks.post = lambda url, body, headers: calls.append((url, body, headers)) or 500
            self.assertEqual(webhooks.deliver_pending(), 0)
            self.assertEqual(self.req(self.ali, "GET", "/api/me/webhooks")["webhooks"][0]["failures"], 2)
            self.assertEqual(webhooks.deliver_pending(), 0)  # backoff: not retried immediately
            timeutil.freeze(NOON + timedelta(minutes=5))
            webhooks.post = lambda url, body, headers: calls.append((url, body, headers)) or 204
            self.assertEqual(webhooks.deliver_pending(), 2)
            url, body, headers = calls[-1]
            expected = hmac.new(hook["secret"].encode(), f"{headers['X-Reja-Timestamp']}.".encode() + body, hashlib.sha256).hexdigest()
            self.assertEqual(headers["X-Reja-Signature"], "sha256=" + expected)
            self.assertEqual({json.loads(c[1])["event"] for c in calls}, {"plan.created", "plan.completed"})
            self.assertEqual(self.req(self.ali, "GET", "/api/me/webhooks")["webhooks"][0]["failures"], 0)
        finally:
            webhooks.post = real_post
            del os.environ["REJA_WEBHOOK_ALLOW_PRIVATE"]

    def test_email_notifications_quiet_hours_and_digest(self):
        mailer.sent.clear()
        self.plan(approver_id=self.aziza["id"])
        p = self.plan(approver_id=self.aziza["id"], title="Hisobot")
        self.req(self.ali, "POST", f"/api/plans/{p['id']}/submit", json={})
        self.assertEqual(emails.send_pending("http://app"), 0)  # waits 2 minutes (undo window)
        timeutil.freeze(NOON + timedelta(minutes=3))
        self.assertEqual(emails.send_pending("http://app"), 1)
        self.assertIn("Hisobot", mailer.sent[-1]["text"])
        self.assertEqual(emails.send_pending("http://app"), 0)  # never twice
        # quiet hours (Tashkent 12:03 falls inside 12:00–13:00): held back, sent later
        self.req(self.aziza, "PUT", "/api/me/prefs", json={"email_kinds": ["approval_requested"], "quiet_start": "12:00", "quiet_end": "13:00"})
        q = self.plan(approver_id=self.aziza["id"], title="Kechqurun")
        self.req(self.ali, "POST", f"/api/plans/{q['id']}/submit", json={})
        timeutil.freeze(NOON + timedelta(minutes=6))
        self.assertEqual(emails.send_pending("http://app"), 0)
        timeutil.freeze(NOON + timedelta(hours=1, minutes=1))
        self.assertEqual(emails.send_pending("http://app"), 1)
        # morning digest, once a day after 08:00 local
        self.req(self.ali, "PUT", "/api/me/prefs", json={"digest": True})
        self.plan(title="Bugungi", due_at=timeutil.to_iso(NOON + timedelta(hours=5)))
        self.assertEqual(emails.send_digests("http://app"), 1)
        self.assertIn("Bugungi", mailer.sent[-1]["text"])
        self.assertEqual(emails.send_digests("http://app"), 0)

    def test_external_imports(self):
        csv_text = "Nomi,Muddat,Teg,Ustuvorlik,Izoh\nHisobot,15.10.2026 10:00,Ish,yuqori,Choraklik\n,,,,\nBozorlik,2026-10-16,Uy,,\n"
        r = self.req(self.ali, "POST", "/api/import/external", 201, json={"format": "csv", "content": csv_text})
        self.assertEqual(r, {"created": 2, "skipped": 1})
        todoist = "TYPE,CONTENT,DESCRIPTION,PRIORITY,INDENT,AUTHOR,RESPONSIBLE,DATE,DATE_LANG,TIMEZONE\ntask,Report @work,Q3,4,1,,,2026-10-20,en,\ntask,Draft,,1,2,,,,en,\nsection,Ideas,,,,,,,,\n"
        self.req(self.aziza, "POST", "/api/import/external", 201, json={"format": "todoist", "content": todoist})
        plan = self.req(self.aziza, "GET", "/api/plans")["plans"][0]
        self.assertEqual((plan["title"], plan["tag"], plan["priority"], plan["progress"]["total"]), ("Report", "work", "urgent", 1))
        trello = {"cards": [{"id": "c1", "name": "Sayt", "desc": "yangi", "due": "2026-10-21T09:00:00.000Z", "labels": [{"name": "Web"}], "idChecklists": ["k1"]}, {"name": "Eski", "closed": True}],
                  "checklists": [{"id": "k1", "checkItems": [{"name": "Dizayn"}, {"name": "Kod"}]}]}
        self.req(self.bobur, "POST", "/api/import/external", 201, json={"format": "trello", "content": json.dumps(trello)})
        plan = self.req(self.bobur, "GET", "/api/plans")["plans"][0]
        self.assertEqual((plan["title"], plan["due_at"], plan["progress"]["total"]), ("Sayt", "2026-10-21T09:00:00Z", 2))
        self.assertEqual(self.req(self.bobur, "POST", "/api/import/external", 400, json={"format": "trello", "content": "{"})["error"], "import_bad_file")
        self.assertEqual(self.req(self.bobur, "POST", "/api/import/external", 400, json={"format": "csv", "content": "a,b\n1,2"})["error"], "import_no_title_column")

    def test_inline_images(self):
        p = self.plan()
        att = self.req(self.ali, "POST", f"/api/plans/{p['id']}/attachments", 201, data={"inline": "1"}, files={"file": ("r.png", base.PNG, "image/png")})
        self.assertTrue(att["url"].startswith(f"/api/files/{att['id']}?sig="))
        self.assertEqual(self.client.get(att["url"]).content, base.PNG)
        self.assertEqual(self.client.get(f"/api/files/{att['id']}?sig={'0' * 64}").status_code, 404)
        self.req(self.ali, "POST", f"/api/plans/{p['id']}/attachments", 400, data={"inline": "1"}, files={"file": ("a.pdf", base.PDF, "application/pdf")})
        body = f'<p>Rasm:</p><img src="http://localhost:8000{att["url"]}"><img src="https://tracker.example/p.gif">'
        self.assertEqual(sanitize_html(body).count("<img"), 1)
        # inline images are not "proof"
        self.req(self.ali, "PATCH", f"/api/plans/{p['id']}", json={"base_version": 1, "require_proof": True})
        self.assertEqual(self.req(self.ali, "GET", f"/api/plans/{p['id']}")["blockers"], ["proof_required"])

    def test_deleting_account_passes_on_team_and_chain(self):
        team, board = self.team_with((self.aziza, "aziza@example.com"), role="admin")
        p = self.plan(who=self.aziza, approver_id=self.bobur["id"], approval_chain=[self.ali["id"]])
        self.req(self.ali, "DELETE", "/api/me", 204, json={"password": "parol12345"})
        t = self.req(self.aziza, "GET", "/api/teams")["teams"][0]
        self.assertEqual((t["my_role"], len(t["members"])), ("owner", 1))
        self.assertEqual(self.req(self.aziza, "GET", f"/api/plans/{p['id']}")["approval_chain"], [])

    def test_share_view_hides_new_people_fields(self):
        p = self.plan(approver_id=self.aziza["id"], approval_chain=[self.bobur["id"]])
        link = self.req(self.ali, "POST", f"/api/plans/{p['id']}/shares", 201, json={"role": "view"})
        text = json.dumps(self.client.get(f"/api/shared/{link['token']}").json())
        self.assertNotIn("@example.com", text)
        self.assertNotIn(self.bobur["id"], text)


if __name__ == "__main__":
    unittest.main()
