"""Small shared helpers: ids, time, json."""

from __future__ import annotations

import json
import os
import secrets
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

UTC = timezone.utc


def uuid7() -> str:
    """Time-ordered UUID (RFC 9562 v7) so ids sort by creation time."""
    ms = int(time.time() * 1000) & 0xFFFFFFFFFFFF
    rand_a = int.from_bytes(os.urandom(2), "big") & 0xFFF
    rand_b = int.from_bytes(os.urandom(8), "big") & ((1 << 62) - 1)
    value = (ms << 80) | (0x7 << 76) | (rand_a << 64) | (0b10 << 62) | rand_b
    return str(uuid.UUID(int=value))


def new_id() -> str:
    return uuid7()


def utcnow() -> datetime:
    return datetime.now(UTC)


def iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def now_iso() -> str:
    return iso(utcnow())


def parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    v = value.strip()
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"
    dt = datetime.fromisoformat(v)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def parse_date(value: str) -> date:
    return date.fromisoformat(value)


# Business day boundary. Servers usually run in UTC, but "today" for a factory is its local date
# (Tashkent is UTC+5, so the dates differ every night between 00:00 and 05:00 local time).
DEFAULT_TZ = os.environ.get("FRAS_TIMEZONE", "Asia/Tashkent")


def local_today(zone: str | None = None) -> date:
    return datetime.now(ZoneInfo(zone or DEFAULT_TZ)).date()


def local_day_bounds(first: str, last: str, zone: str | None = None) -> tuple[str, str]:
    """UTC [start, end) covering local calendar days first..last (ISO dates) — event timestamps are UTC."""
    z = ZoneInfo(zone or DEFAULT_TZ)
    a, b = date.fromisoformat(first[:10]), date.fromisoformat(last[:10]) + timedelta(days=1)
    to_utc = lambda d: datetime(d.year, d.month, d.day, tzinfo=z).astimezone(timezone.utc)  # noqa: E731
    return iso(to_utc(a)), iso(to_utc(b))


def tz(name: str) -> ZoneInfo:
    return ZoneInfo(name)


def local_dt(day: date, hhmm: str, zone: str) -> datetime:
    """Local wall-clock time on a day, converted to an aware datetime."""
    h, m = (int(x) for x in hhmm.split(":"))
    return datetime(day.year, day.month, day.day, h, m, tzinfo=ZoneInfo(zone))


def daterange(start: date, end: date):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def dumps(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def loads(value, default=None):
    if value is None or value == "":
        return default
    return json.loads(value)


def token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


def minutes_between(a: datetime, b: datetime) -> int:
    return int((b - a).total_seconds() // 60)
