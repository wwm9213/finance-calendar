from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from typing import Any


@dataclass(slots=True)
class CalendarEvent:
    uid: str
    category: str
    kind: str
    summary: str
    start: date | datetime
    end: date | datetime
    description: dict[str, Any]
    source: str
    source_url: str
    scope: str
    all_day: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["start"] = self.start.isoformat()
        payload["end"] = self.end.isoformat()
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "CalendarEvent":
        data = dict(payload)
        if data.get("all_day"):
            data["start"] = date.fromisoformat(data["start"])
            data["end"] = date.fromisoformat(data["end"])
        else:
            data["start"] = datetime.fromisoformat(data["start"])
            data["end"] = datetime.fromisoformat(data["end"])
        data.setdefault("metadata", {})
        return cls(**data)


@dataclass(slots=True)
class FetchResult:
    events: list[CalendarEvent]
    successful_scopes: set[str] = field(default_factory=set)
    failed_scopes: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def event_sort_key(event: CalendarEvent) -> tuple[str, str]:
    """Sort all-day dates and timed datetimes without mixing Python types."""
    return event.start.isoformat(), event.uid


def merge_scoped_events(
    cached: list[CalendarEvent],
    fresh: list[CalendarEvent],
    *,
    enabled_scopes: set[str],
    successful_scopes: set[str],
) -> list[CalendarEvent]:
    """Replace successful scopes and retain cached data for failed scopes."""
    merged = [
        event
        for event in cached
        if event.scope in enabled_scopes and event.scope not in successful_scopes
    ]
    merged.extend(fresh)

    by_uid: dict[str, CalendarEvent] = {}
    for event in sorted(merged, key=event_sort_key):
        by_uid[event.uid] = event
    return sorted(by_uid.values(), key=event_sort_key)
