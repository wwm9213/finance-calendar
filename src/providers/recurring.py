from __future__ import annotations

from datetime import date, datetime, timedelta

from pandas.tseries.holiday import USFederalHolidayCalendar

from src.config import AppConfig
from src.models import CalendarEvent
from src.providers.common import macro_event
from src.utils.timezone import EASTERN

DOL_URL = "https://www.dol.gov/newsroom/releases/eta"
DOL_SOURCE = "U.S. Department of Labor (ETA)"
DOL_SCOPE = "macro:dol-claims"


def initial_claims_schedule(today: date, config: AppConfig) -> list[CalendarEvent]:
    if not config.macro["jobless_claims"]:
        return []
    start = today - timedelta(days=config.history_days)
    end = today + timedelta(weeks=config.claims_weeks_ahead)
    federal = USFederalHolidayCalendar()
    holidays = {
        timestamp.date()
        for timestamp in federal.holidays(start=start.isoformat(), end=end.isoformat())
    }

    cursor = start
    events: list[CalendarEvent] = []
    while cursor <= end:
        if cursor.weekday() == 3:  # Thursday is the normal publication day.
            release_day = cursor - timedelta(days=1) if cursor in holidays else cursor
            release_time = datetime(
                release_day.year,
                release_day.month,
                release_day.day,
                8,
                30,
                tzinfo=EASTERN,
            )
            reference_week = cursor - timedelta(days=5)
            events.append(
                macro_event(
                    kind="jobless_claims",
                    summary="🇺🇸 美国初请失业金人数",
                    start=release_time,
                    period=reference_week.isoformat(),
                    source=DOL_SOURCE,
                    source_url=DOL_URL,
                    scope=DOL_SCOPE,
                    release="Unemployment Insurance Weekly Claims Report",
                    extra={
                        "Reference Week Ending": reference_week.isoformat(),
                        "Schedule Method": (
                            "Normal Thursday publication; moved one day earlier for a federal holiday"
                            if release_day != cursor
                            else "Normal Thursday 08:30 ET publication pattern"
                        ),
                    },
                )
            )
        cursor += timedelta(days=1)
    return events
