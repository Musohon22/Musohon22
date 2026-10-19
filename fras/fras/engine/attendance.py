"""Attendance calculation engine — pure functions, no database access.

Three layers are kept apart (spec A.4):
  raw events (what happened) → planned shift (what should have happened)
  → daily summary (computed, always reproducible from the first two plus
  approved corrections and leave).

A "work day" is anchored to the shift start date, so a night shift
22:00–06:00 that starts on 18 Oct belongs to work day 18 Oct even though
the check-out happens on 19 Oct.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

COUNTED_RESULTS = {"accepted", "review"}


@dataclass
class Shift:
    code: str
    start: str            # "HH:MM" local
    end: str
    crosses_midnight: bool
    breaks: list[dict] = field(default_factory=list)    # {"start","end","paid"} or {"floating_min","paid"}
    window_before_min: int = 120
    window_after_min: int = 240
    grace_min: int = 5
    early_leave_min: int = 5
    overtime_min: int = 30
    overtime_round_min: int = 15
    count_early_arrival: bool = False

    @classmethod
    def from_row(cls, row: dict, breaks: list[dict]) -> "Shift":
        return cls(code=row["code"], start=row["start_time"], end=row["end_time"],
                   crosses_midnight=bool(row["crosses_midnight"]), breaks=breaks,
                   window_before_min=row["window_before_min"], window_after_min=row["window_after_min"],
                   grace_min=row["grace_min"], early_leave_min=row["early_leave_min"],
                   overtime_min=row["overtime_min"], overtime_round_min=row["overtime_round_min"],
                   count_early_arrival=bool(row["count_early_arrival"]))

    def planned(self, day: date, zone: str) -> tuple[datetime, datetime]:
        tz = ZoneInfo(zone)
        sh, sm = map(int, self.start.split(":"))
        eh, em = map(int, self.end.split(":"))
        start = datetime(day.year, day.month, day.day, sh, sm, tzinfo=tz)
        end_day = day + timedelta(days=1) if self.crosses_midnight else day
        end = datetime(end_day.year, end_day.month, end_day.day, eh, em, tzinfo=tz)
        return start, end

    def window(self, day: date, zone: str) -> tuple[datetime, datetime]:
        start, end = self.planned(day, zone)
        return start - timedelta(minutes=self.window_before_min), end + timedelta(minutes=self.window_after_min)


@dataclass
class Event:
    id: str
    at: datetime              # aware
    direction: str            # in | out
    result: str = "accepted"
    review: str | None = None   # None | verified | rejected
    method: str = "face"
    synthetic: bool = False


@dataclass
class Correction:
    kind: str                   # add_event | void_event | change_time | set_day_status
    event_id: str | None = None
    at: datetime | None = None
    direction: str | None = None
    day_status: str | None = None


@dataclass
class Summary:
    work_date: str
    shift_code: str | None
    planned_start: datetime | None
    planned_end: datetime | None
    first_in: datetime | None
    last_out: datetime | None
    worked_min: int
    break_min: int
    late_min: int
    early_leave_min: int
    overtime_min: int
    status: str
    anomalies: list[str]
    explanation: str
    corrected: bool


def _fmt(minutes: int) -> str:
    h, m = divmod(max(0, minutes), 60)
    return f"{h} s {m:02d} daq"


def _local(dt: datetime | None, zone: str) -> str:
    return dt.astimezone(ZoneInfo(zone)).strftime("%H:%M") if dt else "—"


def assign_work_date(at: datetime, zone: str, shifts_by_day: dict[date, Shift | None]) -> date:
    """Pick the work day an event belongs to: the shift whose window contains it,
    nearest planned boundary wins; otherwise the local calendar date."""
    best: tuple[float, date] | None = None
    for day, shift in shifts_by_day.items():
        if shift is None:
            continue
        w0, w1 = shift.window(day, zone)
        if w0 <= at <= w1:
            ps, pe = shift.planned(day, zone)
            dist = min(abs((at - ps).total_seconds()), abs((at - pe).total_seconds()))
            if best is None or dist < best[0]:
                best = (dist, day)
    if best:
        return best[1]
    return at.astimezone(ZoneInfo(zone)).date()


def apply_corrections(events: list[Event], corrections: list[Correction]) -> tuple[list[Event], str | None, bool]:
    by_id = {e.id: e for e in events}
    voided: set[str] = set()
    day_status = None
    changed = False
    out = list(events)
    for i, c in enumerate(corrections):
        changed = True
        if c.kind == "void_event" and c.event_id:
            voided.add(c.event_id)
        elif c.kind == "change_time" and c.event_id in by_id and c.at:
            orig = by_id[c.event_id]
            voided.add(orig.id)
            out.append(Event(id=f"corr-{i}", at=c.at, direction=c.direction or orig.direction,
                             method="manual", synthetic=True))
        elif c.kind == "add_event" and c.at and c.direction:
            out.append(Event(id=f"corr-{i}", at=c.at, direction=c.direction, method="manual", synthetic=True))
        elif c.kind == "set_day_status":
            day_status = c.day_status
    return [e for e in out if e.id not in voided], day_status, changed


def _debounce(events: list[Event], minutes: int) -> list[Event]:
    kept: list[Event] = []
    last_by_dir: dict[str, datetime] = {}
    for e in events:
        prev = last_by_dir.get(e.direction)
        if prev is not None and (e.at - prev) < timedelta(minutes=minutes) and not e.synthetic:
            continue
        kept.append(e)
        last_by_dir[e.direction] = e.at
    return kept


def _pair(events: list[Event]) -> tuple[list[tuple[datetime, datetime | None]], list[str]]:
    intervals: list[tuple[datetime, datetime | None]] = []
    anomalies: list[str] = []
    open_in: datetime | None = None
    for e in events:
        if e.direction == "in":
            if open_in is None:
                open_in = e.at
            # a second "in" without "out" keeps the earlier one (re-entry through another gate)
        else:
            if open_in is not None:
                intervals.append((open_in, e.at))
                open_in = None
            elif not intervals:
                anomalies.append("missing_in")
            else:
                # out after out: extend the last interval
                last_in, _ = intervals[-1]
                intervals[-1] = (last_in, e.at)
    if open_in is not None:
        intervals.append((open_in, None))
    return intervals, anomalies


def _overlap(a0: datetime, a1: datetime, b0: datetime, b1: datetime) -> int:
    lo, hi = max(a0, b0), min(a1, b1)
    return max(0, int((hi - lo).total_seconds() // 60))


def compute_day(*, work_date: date, zone: str, shift: Shift | None, holiday: bool, events: list[Event],
                corrections: list[Correction], leave: dict | None, debounce_min: int, missing_out_after_min: int,
                now: datetime) -> Summary:
    evs, forced_status, corrected = apply_corrections(events, corrections)
    pending_review = any(e.result == "review" and e.review is None for e in evs)
    evs = [e for e in evs if e.synthetic or (e.result in COUNTED_RESULTS and e.review != "rejected")]
    evs.sort(key=lambda e: e.at)
    evs = _debounce(evs, debounce_min)
    intervals, anomalies = _pair(evs)
    if pending_review:
        anomalies.append("review_required")

    planned_start = planned_end = None
    if shift:
        planned_start, planned_end = shift.planned(work_date, zone)

    # close or flag an open interval
    if intervals and intervals[-1][1] is None:
        start_open = intervals[-1][0]
        deadline = (planned_end or start_open + timedelta(hours=12)) + timedelta(minutes=missing_out_after_min)
        if now >= deadline:
            anomalies.append("missing_out")
            intervals = intervals[:-1] + [(start_open, start_open)]   # counts nothing until corrected
        else:
            intervals = intervals[:-1] + [(start_open, min(now, planned_end or now))]

    first_in = evs[0].at if evs and evs[0].direction == "in" else (intervals[0][0] if intervals else None)
    outs = [e.at for e in evs if e.direction == "out"]
    last_out = outs[-1] if outs else None

    worked = late = early = overtime = break_min = 0
    if intervals:
        if shift:
            regular = 0
            extra_after = 0
            extra_before = 0
            for a, b in intervals:
                b = b or a
                regular += _overlap(a, b, planned_start, planned_end)
                if b > planned_end:
                    extra_after += _overlap(a, b, planned_end, b)
                if a < planned_start:
                    extra_before += _overlap(a, b, a, planned_start)
            # unpaid breaks
            for br in shift.breaks:
                if br.get("paid"):
                    continue
                if br.get("floating_min"):
                    if regular >= br["floating_min"] * 2:
                        break_min += br["floating_min"]
                else:
                    bs, be = Shift(code="", start=br["start"], end=br["end"],
                                   crosses_midnight=br["end"] < br["start"]).planned(work_date, zone)
                    if bs < planned_start:   # break after midnight in a night shift
                        bs += timedelta(days=1)
                        be += timedelta(days=1)
                    break_min += sum(_overlap(a, b or a, bs, be) for a, b in intervals)
            regular = max(0, regular - break_min)
            extra = extra_after + (extra_before if shift.count_early_arrival else 0)
            if extra >= shift.overtime_min:
                step = max(1, shift.overtime_round_min)
                overtime = (extra // step) * step
            worked = regular + overtime
            if first_in and first_in > planned_start + timedelta(minutes=shift.grace_min):
                late = int((first_in - planned_start).total_seconds() // 60)
            if last_out and "missing_out" not in anomalies and last_out < planned_end - timedelta(minutes=shift.early_leave_min):
                early = int((planned_end - last_out).total_seconds() // 60)
        else:
            worked = sum(_overlap(a, b or a, a, b or a) for a, b in intervals)

    # ---- status
    if forced_status:
        status = forced_status
    elif leave and leave.get("full_day", True) and not evs:
        status = "leave"
    elif not evs:
        if holiday:
            status = "holiday"
        elif shift is None:
            status = "off"
        elif now < planned_start:
            status = "scheduled"
        elif now < planned_start + timedelta(minutes=shift.grace_min):
            status = "scheduled"
        else:
            status = "absent"
    elif "missing_out" in anomalies or "missing_in" in anomalies:
        status = "incomplete"
    elif shift is None or holiday:
        status = "present"
        if shift is None and worked:
            overtime = worked   # work on a rest day is fully extra time
    elif late:
        status = "late"
    else:
        status = "present"

    # ---- explanation (shown in the timesheet popover)
    parts = []
    if shift:
        parts.append(f"Smena {shift.code} {_local(planned_start, zone)}–{_local(planned_end, zone)}")
    else:
        parts.append("Smena yo'q" + (" (bayram)" if holiday else ""))
    if evs:
        parts.append(f"kirish {_local(first_in, zone)}, chiqish {_local(last_out, zone) if last_out else '—'}")
    if break_min:
        parts.append(f"tanaffus {break_min} daq")
    parts.append(f"ishlangan {_fmt(worked)}")
    if late:
        parts.append(f"kechikish {late} daq")
    if early:
        parts.append(f"erta ketish {early} daq")
    if overtime:
        parts.append(f"qo'shimcha {_fmt(overtime)}")
    elif shift and intervals:
        parts.append("qo'shimcha vaqt chegaradan past" if any(b and b > planned_end for _, b in intervals) else "qo'shimcha 0")
    if leave:
        parts.append(f"ruxsat: {leave.get('type')}")
    if corrected:
        parts.append("tuzatish qo'llangan")

    return Summary(work_date=work_date.isoformat(), shift_code=shift.code if shift else None,
                   planned_start=planned_start, planned_end=planned_end, first_in=first_in, last_out=last_out,
                   worked_min=worked, break_min=break_min, late_min=late, early_leave_min=early,
                   overtime_min=overtime, status=status, anomalies=sorted(set(anomalies)),
                   explanation=", ".join(parts), corrected=corrected)
