from __future__ import annotations

import re
from datetime import date, datetime, timedelta

from bs4 import BeautifulSoup

from src.config import AppConfig
from src.models import CalendarEvent
from src.providers.common import MONTHS, macro_event
from src.utils.timezone import EASTERN

FED_URL = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
FED_SOURCE = "Federal Reserve Board"
FED_SCOPE = "macro:fed"


def parse_fomc_calendar(html: str, config: AppConfig) -> list[CalendarEvent]:
    soup = BeautifulSoup(html, "html.parser")
    events: list[CalendarEvent] = []
    panels_found = 0
    for panel in soup.select("div.panel"):
        heading = panel.select_one(".panel-heading")
        heading_text = heading.get_text(" ", strip=True) if heading else ""
        year_match = re.search(r"(20\d{2}) FOMC Meetings", heading_text)
        if not year_match:
            continue
        panels_found += 1
        year = int(year_match.group(1))
        for index, meeting in enumerate(panel.select(".fomc-meeting"), start=1):
            month_node = meeting.select_one(".fomc-meeting__month")
            date_node = meeting.select_one(".fomc-meeting__date")
            if not month_node or not date_node:
                continue
            month_name = month_node.get_text(" ", strip=True).lower()
            if month_name not in MONTHS:
                continue
            month = MONTHS[month_name]
            days = [int(value) for value in re.findall(r"\d+", date_node.get_text(" ", strip=True))]
            if not days:
                continue
            first_day, last_day = days[0], days[-1]
            meeting_start = date(year, month, first_day)
            decision_day = date(year, month, last_day)
            meeting_key = f"{year}-{index:02d}"

            if config.macro["fomc"]:
                events.append(
                    CalendarEvent(
                        uid=f"macro-US-FOMC-MEETING-{meeting_key}@finance-calendar",
                        category="macro",
                        kind="fomc_meeting",
                        summary="🏦 FOMC 议息会议",
                        start=meeting_start,
                        end=decision_day + timedelta(days=1),
                        description={
                            "Event": "Federal Open Market Committee Meeting",
                            "Meeting": f"{meeting_start.isoformat()} to {decision_day.isoformat()}",
                        },
                        source=FED_SOURCE,
                        source_url=FED_URL,
                        scope=FED_SCOPE,
                        all_day=True,
                    )
                )
                decision_start = datetime(
                    decision_day.year,
                    decision_day.month,
                    decision_day.day,
                    14,
                    0,
                    tzinfo=EASTERN,
                )
                events.append(
                    macro_event(
                        kind="fomc_decision",
                        summary="🏦 FOMC 利率决议",
                        start=decision_start,
                        period=meeting_key,
                        source=FED_SOURCE,
                        source_url=FED_URL,
                        scope=FED_SCOPE,
                        release="FOMC Statement and Interest Rate Decision",
                        duration_minutes=60,
                        extra={"Meeting End Date": decision_day.isoformat()},
                    )
                )

            if config.macro["fomc_minutes"]:
                minutes_node = meeting.select_one(".fomc-meeting__minutes")
                minutes_text = minutes_node.get_text(" ", strip=True) if minutes_node else ""
                released = re.search(
                    r"Released\s+([A-Za-z]+)\s+(\d{1,2}),\s*(20\d{2})", minutes_text
                )
                method = "Official release date"
                if released and released.group(1).lower() in MONTHS:
                    minutes_day = date(
                        int(released.group(3)),
                        MONTHS[released.group(1).lower()],
                        int(released.group(2)),
                    )
                else:
                    minutes_day = decision_day + timedelta(days=21)
                    method = "Federal Reserve three-week publication policy"
                minutes_start = datetime(
                    minutes_day.year,
                    minutes_day.month,
                    minutes_day.day,
                    14,
                    0,
                    tzinfo=EASTERN,
                )
                events.append(
                    macro_event(
                        kind="fomc_minutes",
                        summary="🏦 FOMC 会议纪要",
                        start=minutes_start,
                        period=meeting_key,
                        source=FED_SOURCE,
                        source_url=FED_URL,
                        scope=FED_SCOPE,
                        release="FOMC Minutes",
                        duration_minutes=30,
                        extra={
                            "Meeting End Date": decision_day.isoformat(),
                            "Schedule Method": method,
                        },
                    )
                )
    if panels_found == 0:
        raise ValueError("FOMC meeting panels not found")
    return events
