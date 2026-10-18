"""Quick add: turn one line of Uzbek, Russian or English into a plan.

    "Ertaga 15:00 mijoz bilan uchrashuv #ish !yuqori"
    -> title "Mijoz bilan uchrashuv", due tomorrow 15:00 (user's time zone), tag "ish", priority high

Recognised pieces are cut out of the title; anything unrecognised stays in it."""

import re
from datetime import date, datetime, time, timedelta

from . import timeutil

F = re.IGNORECASE | re.UNICODE
B = r"(?<![\w])"  # word start (works for Cyrillic, unlike \b with apostrophes)
E = r"(?![\w])"

WEEKDAYS = {
    0: ["dushanba", "понедельник", "monday", "mon"],
    1: ["seshanba", "вторник", "tuesday", "tue"],
    2: ["chorshanba", "среда", "среду", "wednesday", "wed"],
    3: ["payshanba", "четверг", "thursday", "thu"],
    4: ["juma", "пятница", "пятницу", "friday", "fri"],
    5: ["shanba", "суббота", "субботу", "saturday", "sat"],
    6: ["yakshanba", "воскресенье", "sunday", "sun"],
}
WEEKDAY_WORD = {w: d for d, words in WEEKDAYS.items() for w in words}
WEEKDAY_RE = "|".join(sorted(WEEKDAY_WORD, key=len, reverse=True))

MONTHS = {
    1: ["yanvar", "января", "январь", "january", "jan"],
    2: ["fevral", "февраля", "февраль", "february", "feb"],
    3: ["mart", "марта", "март", "march", "mar"],
    4: ["aprel", "апреля", "апрель", "april", "apr"],
    5: ["may", "мая", "май"],
    6: ["iyun", "июня", "июнь", "june", "jun"],
    7: ["iyul", "июля", "июль", "july", "jul"],
    8: ["avgust", "августа", "август", "august", "aug"],
    9: ["sentabr", "sentyabr", "сентября", "сентябрь", "september", "sept", "sep"],
    10: ["oktabr", "oktyabr", "октября", "октябрь", "october", "oct"],
    11: ["noyabr", "ноября", "ноябрь", "november", "nov"],
    12: ["dekabr", "декабря", "декабрь", "december", "dec"],
}
MONTH_WORD = {w: m for m, words in MONTHS.items() for w in words}
MONTH_RE = "|".join(sorted(MONTH_WORD, key=len, reverse=True))

PRIORITY_WORDS = {
    "urgent": ["urgent", "shoshilinch", "срочно", "1"],
    "high": ["high", "yuqori", "muhim", "важно", "высокий", "2"],
    "low": ["low", "past", "низкий", "4"],
    "normal": ["normal", "oddiy", "обычный", "3"],
}
PRIORITY_WORD = {w: p for p, words in PRIORITY_WORDS.items() for w in words}

RELATIVE_DAYS = [
    (r"day after tomorrow|indinga|послезавтра", 2),
    (r"bugun|сегодня|today|tonight", 0),
    (r"ertaga|завтра|tomorrow", 1),
]
PARTS_OF_DAY = [
    (r"ertalab|утром|in the morning|morning", time(9, 0)),
    (r"tushda|днём|днем|at noon|noon", time(13, 0)),
    (r"kechqurun|вечером|in the evening|evening|tonight", time(19, 0)),
]
NEXT_WEEK = r"keyingi hafta(?:da)?|на следующей неделе|next week"
DEFAULT_TIME = time(9, 0)


class _Text:
    """The input plus the spans already consumed, so pieces never overlap."""

    def __init__(self, text: str):
        self.text = text
        self.used: list[tuple[int, int]] = []

    def take(self, pattern: str):
        for m in re.finditer(pattern, self.text, F):
            if not any(m.start() < e and s < m.end() for s, e in self.used):
                self.used.append(m.span())
                return m
        return None

    def rest(self) -> str:
        out, last = [], 0
        for s, e in sorted(self.used):
            out.append(self.text[last:s])
            last = e
        out.append(self.text[last:])
        cleaned = re.sub(r"\s+", " ", " ".join(out)).strip(" ,.;:-–—")
        return cleaned


def _year_for(day: int, month: int, today: date) -> date | None:
    for year in (today.year, today.year + 1):
        try:
            d = date(year, month, day)
        except ValueError:
            return None
        if d >= today:
            return d
    return None


