from __future__ import annotations

import re
from datetime import datetime

from bs4 import BeautifulSoup

from src.config import AppConfig
from src.models import CalendarEvent
from src.providers.common import macro_event, period_key
from src.utils.timezone import EASTERN

BEA_URL = "https://www.bea.gov/news/schedule"
BEA_SOURCE = "U.S. Bureau of Economic Analysis (BEA)"
BEA_SCOPE = "macro:bea"


def parse_bea_schedule(html: str, config: AppConfig) -> list[CalendarEvent]:
    soup = BeautifulSoup(html, "html.parser")
    table = soup.select_one("#release-schedule-table")
    if table is None:
        raise ValueError("BEA release schedule table not found")
    heading = table.find("th")
    year_match = re.search(r"(20\d{2})", heading.get_text(" ", strip=True) if heading else "")
    if not year_match:
        raise ValueError("BEA schedule year not found")
    year = int(year_match.group(1))

    events: list[CalendarEvent] = []
    for row in table.select("tbody tr"):
        date_node = row.select_one(".release-date")
        time_node = row.select_one(".scheduled-date small")
        title_node = row.select_one(".release-title")
        if not date_node or not time_node or not title_node:
            continue
        release = " ".join(title_node.get_text(" ", strip=True).split())
        try:
            start = datetime.strptime(
                f"{date_node.get_text(' ', strip=True)} {year} {time_node.get_text(' ', strip=True)}",
                "%B %d %Y %I:%M %p",
            ).replace(tzinfo=EASTERN)
        except ValueError:
            continue

        period = period_key(release, start)
        if release.startswith("Personal Income and Outlays"):
            definitions = [
                ("pce", "🇺🇸 美国 PCE", "PCE Price Index"),
                ("core_pce", "🇺🇸 美国核心 PCE", "Core PCE Price Index"),
            ]
            for kind, summary, indicator in definitions:
                if config.macro[kind]:
                    events.append(
                        macro_event(
                            kind=kind,
                            summary=summary,
                            start=start,
                            period=period,
                            source=BEA_SOURCE,
                            source_url=BEA_URL,
                            scope=BEA_SCOPE,
                            release=release,
                            extra={"Indicator": indicator},
                        )
                    )
        elif release.startswith("GDP (") and config.macro["gdp"]:
            stage_match = re.search(r"GDP \(([^)]+)\)", release)
            stage = stage_match.group(1) if stage_match else "Estimate"
            events.append(
                macro_event(
                    kind="gdp",
                    summary=f"🇺🇸 美国 GDP · {stage}",
                    start=start,
                    period=f"{period}-{stage.lower().replace(' ', '-')}",
                    source=BEA_SOURCE,
                    source_url=BEA_URL,
                    scope=BEA_SCOPE,
                    release=release,
                    extra={"Estimate Stage": stage},
                )
            )
    if not events and any(config.macro[key] for key in ("pce", "core_pce", "gdp")):
        raise ValueError("BEA schedule contained no supported future releases")
    return events
