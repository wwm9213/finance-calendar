from __future__ import annotations

from datetime import date, datetime

from icalendar import Calendar

from src.config import AppConfig
from src.models import CalendarEvent
from src.providers.common import macro_event, period_key
from src.utils.timezone import EASTERN, ensure_aware

BLS_ICS_URL = "https://www.bls.gov/schedule/news_release/bls.ics"
BLS_SOURCE = "U.S. Bureau of Labor Statistics (BLS)"
BLS_SCOPE = "macro:bls"


def parse_bls_ics(payload: str | bytes, config: AppConfig) -> list[CalendarEvent]:
    calendar = Calendar.from_ical(payload)
    events: list[CalendarEvent] = []
    matched_releases = 0
    for component in calendar.walk("VEVENT"):
        release = str(component.get("summary", "")).strip()
        lowered = release.lower()
        raw_start = component.decoded("dtstart")
        if isinstance(raw_start, date) and not isinstance(raw_start, datetime):
            continue
        start = ensure_aware(raw_start, EASTERN)
        period = period_key(release, start)
        url = str(component.get("url", BLS_ICS_URL))

        definitions: list[tuple[str, str, str]] = []
        if "employment situation" in lowered:
            definitions.extend(
                [
                    ("nfp", "🇺🇸 美国非农就业（NFP）", "Nonfarm Payrolls"),
                    ("unemployment", "🇺🇸 美国失业率", "Unemployment Rate"),
                ]
            )
        elif "consumer price index" in lowered:
            definitions.extend(
                [
                    ("cpi", "🇺🇸 美国 CPI", "Consumer Price Index"),
                    ("core_cpi", "🇺🇸 美国核心 CPI", "Core Consumer Price Index"),
                ]
            )
        elif "producer price index" in lowered:
            definitions.extend(
                [
                    ("ppi", "🇺🇸 美国 PPI", "Producer Price Index"),
                    ("core_ppi", "🇺🇸 美国核心 PPI", "Core Producer Price Index"),
                ]
            )
        if not definitions:
            continue
        matched_releases += 1
        for kind, summary, indicator in definitions:
            if not config.macro[kind]:
                continue
            events.append(
                macro_event(
                    kind=kind,
                    summary=summary,
                    start=start,
                    period=period,
                    source=BLS_SOURCE,
                    source_url=url,
                    scope=BLS_SCOPE,
                    release=release,
                    extra={"Indicator": indicator},
                )
            )
    if matched_releases == 0:
        raise ValueError("BLS calendar contained no supported releases")
    return events
