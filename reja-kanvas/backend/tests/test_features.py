import csv
import io
import json
import unittest
from datetime import datetime, timedelta, timezone

from tests import test_api as base  # sets up the temporary data dir before the app is imported

from app import timeutil  # noqa: E402
from app.quickadd import parse  # noqa: E402
from app.recurrence import next_due  # noqa: E402

NOON = base.NOON  # Wednesday 2026-10-14, 12:00 in Tashkent


class FeatureTest(unittest.TestCase):
    setUp = base.ApiTest.setUp
    tearDown = base.ApiTest.tearDown
    register = base.ApiTest.register
    req = base.ApiTest.req
    plan = base.ApiTest.plan

    # recurrence -------------------------------------------------------------------------
    def test_next_due_rules(self):
        due = datetime(2026, 10, 14, 4, 0, tzinfo=timezone.utc)  # Wed 09:00 Tashkent
        tz = "Asia/Tashkent"
        nd = lambda rule, now=NOON: timeutil.to_iso(next_due(due, rule, tz, now))
        self.assertEqual(nd({"freq": "daily"}), "2026-10-15T04:00:00Z")
        self.assertEqual(nd({"freq": "daily", "interval": 2}), "2026-10-16T04:00:00Z")
        self.assertEqual(nd({"freq": "weekly"}), "2026-10-21T04:00:00Z")
        self.assertEqual(nd({"freq": "weekly", "weekdays": [0, 4]}), "2026-10-16T04:00:00Z")  # Fri
        self.assertEqual(nd({"freq": "weekly", "weekdays": [0, 1]}), "2026-10-19T04:00:00Z")  # next Mon
        self.assertEqual(nd({"freq": "weekly", "interval": 2, "weekdays": [0]}), "2026-10-26T04:00:00Z")
        jan31 = datetime(2026, 1, 31, 4, 0, tzinfo=timezone.utc)
        self.assertEqual(timeutil.to_iso(next_due(jan31, {"freq": "monthly"}, tz, jan31)), "2026-02-28T04:00:00Z")
        # finished very late: skips to the next slot in the future, not one in the past
        self.assertEqual(nd({"freq": "daily"}, NOON + timedelta(days=3)), "2026-10-18T04:00:00Z")
        self.assertIsNone(next_due(due, {"freq": "daily", "until": "2026-10-14"}, tz, NOON))
        # local time survives a DST change
        berlin = datetime(2026, 3, 28, 8, 0, tzinfo=timezone.utc)  # 09:00 CET
        self.assertEqual(timeutil.to_iso(next_due(berlin, {"freq": "daily"}, "Europe/Berlin", berlin)), "2026-03-29T07:00:00Z")

    def test_recurring_plan_spawns_next_and_undo_retracts_it(self):
        p = self.plan(due_at="2026-10-14T04:00:00Z", recurrence={"freq": "daily"}, steps=["a"])
        steps = self.req(self.ali, "GET", f"/api/plans/{p['id']}")["steps"]
        self.req(self.ali, "PATCH", f"/api/steps/{steps[0]['id']}", json={"status": "done"})
        done = self.req(self.ali, "POST", f"/api/plans/{p['id']}/submit", json={})
        nxt = self.req(self.ali, "GET", f"/api/plans/{done['next_occurrence_id']}")
        self.assertEqual((nxt["due_at"], nxt["status"], nxt["series_id"]), ("2026-10-15T04:00:00Z", "active", p["id"]))
        self.assertEqual([s["status"] for s in nxt["steps"]], ["todo"])  # fresh steps
        self.req(self.ali, "POST", f"/api/plans/{p['id']}/reopen", json={"reason": "undo"})
        self.req(self.ali, "GET", f"/api/plans/{nxt['id']}", 404)

    def test_recurring_with_approver_spawns_on_approval(self):
        p = self.plan(due_at="2026-10-14T04:00:00Z", recurrence={"freq": "weekly"}, approver_id=self.aziza["id"])
        sub = self.req(self.ali, "POST", f"/api/plans/{p['id']}/submit", json={})
        self.assertIsNone(sub["next_occurrence_id"])
        done = self.req(self.aziza, "POST", f"/api/plans/{p['id']}/approve")
        self.assertIsNotNone(done["next_occurrence_id"])

    # dependencies -----------------------------------------------------------------------
    def test_dependencies_block_completion_and_reject_cycles(self):
        a, b, c = self.plan(title="A"), self.plan(title="B"), self.plan(title="C")
        self.req(self.ali, "POST", f"/api/plans/{b['id']}/dependencies", 201, json={"blocker_id": a["id"]})
        self.req(self.ali, "POST", f"/api/plans/{c['id']}/dependencies", 201, json={"blocker_id": b["id"]})
        r = self.req(self.ali, "POST", f"/api/plans/{a['id']}/dependencies", 400, json={"blocker_id": c["id"]})
        self.assertEqual(r["error"], "dependency_cycle")
        self.assertEqual(self.req(self.ali, "POST", f"/api/plans/{a['id']}/dependencies", 400, json={"blocker_id": a["id"]})["error"], "dependency_self")
        r = self.req(self.ali, "POST", f"/api/plans/{b['id']}/submit", 400, json={})
        self.assertEqual((r["error"], r["open_blockers"][0]["title"]), ("blocked_by_open", "A"))
        self.assertEqual(self.req(self.ali, "GET", "/api/plans")["plans"][1]["blocked_by"], [a["id"]])
        self.req(self.ali, "POST", f"/api/plans/{a['id']}/submit", json={})
        self.assertEqual(self.req(self.ali, "POST", f"/api/plans/{b['id']}/submit", json={})["status"], "done")
        other = self.plan(who=self.aziza)
        self.req(self.ali, "POST", f"/api/plans/{c['id']}/dependencies", 404, json={"blocker_id": other["id"]})
        self.assertEqual(self.req(self.ali, "DELETE", f"/api/plans/{c['id']}/dependencies/{b['id']}")["blocked_by"], [])

    # comments ---------------------------------------------------------------------------
    def test_comments_mentions_and_permissions(self):
        p = self.plan(approver_id=self.aziza["id"])
        c = self.req(self.ali, "POST", f"/api/plans/{p['id']}/comments", 201, json={"body": "@aziza@example.com qarab chiqing"})
        kinds = [n["kind"] for n in self.req(self.aziza, "GET", "/api/notifications")["notifications"]]
        self.assertEqual(kinds, ["mentioned"])
        # mentioning someone outside the plan does not notify (or reveal) anything
        self.req(self.ali, "POST", f"/api/plans/{p['id']}/comments", 201, json={"body": "@bobur@example.com"})
        self.assertEqual(self.req(self.bobur, "GET", "/api/notifications")["notifications"], [])
        self.req(self.bobur, "POST", f"/api/plans/{p['id']}/comments", 404, json={"body": "salom"})
        self.req(self.aziza, "POST", f"/api/plans/{p['id']}/comments", 201, json={"body": "Ko'rdim"})
        self.assertEqual(len(self.req(self.ali, "GET", f"/api/plans/{p['id']}/comments")["comments"]), 3)
        self.assertEqual(self.req(self.aziza, "PATCH", f"/api/comments/{c['id']}", 403, json={"body": "x"})["error"], "not_author")
        self.assertEqual(self.req(self.ali, "PATCH", f"/api/comments/{c['id']}", json={"body": "tuzatildi"})["body"], "tuzatildi")
        timeutil.freeze(NOON + timedelta(minutes=20))
        self.assertEqual(self.req(self.ali, "PATCH", f"/api/comments/{c['id']}", 409, json={"body": "y"})["error"], "edit_window_passed")
        self.req(self.ali, "DELETE", f"/api/comments/{c['id']}", 204)

    # time tracking ----------------------------------------------------------------------
    def test_timer_one_at_a_time_and_capped(self):
        a, b = self.plan(title="A"), self.plan(title="B")
        self.req(self.ali, "POST", f"/api/plans/{a['id']}/timer/start")
        timeutil.freeze(NOON + timedelta(minutes=25))
        self.req(self.ali, "POST", f"/api/plans/{b['id']}/timer/start")  # stops A
        self.assertEqual(self.req(self.ali, "GET", f"/api/plans/{a['id']}")["tracked_seconds"], 1500)
        timeutil.freeze(NOON + timedelta(days=2))
        out = self.req(self.ali, "POST", f"/api/plans/{b['id']}/timer/stop")
        self.assertEqual(out["booked_seconds"], 12 * 3600)  # forgotten timer is capped
        self.assertIsNone(out["timer_started_at"])
        # submitting stops a running timer
        self.req(self.ali, "POST", f"/api/plans/{a['id']}/timer/start")
        timeutil.freeze(NOON + timedelta(days=2, minutes=10))
        done = self.req(self.ali, "POST", f"/api/plans/{a['id']}/submit", json={})
        self.assertEqual((done["timer_started_at"], done["tracked_seconds"]), (None, 2100))

    # quick add --------------------------------------------------------------------------
    def test_quick_add_parser(self):
        tz = "Asia/Tashkent"
        r = parse("Ertaga 15:00 mijoz bilan uchrashuv #ish !yuqori", tz, NOON)
        self.assertEqual((r["title"], r["due_at"], r["tag"], r["priority"]), ("Mijoz bilan uchrashuv", "2026-10-15T10:00:00Z", "ish", "high"))
        r = parse("Har dushanba soat 9:00 haftalik yig'ilish", tz, NOON)
        self.assertEqual((r["title"], r["due_at"], r["recurrence"]["weekdays"]), ("Haftalik yig'ilish", "2026-10-19T04:00:00Z", [0]))
        r = parse("Завтра в 10:30 позвонить маме !!", tz, NOON)
        self.assertEqual((r["title"], r["due_at"], r["priority"]), ("Позвонить маме", "2026-10-15T05:30:00Z", "high"))
        r = parse("Report 25 October 5pm #work", tz, NOON)
        self.assertEqual((r["title"], r["due_at"]), ("Report", "2026-10-25T12:00:00Z"))
        self.assertEqual(parse("10:00 dars", tz, NOON)["due_at"], "2026-10-15T05:00:00Z")  # 10:00 already passed today
        self.assertEqual(parse("Juma kuni hisobot", tz, NOON)["title"], "Hisobot")
        self.assertEqual(parse("Sotib olish: non, sut", tz, NOON)["due_at"], None)
        self.assertEqual(parse("31.02 xato sana", tz, NOON)["due_at"], None)
        api = self.req(self.ali, "POST", "/api/parse", json={"text": "bugun kechqurun kitob"})
        self.assertEqual(api["title"], "Kitob")

    # duplicate, templates, archive ------------------------------------------------------
    def test_duplicate_template_archive(self):
        p = self.plan(title="Hisobot", steps=["a", "b"], priority="urgent")
        copy = self.req(self.ali, "POST", f"/api/plans/{p['id']}/duplicate", 201)
        self.assertEqual((copy["title"], copy["priority"], len(copy["steps"])), ("Hisobot (2)", "urgent", 2))
        t = self.req(self.ali, "POST", f"/api/plans/{p['id']}/save-template", 201, json={"name": "Oylik hisobot"})
        listing = self.req(self.ali, "GET", "/api/templates")
        self.assertEqual(listing["mine"][0]["name"], "Oylik hisobot")
        made = self.req(self.ali, "POST", f"/api/templates/{t['key']}/apply", 201)["plans"]
        self.assertEqual(made[0]["title"], "Hisobot")
        self.req(self.aziza, "POST", f"/api/templates/{t['key']}/apply", 404)  # templates are private
        self.req(self.ali, "DELETE", f"/api/templates/{t['key']}", 204)
        self.assertEqual(self.req(self.ali, "POST", f"/api/plans/{p['id']}/archive", 409)["error"], "archive_open_plan")
        self.req(self.ali, "POST", f"/api/plans/{copy['id']}/cancel")
        self.req(self.ali, "POST", f"/api/plans/{copy['id']}/archive")
        ids = [x["id"] for x in self.req(self.ali, "GET", "/api/plans")["plans"]]
        self.assertNotIn(copy["id"], ids)
        self.assertEqual([x["id"] for x in self.req(self.ali, "GET", "/api/plans", params={"archived": "1"})["plans"]], [copy["id"]])

    # analytics --------------------------------------------------------------------------
    def test_analytics(self):
        on_time = self.plan(tag="Ish", due_at=timeutil.to_iso(NOON + timedelta(hours=1)))
        late = self.plan(tag="Ish", due_at=timeutil.to_iso(NOON - timedelta(hours=2)))
        self.plan(tag="Uy")
        self.req(self.ali, "POST", f"/api/plans/{on_time['id']}/submit", json={})
        self.req(self.ali, "POST", f"/api/plans/{late['id']}/submit", json={})
        a = self.req(self.ali, "GET", "/api/analytics", params={"days": "7"})
        self.assertEqual(len(a["series"]), 7)
        self.assertEqual(a["series"][-1], {"date": "2026-10-14", "done": 2, "created": 3})
        self.assertEqual((a["on_time"], a["late"], a["on_time_rate"], a["avg_late_minutes"]), (1, 1, 0.5, 120))
        self.assertEqual(a["weekday_done"][2], 2)  # Wednesday
        self.assertEqual(a["by_tag"][0], {"tag": "Ish", "done": 2, "open": 0})

    # export / import / calendar ---------------------------------------------------------
    def test_export_import_roundtrip(self):
        self.plan(title="=HYPERLINK(\"x\")", steps=["bir"], body_html="<p>Salom</p>")
        self.plan(title="Режа", tag="Uy", recurrence={"freq": "daily"}, due_at="2026-10-15T04:00:00Z")
        r = self.client.get("/api/export.csv", headers=self.ali["h"])
        rows = list(csv.reader(io.StringIO(r.text.lstrip("﻿"))))
        self.assertEqual(rows[0][:3], ["title", "status", "priority"])
        self.assertTrue(rows[1][0].startswith("'="))  # formula injection neutralised
        data = self.client.get("/api/export.json", headers=self.ali["h"]).json()
        self.assertEqual(len(data["plans"]), 2)
        out = self.req(self.aziza, "POST", "/api/import", 201, json={"version": 1, "plans": data["plans"] + [{"title": ""}, {"bad": 1}]})
        self.assertEqual(out, {"created": 2, "skipped": 2})  # entries without a title are skipped
        titles = {p["title"] for p in self.req(self.aziza, "GET", "/api/plans")["plans"]}
        self.assertIn("Режа", titles)

    def test_calendar_feed(self):
        self.plan(title="Uchrashuv, muhim; " + "x" * 80, due_at="2026-10-15T10:00:00Z")
        self.plan(title="Muddatsiz")
        token = self.req(self.ali, "GET", "/api/me/calendar")["token"]
        self.assertEqual(self.req(self.ali, "GET", "/api/me/calendar")["token"], token)
        feed = self.client.get(f"/api/calendar/{token}.ics")
        self.assertEqual(feed.headers["content-type"], "text/calendar; charset=utf-8")
        body = feed.text
        self.assertIn("DTSTART:20261015T100000Z", body)
        self.assertIn("SUMMARY:Uchrashuv\\, muhim\\; ", body)
        self.assertNotIn("Muddatsiz", body)
        self.assertTrue(all(len(line.encode()) <= 75 for line in body.split("\r\n")))
        new = self.req(self.ali, "POST", "/api/me/calendar")["token"]
        self.assertEqual(self.client.get(f"/api/calendar/{token}.ics").status_code, 404)
        self.assertEqual(self.client.get(f"/api/calendar/{new}.ics").status_code, 200)

    # account ----------------------------------------------------------------------------
    def test_password_change_signs_out_other_sessions(self):
        old = dict(self.ali)
        r = self.req(self.ali, "POST", "/api/me/password", 403, json={"current": "wrong", "new": "yangiparol1"})
        self.assertEqual(r["error"], "bad_password")
        token = self.req(self.ali, "POST", "/api/me/password", json={"current": "parol12345", "new": "yangiparol1"})["token"]
        self.req(old, "GET", "/api/me", 401)
        self.req({"h": {"Authorization": f"Bearer {token}"}}, "GET", "/api/me")
        r = self.client.post("/api/auth/login", json={"email": "ali@example.com", "password": "yangiparol1"})
        self.assertEqual(r.status_code, 200)

    def test_delete_account_hands_back_pending_approvals(self):
        p = self.plan(approver_id=self.aziza["id"], backup_approver_id=self.bobur["id"])
        self.req(self.ali, "POST", f"/api/plans/{p['id']}/submit", json={})
        mine = self.plan(who=self.aziza, title="Azizaniki")
        self.req(self.aziza, "DELETE", "/api/me", 403, json={"password": "nope"})
        self.req(self.aziza, "DELETE", "/api/me", 204, json={"password": "parol12345"})
        back = self.req(self.ali, "GET", f"/api/plans/{p['id']}")
        self.assertEqual((back["status"], back["approver_id"], back["backup_approver_id"]), ("active", self.bobur["id"], None))
        self.assertIn("approver_left", [n["kind"] for n in self.req(self.ali, "GET", "/api/notifications")["notifications"]])
        self.req(self.aziza, "GET", "/api/me", 401)
        r = self.client.post("/api/auth/login", json={"email": "aziza@example.com", "password": "parol12345"})
        self.assertEqual(r.status_code, 401)
        self.assertIsNotNone(mine)


if __name__ == "__main__":
    unittest.main()
