from __future__ import annotations

import calendar as month_calendar
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
    table = next(
        (
            candidate
            for candidate in soup.find_all("table")
            if "Manufacturing" in candidate.get_text(" ") and "Services" in candidate.get_text(" ")
        ),
        None,
    )
    if table is None:
        raise ValueError("ISM release schedule table not found")
    events: list[CalendarEvent] = []
    for row in table.find_all("tr"):
        cells = [" ".join(cell.get_text(" ", strip=True).split()) for cell in row.find_all(["th", "td"])]
        if len(cells) < 3:
            continue
        month_bits = cells[0].split()
        if len(month_bits) < 2 or month_bits[0].lower() not in MONTHS:
            continue
        try:
            year = int(month_bits[1])
            month = MONTHS[month_bits[0].lower()]
            manufacturing_day = int("".join(ch for ch in cells[1] if ch.isdigit()))
            services_day = int("".join(ch for ch in cells[2] if ch.isdigit()))
        except (ValueError, IndexError):
            continue
        if config.macro["ism_manufacturing"]:
            events.append(
                _build_event(
                    "ism_manufacturing",
                    date(year, month, manufacturing_day),
                    config,
                    method="Official ISM release table",
                )
            )
        if config.macro["ism_services"]:
            events.append(
                _build_event(
                    "ism_services",
                    date(year, month, services_day),
                    config,
                    method="Official ISM release table",
                )
            )
    if not events:
        raise ValueError("ISM schedule contained no supported releases")
    return events


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
