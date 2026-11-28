from __future__ import annotations

import calendar as month_calendar
import re
from datetime import date, datetime

from bs4 import BeautifulSoup
from pandas.tseries.holiday import USFederalHolidayCalendar

from src.config import AppConfig
from src.models import CalendarEvent
from src.providers.common import MONTHS, macro_event
from src.utils.timezone import EASTERN

ISM_URL = "https://www.ismworld.org/supply-management-news-and-reports/reports/rob-report-calendar/"
ISM_SOURCE = "Institute for Supply Management (ISM)"
ISM_SCOPE = "macro:ism"
ISM_OFFICIAL = "Official ISM release table"


def _build_event(kind: str, day: date, config: AppConfig, *, method: str) -> CalendarEvent:
    summary = "🇺🇸 ISM 制造业 PMI" if kind == "ism_manufacturing" else "🇺🇸 ISM 服务业 PMI"
    name = "Manufacturing PMI" if kind == "ism_manufacturing" else "Services PMI"
    start = datetime(day.year, day.month, day.day, 10, 0, tzinfo=EASTERN)
    return macro_event(
        kind=kind,
        summary=summary,
        start=start,
        period=f"{day.year}-{day.month:02d}",
        source=ISM_SOURCE,
        source_url=ISM_URL,
        scope=ISM_SCOPE,
        release=f"ISM {name} Report",
        extra={"Schedule Method": method},
    )


def parse_ism_schedule(html: str, config: AppConfig) -> list[CalendarEvent]:
    soup = BeautifulSoup(html, "html.parser")
    if soup.select_one('form[name="captcha_form"], form[action*="captcha"]'):
        raise ValueError("ISM returned a CAPTCHA page")

    events: dict[str, CalendarEvent] = {}
    for table in soup.find_all("table"):
        # Inspect headers rather than requiring the whole document to bear
        # specific casing. Older tables can label services non-manufacturing.
        header = table.find("tr")
        if header is None:
            continue
        headers = [cell.get_text(" ", strip=True).lower() for cell in header.find_all(["th", "td"])]
        if (len(headers) < 3 or "manufacturing" not in headers[1] or
                not any(label in headers[2] for label in ("services", "non-manufacturing"))):
            continue
        for row in table.find_all("tr"):
            cells = row.find_all(["th", "td"], recursive=False)
            if len(cells) < 3:
                continue
            month_bits = cells[0].get_text(" ", strip=True).lower().split()
            if len(month_bits) != 2 or month_bits[0] not in MONTHS or not re.fullmatch(r"20\d{2}", month_bits[1]):
                continue
            year, month = int(month_bits[1]), MONTHS[month_bits[0]]
            for kind, cell in zip(("ism_manufacturing", "ism_services"), cells[1:3]):
                if not config.macro[kind]:
                    continue
                for footnote in cell.find_all("sup"):
                    footnote.decompose()
                match = re.fullmatch(r"(\d{1,2})\s*[*†‡]*", cell.get_text(" ", strip=True))
                if not match:
                    continue
                try:
                    day = date(year, month, int(match[1]))
                except ValueError:
                    continue
                event = _build_event(kind, day, config, method=ISM_OFFICIAL)
                events[event.uid] = event
    if not events:
        raise ValueError("ISM schedule contained no supported releases")
    return list(events.values())


def derived_ism_schedule(config: AppConfig, start_year: int, end_year: int) -> list[CalendarEvent]:
    """Fallback based on ISM's published first/third-business-day rule."""
    federal = USFederalHolidayCalendar()
    holidays = set(
        timestamp.date()
        for timestamp in federal.holidays(
            start=f"{start_year}-01-01", end=f"{end_year}-12-31"
        )
    )
    events: list[CalendarEvent] = []
    for year in range(start_year, end_year + 1):
        for month in range(1, 13):
            business_days = [
                date(year, month, day)
                for day in range(1, month_calendar.monthrange(year, month)[1] + 1)
                if date(year, month, day).weekday() < 5 and date(year, month, day) not in holidays
            ]
            if config.macro["ism_manufacturing"]:
                events.append(
                    _build_event(
                        "ism_manufacturing",
                        business_days[0],
                        config,
                        method="Fallback: ISM first-business-day rule",
                    )
                )
            if config.macro["ism_services"]:
                events.append(
                    _build_event(
                        "ism_services",
                        business_days[2],
                        config,
                        method="Fallback: ISM third-business-day rule",
                    )
                )
    return events
