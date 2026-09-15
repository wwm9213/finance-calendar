from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any

from src.models import CalendarEvent

MONTHS = {
    name.lower(): number
    for number, name in enumerate(
        (
            "January",
            "February",
            "March",
            "April",
            "May",
            "June",
            "July",
            "August",
            "September",
            "October",
            "November",
            "December",
        ),
        start=1,
    )
}


def period_key(text: str, fallback: date | datetime) -> str:
    month_pattern = "|".join(name.title() for name in MONTHS)
    month_match = re.search(rf"\b({month_pattern})\s+(20\d{{2}})\b", text, re.IGNORECASE)
    if month_match:
        return f"{month_match.group(2)}-{MONTHS[month_match.group(1).lower()]:02d}"
    quarter_match = re.search(
        r"\b(?:Q([1-4])|([1-4])(?:st|nd|rd|th)\s+Quarter)\s*,?\s*(20\d{2})\b",
        text,
        re.IGNORECASE,
    )
    if quarter_match:
        quarter = quarter_match.group(1) or quarter_match.group(2)
        return f"{quarter_match.group(3)}-Q{quarter}"
    value = fallback.date() if isinstance(fallback, datetime) else fallback
    return value.strftime("%Y-%m")


def macro_event(
    *,
    kind: str,
    summary: str,
    start: datetime,
    period: str,
    source: str,
    source_url: str,
    scope: str,
    release: str,
    duration_minutes: int = 30,
    extra: dict[str, Any] | None = None,
) -> CalendarEvent:
    description: dict[str, Any] = {
        "Release": release,
        "Reference Period": period,
    }
    if extra:
        description.update(extra)
    return CalendarEvent(
        uid=f"macro-US-{kind.upper()}-{period}@finance-calendar",
        category="macro",
        kind=kind,
        summary=summary,
        start=start,
        end=start + timedelta(minutes=duration_minutes),
        description=description,
        source=source,
        source_url=source_url,
        scope=scope,
    )
