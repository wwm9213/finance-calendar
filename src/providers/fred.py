from __future__ import annotations

import re
from datetime import date, datetime

import requests
from bs4 import BeautifulSoup

from src.config import AppConfig
from src.models import CalendarEvent
from src.providers.bls import BLS_SCOPE
from src.providers.common import MONTHS, macro_event
from src.utils.http import get_text
from src.utils.timezone import EASTERN

FRED_BASE_URL = "https://fred.stlouisfed.org/releases/calendar"
FRED_SOURCE = "FRED release calendar (dates supplied by BLS)"

RELEASES = {
    50: (
        "Employment Situation",
        [
            ("nfp", "🇺🇸 美国非农就业（NFP）", "Nonfarm Payrolls"),
            ("unemployment", "🇺🇸 美国失业率", "Unemployment Rate"),
        ],
    ),
    10: (
        "Consumer Price Index",
        [
            ("cpi", "🇺🇸 美国 CPI", "Consumer Price Index"),
            ("core_cpi", "🇺🇸 美国核心 CPI", "Core Consumer Price Index"),
        ],
    ),
    46: (
        "Producer Price Index",
        [
            ("ppi", "🇺🇸 美国 PPI", "Producer Price Index"),
            ("core_ppi", "🇺🇸 美国核心 PPI", "Core Producer Price Index"),
        ],
    ),
}

DATE_PATTERN = re.compile(
    r"\b(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\s+"
    r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+"
    r"(\d{1,2}),?\s+(20\d{2})\b",
    re.IGNORECASE,
)


def _previous_month(day: date) -> str:
    if day.month == 1:
        return f"{day.year - 1}-12"
    return f"{day.year}-{day.month - 1:02d}"


def parse_fred_release_calendar(
    html: str, *, release_id: int, config: AppConfig
) -> list[CalendarEvent]:
    release, definitions = RELEASES[release_id]
    text = " ".join(BeautifulSoup(html, "html.parser").get_text(" ", strip=True).split())
    dates = {
        date(int(match.group(3)), MONTHS[match.group(1).lower()], int(match.group(2)))
        for match in DATE_PATTERN.finditer(text)
    }
    if not dates:
        raise ValueError(f"FRED {release} calendar contained no release dates")

    source_url = f"{FRED_BASE_URL}?rid={release_id}"
    events: list[CalendarEvent] = []
    for day in sorted(dates):
        start = datetime(day.year, day.month, day.day, 8, 30, tzinfo=EASTERN)
        period = _previous_month(day)
        for kind, summary, indicator in definitions:
            if config.macro[kind]:
                events.append(
                    macro_event(
                        kind=kind,
                        summary=summary,
                        start=start,
                        period=period,
                        source=FRED_SOURCE,
                        source_url=source_url,
                        scope=BLS_SCOPE,
                        release=release,
                        extra={
                            "Indicator": indicator,
                            "Schedule Note": "FRED states that release dates are published by the data source",
                        },
                    )
                )
    return events


def fetch_fred_bls_fallback(
    session: requests.Session,
    config: AppConfig,
    *,
    start_year: int,
    end_year: int,
) -> list[CalendarEvent]:
    events: list[CalendarEvent] = []
    errors: list[str] = []
    for year in range(start_year, end_year + 1):
        for release_id in RELEASES:
            url = f"{FRED_BASE_URL}?rid={release_id}&y={year}"
            try:
                html = get_text(
                    session,
                    url,
                    timeout=min(config.request_timeout_seconds, 15),
                )
                events.extend(parse_fred_release_calendar(html, release_id=release_id, config=config))
            except Exception as exc:
                errors.append(f"rid={release_id}, year={year}: {type(exc).__name__}: {exc}")
    if not events:
        raise RuntimeError("; ".join(errors) or "FRED fallback returned no events")
    return events
