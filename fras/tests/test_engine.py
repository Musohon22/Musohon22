"""Attendance engine: pure calculation tests (spec D-06 test cases)."""

import unittest
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from fras.engine.attendance import Correction, Event, Shift, assign_work_date, compute_day
from fras.engine.decision import decide

TZ = "Asia/Tashkent"
Z = ZoneInfo(TZ)


def at(d: date, hm: str, plus_days: int = 0) -> datetime:
    h, m = map(int, hm.split(":"))
    dd = d + timedelta(days=plus_days)
    return datetime(dd.year, dd.month, dd.day, h, m, tzinfo=Z)


def ev(i, d, hm, direction, plus=0, **kw):
    return Event(id=str(i), at=at(d, hm, plus), direction=direction, **kw)


DAY = date(2026, 10, 14)
LATER = at(DAY, "23:59", 2)
DAYSHIFT = Shift(code="D1", start="08:00", end="17:00", crosses_midnight=False,
                 breaks=[{"start": "12:00", "end": "13:00", "paid": False}])
NIGHT = Shift(code="N1", start="22:00", end="06:00", crosses_midnight=True, breaks=[{"floating_min": 30, "paid": False}])


def run(events, shift=DAYSHIFT, corrections=(), leave=None, holiday=False, now=LATER, day=DAY):
    return compute_day(work_date=day, zone=TZ, shift=shift, holiday=holiday, events=list(events),
                       corrections=list(corrections), leave=leave, debounce_min=2, missing_out_after_min=120, now=now)


class EngineTests(unittest.TestCase):
    def test_regular_day(self):
        s = run([ev(1, DAY, "07:55", "in"), ev(2, DAY, "17:02", "out")])
        self.assertEqual(s.status, "present")
        self.assertEqual(s.break_min, 60)
        self.assertEqual(s.worked_min, 8 * 60)          # 08:00–17:00 minus 1 h unpaid break
        self.assertEqual(s.late_min, 0)
        self.assertEqual(s.overtime_min, 0)

    def test_late_beyond_grace(self):
        s = run([ev(1, DAY, "08:12", "in"), ev(2, DAY, "17:00", "out")])
        self.assertEqual(s.status, "late")
        self.assertEqual(s.late_min, 12)

    def test_within_grace_is_not_late(self):
        s = run([ev(1, DAY, "08:04", "in"), ev(2, DAY, "17:00", "out")])
        self.assertEqual(s.late_min, 0)
        self.assertEqual(s.status, "present")

    def test_early_leave(self):
        s = run([ev(1, DAY, "08:00", "in"), ev(2, DAY, "16:30", "out")])
        self.assertEqual(s.early_leave_min, 30)

    def test_overtime_rounded_down_and_threshold(self):
        s = run([ev(1, DAY, "08:00", "in"), ev(2, DAY, "18:10", "out")])   # 70 min extra → 60
        self.assertEqual(s.overtime_min, 60)
        self.assertEqual(s.worked_min, 8 * 60 + 60)
        s2 = run([ev(1, DAY, "08:00", "in"), ev(2, DAY, "17:20", "out")])  # 20 min < 30 threshold
        self.assertEqual(s2.overtime_min, 0)

    def test_night_shift_belongs_to_start_day(self):
        # spec AC: N 22:00–06:00, in 21:50 on 18 Oct, out 06:05 on 19 Oct → work day 18 Oct
        d = date(2026, 10, 18)
        shifts = {d - timedelta(days=1): None, d: NIGHT, d + timedelta(days=1): None}
        self.assertEqual(assign_work_date(at(d, "21:50"), TZ, shifts), d)
        self.assertEqual(assign_work_date(at(d, "06:05", 1), TZ, shifts), d)
        s = run([ev(1, d, "21:50", "in"), ev(2, d, "06:05", "out", plus=1)], shift=NIGHT, day=d, now=at(d, "12:00", 2))
        self.assertEqual(s.work_date, "2026-10-18")
        self.assertEqual(s.status, "present")
        self.assertEqual(s.break_min, 30)
        self.assertEqual(s.worked_min, 8 * 60 - 30)

    def test_missing_checkout_becomes_anomaly_after_deadline(self):
        s = run([ev(1, DAY, "08:00", "in")], now=at(DAY, "20:00"))
        self.assertIn("missing_out", s.anomalies)
        self.assertEqual(s.status, "incomplete")
        s2 = run([ev(1, DAY, "08:00", "in")], now=at(DAY, "11:00"))
        self.assertNotIn("missing_out", s2.anomalies)    # still at work

    def test_debounce_and_duplicates(self):
        s = run([ev(1, DAY, "07:58", "in"), ev(2, DAY, "07:59", "in"), ev(3, DAY, "17:01", "out"),
                 ev(4, DAY, "17:02", "out")])
        self.assertEqual(s.first_in, at(DAY, "07:58"))
        self.assertEqual(s.status, "present")

    def test_rejected_and_unknown_events_do_not_count(self):
        s = run([ev(1, DAY, "08:00", "in", result="pad"), ev(2, DAY, "08:30", "in"), ev(3, DAY, "17:00", "out")])
        self.assertEqual(s.first_in, at(DAY, "08:30"))
        s2 = run([ev(1, DAY, "08:00", "in", result="review", review="rejected"), ev(2, DAY, "17:00", "out")])
        self.assertIn("missing_in", s2.anomalies)

    def test_pending_review_flags_day(self):
        s = run([ev(1, DAY, "08:00", "in", result="review"), ev(2, DAY, "17:00", "out")])
        self.assertIn("review_required", s.anomalies)

    def test_absent_and_scheduled(self):
        self.assertEqual(run([], now=at(DAY, "10:00")).status, "absent")
        self.assertEqual(run([], now=at(DAY, "07:00")).status, "scheduled")

    def test_day_off_and_holiday(self):
        self.assertEqual(run([], shift=None).status, "off")
        self.assertEqual(run([], shift=None, holiday=True).status, "holiday")
        s = run([ev(1, DAY, "09:00", "in"), ev(2, DAY, "13:00", "out")], shift=None)
        self.assertEqual(s.status, "present")
        self.assertEqual(s.overtime_min, 240)   # whole rest-day work is extra time

    def test_leave(self):
        self.assertEqual(run([], leave={"type": "vacation", "full_day": True}).status, "leave")

    def test_corrections(self):
        base = [ev(1, DAY, "08:00", "in")]
        s = run(base, corrections=[Correction(kind="add_event", at=at(DAY, "17:00"), direction="out")])
        self.assertEqual(s.status, "present")
        self.assertTrue(s.corrected)
        s2 = run([ev(1, DAY, "08:30", "in"), ev(2, DAY, "17:00", "out")],
                 corrections=[Correction(kind="change_time", event_id="1", at=at(DAY, "08:00"))])
        self.assertEqual(s2.late_min, 0)
        s3 = run([], corrections=[Correction(kind="set_day_status", day_status="business_trip")])
        self.assertEqual(s3.status, "business_trip")
        s4 = run([ev(1, DAY, "08:00", "in"), ev(2, DAY, "12:00", "out"), ev(3, DAY, "12:30", "out")],
                 corrections=[Correction(kind="void_event", event_id="3")])
        self.assertEqual(s4.last_out, at(DAY, "12:00"))

    def test_mid_shift_exit_reduces_worked_time(self):
        s = run([ev(1, DAY, "08:00", "in"), ev(2, DAY, "10:00", "out"), ev(3, DAY, "11:00", "in"),
                 ev(4, DAY, "17:00", "out")])
        self.assertEqual(s.worked_min, 8 * 60 - 60)

    def test_explanation_mentions_key_numbers(self):
        s = run([ev(1, DAY, "08:12", "in"), ev(2, DAY, "17:00", "out")])
        self.assertIn("kechikish 12 daq", s.explanation)
        self.assertIn("08:12", s.explanation)


