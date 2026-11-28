from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime

import requests
from bs4 import BeautifulSoup
from icalendar import Calendar

from src.config import AppConfig
from src.models import CalendarEvent
from src.providers.common import macro_event, period_key
from src.utils.http import get_text
from src.utils.timezone import EASTERN, ensure_aware

BLS_ICS_URL = "https://www.bls.gov/schedule/news_release/bls.ics"
BLS_SOURCE = "U.S. Bureau of Labor Statistics (BLS)"
BLS_SCOPE = "macro:bls"
_SCHEDULE_BASE = "https://www.bls.gov/schedule/news_release/"
_RELEASES = {
    "empsit.htm": (
        "Employment Situation",
        (
            ("nfp", "🇺🇸 美国非农就业（NFP）", "Nonfarm Payrolls"),
            ("unemployment", "🇺🇸 美国失业率", "Unemployment Rate"),
        ),
    ),
    "cpi.htm": (
        "Consumer Price Index",
        (
            ("cpi", "🇺🇸 美国 CPI", "Consumer Price Index"),
            ("core_cpi", "🇺🇸 美国核心 CPI", "Core Consumer Price Index"),
        ),
    ),
    "ppi.htm": (
        "Producer Price Index",
        (
            ("ppi", "🇺🇸 美国 PPI", "Producer Price Index"),
            ("core_ppi", "🇺🇸 美国核心 PPI", "Core Producer Price Index"),
        ),
    ),
}


def _release_events(
    page: str, config: AppConfig, *, release: str, start: datetime, period: str, url: str
) -> list[CalendarEvent]:
    return [
        macro_event(
            kind=kind, summary=summary, start=start, period=period, source=BLS_SOURCE,
            source_url=url, scope=BLS_SCOPE, release=release, extra={"Indicator": indicator},
        )
        for kind, summary, indicator in _RELEASES[page][1]
        if config.macro[kind]
    ]


def parse_bls_ics(payload: str | bytes, config: AppConfig) -> list[CalendarEvent]:
    events: list[CalendarEvent] = []
    for component in Calendar.from_ical(payload).walk("VEVENT"):
        release = str(component.get("summary", "")).strip()
        page = next((p for p, (name, _) in _RELEASES.items() if name.lower() in release.lower()), None)
        if page is None:
            continue
        raw_start = component.decoded("dtstart", None)
        if isinstance(raw_start, date) and not isinstance(raw_start, datetime):
            continue
        if not isinstance(raw_start, datetime):
            continue
        start = ensure_aware(raw_start, EASTERN)
        events.extend(_release_events(
            page, config, release=release, start=start, period=period_key(release, start),
            url=str(component.get("url", BLS_ICS_URL)),
        ))
    if not events:
        raise ValueError("BLS calendar contained no enabled releases")
    return events


def parse_bls_release_schedule(html: str, config: AppConfig, *, page: str) -> list[CalendarEvent]:
    """Read the reference month, release date and local time from the official table."""
    name, _ = _RELEASES[page]
    soup = BeautifulSoup(html, "html.parser")
    table = soup.select_one("table.release-list")
    if not table or [th.get_text(" ", strip=True).lower() for th in table.select("thead th")] != [
        "reference month", "release date", "release time"
    ]:
        raise ValueError("BLS reference-month schedule table not found")
    events: list[CalendarEvent] = []
    for row in table.select("tbody tr"):
        cells = [cell.get_text(" ", strip=True) for cell in row.find_all("td", recursive=False)]
        if len(cells) != 3:
            continue
        ref, published, release_time = cells
        try:
            period = datetime.strptime(ref, "%B %Y").strftime("%Y-%m")
            # The official cells use abbreviated dates, with optional periods.
            published = published.replace(".", "")
            try:
                day = datetime.strptime(published, "%b %d, %Y").date()
            except ValueError:
                day = datetime.strptime(published, "%B %d, %Y").date()
            hour = datetime.strptime(release_time, "%I:%M %p").time()
        except ValueError:
            # An unannounced or malformed row must never replace cached events.
            continue
        events.extend(_release_events(
            page, config, release=f"{name} for {ref}", period=period,
            start=datetime.combine(day, hour, tzinfo=EASTERN), url=_SCHEDULE_BASE + page,
        ))
    if not events:
        raise ValueError("BLS release schedule contained no enabled dates")
    return events


def fetch_bls_schedules(
    session: requests.Session, config: AppConfig
) -> tuple[list[CalendarEvent], list[str]]:
    # ICS can return HTTP 200 while omitting a newly announced year. Always
    # consult the enabled release tables, with at most four bounded requests.
    pages = [page for page, (_, defs) in _RELEASES.items() if any(config.macro[k] for k, _, _ in defs)]
    timeout = min(config.request_timeout_seconds, 8)

    def fetch_one(page: str | None) -> tuple[list[CalendarEvent], str | None]:
        try:
            if page is None:
                payload = get_text(session, BLS_ICS_URL, timeout=timeout, accept="text/calendar,*/*;q=0.8")
                return parse_bls_ics(payload, config), None
            payload = get_text(session, _SCHEDULE_BASE + page, timeout=timeout)
            return parse_bls_release_schedule(payload, config, page=page), None
        except (requests.RequestException, ValueError, KeyError) as exc:
            return [], f"{page or 'ICS'}: {type(exc).__name__}: {exc}"

    by_uid: dict[str, CalendarEvent] = {}
    errors: list[str] = []
    with ThreadPoolExecutor(max_workers=len(pages) + 1) as executor:
        # ICS loads first in result order. Keep its metadata when the official
        # table agrees, and let explicit official table dates handle revisions.
        for events, error in executor.map(fetch_one, [None, *pages]):
            if error:
                errors.append(error)
            for event in events:
                old = by_uid.get(event.uid)
                if old is None or old.start != event.start:
                    by_uid[event.uid] = event
    return list(by_uid.values()), errors