def parse(text: str, tz: str, now: datetime | None = None) -> dict:
    now = (now or timeutil.now()).astimezone(timeutil.zone(tz))
    today = now.date()
    t = _Text(text)
    out: dict = {"tag": None, "priority": None, "recurrence": None, "due_at": None}

    if m := t.take(rf"{B}#([\w\-]{{1,30}})"):
        out["tag"] = m.group(1)
    if m := t.take(rf"{B}!(" + "|".join(PRIORITY_WORD) + rf"){E}"):
        out["priority"] = PRIORITY_WORD[m.group(1).lower()]
    elif m := t.take(rf"{B}(!!!?)(?!\S)"):
        out["priority"] = "urgent" if len(m.group(1)) == 3 else "high"

    # recurrence (before plain weekdays, so "har dushanba" is not read as "this Monday")
    day: date | None = None
    if m := t.take(rf"{B}(?:har|каждый|каждую|каждое|every|on every)\s+({WEEKDAY_RE}){E}"):
        wd = WEEKDAY_WORD[m.group(1).lower()]
        out["recurrence"] = {"freq": "weekly", "interval": 1, "weekdays": [wd], "until": None}
        day = today + timedelta(days=(wd - today.weekday()) % 7)
    elif t.take(rf"{B}(?:har kuni|каждый день|ежедневно|every day|daily){E}"):
        out["recurrence"] = {"freq": "daily", "interval": 1, "weekdays": [], "until": None}
    elif t.take(rf"{B}(?:har hafta|каждую неделю|еженедельно|every week|weekly){E}"):
        out["recurrence"] = {"freq": "weekly", "interval": 1, "weekdays": [], "until": None}
    elif t.take(rf"{B}(?:har oy|каждый месяц|ежемесячно|every month|monthly){E}"):
        out["recurrence"] = {"freq": "monthly", "interval": 1, "weekdays": [], "until": None}

    # date
    if day is None and (m := t.take(rf"{B}(\d{{4}})-(\d{{2}})-(\d{{2}}){E}")):
        try:
            day = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass
    on = r"(?:on\s+|в\s+|до\s+)?"
    if day is None and (m := t.take(rf"{B}{on}(\d{{1,2}})[\s\-]*({MONTH_RE})\w*{E}")):
        day = _year_for(int(m.group(1)), MONTH_WORD[m.group(2).lower()], today)
    if day is None and (m := t.take(rf"{B}({MONTH_RE})\w*\s+(\d{{1,2}}){E}")):
        day = _year_for(int(m.group(2)), MONTH_WORD[m.group(1).lower()], today)
    if day is None and (m := t.take(rf"{B}{on}(\d{{1,2}})[./](\d{{1,2}})(?:[./](\d{{2,4}}))?{E}")):
        d, mo, y = int(m.group(1)), int(m.group(2)), m.group(3)
        if 1 <= mo <= 12:
            if y:
                try:
                    day = date(int(y) + (2000 if len(y) == 2 else 0), mo, d)
                except ValueError:
                    pass
            else:
                day = _year_for(d, mo, today)
    if day is None and t.take(rf"{B}(?:{NEXT_WEEK}){E}"):
        day = today + timedelta(days=7 - today.weekday())
    if day is None:
        for pattern, offset in RELATIVE_DAYS:
            if t.take(rf"{B}(?:{pattern}){E}"):
                day = today + timedelta(days=offset)
                break
    if day is None and (m := t.take(rf"{B}(?:в\s+|on\s+)?({WEEKDAY_RE})(?:\s+kuni)?{E}")):
        day = today + timedelta(days=(WEEKDAY_WORD[m.group(1).lower()] - today.weekday()) % 7)

    # time
    at: time | None = None
    if m := t.take(rf"{B}(?:soat\s*|в\s*|at\s*)?([01]?\d|2[0-3]):([0-5]\d){E}"):
        at = time(int(m.group(1)), int(m.group(2)))
    elif m := t.take(rf"{B}(?:at\s*)?(1[0-2]|0?[1-9])\s*(am|pm){E}"):
        hour = int(m.group(1)) % 12 + (12 if m.group(2).lower() == "pm" else 0)
        at = time(hour, 0)
    elif m := t.take(rf"{B}soat\s+([01]?\d|2[0-3]){E}"):
        at = time(int(m.group(1)), 0)
    else:
        for pattern, part in PARTS_OF_DAY:
            if t.take(rf"{B}(?:{pattern}){E}"):
                at = part
                break

    if day is None and (at is not None or out["recurrence"]):
        # "15:00 call mum" means the next 15:00; "every day" starts today.
        candidate = datetime.combine(today, at or DEFAULT_TIME, tzinfo=now.tzinfo)
        day = today if candidate > now else today + timedelta(days=1)
    if day is not None:
        due = timeutil.at_local(day, (at or DEFAULT_TIME).hour, (at or DEFAULT_TIME).minute, tz)
        out["due_at"] = timeutil.to_iso(due)

    title = t.rest()
    out["title"] = (title[:1].upper() + title[1:]) if title else text.strip()
    return out
