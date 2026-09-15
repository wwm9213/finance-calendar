from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Iterable

from icalendar import Calendar, Event, vDuration

from src.models import CalendarEvent, event_sort_key
from src.utils.timezone import display_time

CALENDAR_TITLES = {
    "macro": "宏观经济",
    "earnings": "自选股财报",
    "market": "市场交易",
    "all": "全部事件",
}


def _description_text(
    event: CalendarEvent, *, timezone_name: str, updated_at: datetime
) -> str:
    lines = [f"{key}: {value}" for key, value in event.description.items() if value not in (None, "")]
    if not event.all_day and isinstance(event.start, datetime):
        lines.append(f"Local Time ({timezone_name}): {display_time(event.start, timezone_name)}")
    lines.extend(
        [
            f"Source: {event.source}",
            f"Source URL: {event.source_url}",
            f"Last Updated: {updated_at.astimezone(timezone.utc).isoformat()}",
        ]
    )
    return "\n".join(lines)


def build_calendar(
    events: Iterable[CalendarEvent],
    *,
    category: str,
    calendar_name: str,
    timezone_name: str,
    updated_at_by_category: dict[str, datetime],
) -> Calendar:
    calendar = Calendar()
    calendar.add("prodid", "-//Finance Calendar//finance-calendar//ZH-CN")
    calendar.add("version", "2.0")
    calendar.add("calscale", "GREGORIAN")
    calendar.add("method", "PUBLISH")
    calendar.add("x-wr-calname", f"{calendar_name} · {CALENDAR_TITLES[category]}")
    calendar.add("x-wr-timezone", timezone_name)
    calendar["refresh-interval"] = vDuration(timedelta(hours=12))
    calendar.add("x-published-ttl", "PT12H")

    seen: set[str] = set()
    for item in sorted(events, key=event_sort_key):
        if item.uid in seen:
            continue
        seen.add(item.uid)
        component = Event()
        component.add("uid", item.uid)
        updated_at = updated_at_by_category[item.category]
        component.add("dtstamp", updated_at.astimezone(timezone.utc))
        component.add("summary", item.summary)
        component.add(
            "description",
            _description_text(item, timezone_name=timezone_name, updated_at=updated_at),
        )
        component.add("url", item.source_url)
        component.add("categories", [item.category.upper(), item.kind.upper()])

        if item.all_day:
            component.add("dtstart", item.start)
            component.add("dtend", item.end)
            component.add("transp", "TRANSPARENT")
        else:
            start = item.start
            end = item.end
            if not isinstance(start, datetime) or not isinstance(end, datetime):
                raise TypeError(f"timed event {item.uid} must use datetime")
            if start.tzinfo is None or end.tzinfo is None:
                raise ValueError(f"timed event {item.uid} must be timezone-aware")
            component.add("dtstart", start.astimezone(timezone.utc))
            component.add("dtend", end.astimezone(timezone.utc))
        calendar.add_component(component)
    return calendar


def write_calendar(calendar: Calendar, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = calendar.to_ical()
    if not data.endswith(b"\r\n"):
        data += b"\r\n"
    path.write_bytes(data)


def empty_timestamp() -> datetime:
    return datetime.combine(date(1970, 1, 1), time.min, tzinfo=timezone.utc)
