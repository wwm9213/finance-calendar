from __future__ import annotations

import calendar as month_calendar
from datetime import date, datetime, timedelta, timezone

import pandas as pd
import pandas_market_calendars as mcal

from src.config import AppConfig
from src.models import CalendarEvent, FetchResult, event_sort_key
from src.utils.timezone import EASTERN

NYSE_URL = "https://www.nyse.com/markets/hours-calendars"
NYSE_SOURCE = "NYSE schedule via pandas-market-calendars"
MARKET_SCOPE = "market:nyse"

HOLIDAY_TRANSLATIONS = {
    "new year": "元旦",
    "martin luther king": "马丁·路德·金纪念日",
    "washington": "总统日",
    "president": "总统日",
    "good friday": "耶稣受难日",
    "memorial": "阵亡将士纪念日",
    "juneteenth": "六月节",
    "independence": "美国独立日",
    "labor": "劳动节",
    "thanksgiving": "感恩节",
    "christmas": "圣诞节",
}


def _holiday_name(raw: str) -> str:
    lowered = raw.lower()
    translated = next((value for key, value in HOLIDAY_TRANSLATIONS.items() if key in lowered), None)
    return f"{translated} / {raw}" if translated else raw


def _named_regular_holidays(calendar: mcal.MarketCalendar, start: date, end: date) -> dict[date, str]:
    try:
        values = calendar.regular_holidays.holidays(
            start=pd.Timestamp(start), end=pd.Timestamp(end), return_name=True
        )
        return {timestamp.date(): str(name) for timestamp, name in values.items()}
    except Exception:
        return {}


def _market_holidays(
    calendar: mcal.MarketCalendar,
    schedule: pd.DataFrame,
    start: date,
    end: date,
) -> list[CalendarEvent]:
    sessions = {timestamp.date() for timestamp in schedule.index}
    names = _named_regular_holidays(calendar, start, end)
    events: list[CalendarEvent] = []
    cursor = start
    while cursor <= end:
        if cursor.weekday() < 5 and cursor not in sessions:
            raw_name = names.get(cursor, "NYSE Special Full-Day Closure")
            events.append(
                CalendarEvent(
                    uid=f"market-US-HOLIDAY-{cursor.isoformat()}@finance-calendar",
                    category="market",
                    kind="holiday",
                    summary=f"🏛️ 美股休市 · {_holiday_name(raw_name)}",
                    start=cursor,
                    end=cursor + timedelta(days=1),
                    description={
                        "Market": "NYSE equities",
                        "Status": "Full Market Holiday",
                        "Holiday": raw_name,
                    },
                    source=NYSE_SOURCE,
                    source_url=NYSE_URL,
                    scope=MARKET_SCOPE,
                    all_day=True,
                )
            )
        cursor += timedelta(days=1)
    return events


def _early_closes(
    calendar: mcal.MarketCalendar, schedule: pd.DataFrame
) -> list[CalendarEvent]:
    events: list[CalendarEvent] = []
    early = calendar.early_closes(schedule)
    for session_day, row in early.iterrows():
        day = session_day.date()
        close = row["market_close"].to_pydatetime().astimezone(EASTERN)
        events.append(
            CalendarEvent(
                uid=f"market-US-EARLY-CLOSE-{day.isoformat()}@finance-calendar",
                category="market",
                kind="early_close",
                summary=f"⏰ 美股提前收市 · {close.strftime('%H:%M ET')}",
                start=close - timedelta(minutes=30),
                end=close,
                description={
                    "Market": "NYSE equities",
                    "Status": "Early Close",
                    "Official Close": close.strftime("%Y-%m-%d %H:%M %Z"),
                },
                source=NYSE_SOURCE,
                source_url=NYSE_URL,
                scope=MARKET_SCOPE,
            )
        )
    return events


def _quadruple_witching(start_year: int, end_year: int) -> list[CalendarEvent]:
    events: list[CalendarEvent] = []
    for year in range(start_year, end_year + 1):
        for month in (3, 6, 9, 12):
            fridays = [
                day
                for day in range(1, month_calendar.monthrange(year, month)[1] + 1)
                if date(year, month, day).weekday() == 4
            ]
            event_day = date(year, month, fridays[2])
            events.append(
                CalendarEvent(
                    uid=f"market-US-QUADRUPLE-WITCHING-{year}-{month:02d}@finance-calendar",
                    category="market",
                    kind="quadruple_witching",
                    summary="⚠️ 美股四巫日",
                    start=event_day,
                    end=event_day + timedelta(days=1),
                    description={
                        "Event": "Quarterly derivatives expiration concentration",
                        "Rule": "Third Friday of March, June, September and December",
                    },
                    source="Calendar rule",
                    source_url="https://www.optionseducation.org/referencelibrary/faq/options-expiration-calendar",
                    scope="market:quadruple-witching",
                    all_day=True,
                )
            )
    return events


def fetch_market_events(
    config: AppConfig, *, now: datetime | None = None
) -> FetchResult:
    now = now or datetime.now(timezone.utc)
    today = now.astimezone(EASTERN).date()
    start = today - timedelta(days=config.history_days)
    end = today + timedelta(days=config.lookahead_days)
    calendar = mcal.get_calendar("NYSE")
    schedule = calendar.schedule(start_date=start, end_date=end)
    events: list[CalendarEvent] = []
    if config.market["holidays"]:
        events.extend(_market_holidays(calendar, schedule, start, end))
    if config.market["early_close"]:
        events.extend(_early_closes(calendar, schedule))
    if config.market["quadruple_witching"]:
        events.extend(_quadruple_witching(start.year, end.year))
    events = [
        event
        for event in events
        if start <= (event.start.date() if isinstance(event.start, datetime) else event.start) <= end
    ]
    return FetchResult(
        sorted(events, key=event_sort_key),
        {MARKET_SCOPE, "market:quadruple-witching"},
    )