class DecisionTests(unittest.TestCase):
    T = {"accept": 0.62, "review": 0.50}

    def d(self, **kw):
        base = dict(best_score=0.8, best_employee="e1", second_score=0.3, liveness_score=0.9, thresholds=self.T,
                    liveness_required=True, liveness_min=0.6, allowed=True, duplicate=False, attempt=0)
        base.update(kw)
        return decide(**base)

    def test_accept(self):
        r = self.d()
        self.assertEqual((r.result, r.state, r.open_gate), ("accepted", "TRM-05", True))

    def test_pad_blocks_even_with_high_score(self):
        r = self.d(liveness_score=0.2)
        self.assertEqual((r.result, r.state, r.open_gate), ("pad", "TRM-09", False))

    def test_unknown(self):
        self.assertEqual(self.d(best_score=0.3).state, "TRM-08")

    def test_border_zone_never_opens_silently(self):
        r = self.d(best_score=0.55)
        self.assertEqual((r.result, r.open_gate), ("retry", False))
        r2 = self.d(best_score=0.55, attempt=2)
        self.assertEqual((r2.result, r2.state, r2.open_gate), ("review", "TRM-12", False))

    def test_ambiguous_top2(self):
        self.assertEqual(self.d(best_score=0.80, second_score=0.78).result, "retry")

    def test_not_allowed_and_duplicate(self):
        self.assertEqual(self.d(allowed=False).state, "TRM-10")
        r = self.d(duplicate=True)
        self.assertEqual((r.state, r.open_gate), ("TRM-07", True))

    def test_accept_after_retry_marked_review(self):
        self.assertEqual(self.d(attempt=1).result, "review")


class LocalDayTests(unittest.TestCase):
    def test_local_day_maps_to_utc_window(self):
        from fras.util import local_day_bounds
        # a Tashkent calendar day starts at 19:00 UTC the previous day; a UTC-midnight filter would miss 00:00–05:00 local
        self.assertEqual(local_day_bounds("2026-10-20", "2026-10-20", "Asia/Tashkent"),
                         ("2026-10-19T19:00:00Z", "2026-10-20T19:00:00Z"))
        self.assertEqual(local_day_bounds("2026-10-01", "2026-10-31", "UTC"), ("2026-10-01T00:00:00Z", "2026-11-01T00:00:00Z"))


if __name__ == "__main__":
    unittest.main()
