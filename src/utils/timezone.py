from __future__ import annotations

from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

EASTERN = ZoneInfo("America/New_York")
UTC = timezone.utc


def eastern_datetime(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime.combine(day, time(hour, minute), tzinfo=EASTERN)


def ensure_aware(value: datetime, default_zone: ZoneInfo = EASTERN) -> datetime:
    return value.replace(tzinfo=default_zone) if value.tzinfo is None else value


def display_time(value: datetime, timezone_name: str) -> str:
    target = value.astimezone(ZoneInfo(timezone_name))
    return target.strftime("%Y-%m-%d %H:%M %Z")
