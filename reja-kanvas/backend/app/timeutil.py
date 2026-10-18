from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

UTC = timezone.utc
_frozen: datetime | None = None


def now() -> datetime:
    return _frozen or datetime.now(UTC)


def freeze(dt: datetime | None) -> None:
    """Tests only: pin the clock."""
    global _frozen
    _frozen = dt


def to_iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("timezone required")
    return dt.astimezone(UTC)


def zone(name: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(name or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def is_valid_zone(name: str) -> bool:
    try:
        ZoneInfo(name)
        return True
    except (ZoneInfoNotFoundError, ValueError):
        return False


def local_today(tz: str) -> date:
    return now().astimezone(zone(tz)).date()


def local_date(dt: datetime, tz: str) -> date:
    return dt.astimezone(zone(tz)).date()


def day_start_utc(day: date, tz: str) -> datetime:
    return datetime.combine(day, time.min, tzinfo=zone(tz)).astimezone(UTC)


def day_bounds_utc(day: date, tz: str) -> tuple[datetime, datetime]:
    return day_start_utc(day, tz), day_start_utc(day + timedelta(days=1), tz)


def at_local(day: date, hour: int, minute: int, tz: str) -> datetime:
    return datetime.combine(day, time(hour, minute), tzinfo=zone(tz)).astimezone(UTC)
