from __future__ import annotations

from datetime import datetime

from bs4 import BeautifulSoup

from src.config import AppConfig
from src.models import CalendarEvent
from src.providers.common import macro_event, period_key
from src.utils.timezone import EASTERN

CENSUS_URL = "https://www.census.gov/retail/release_schedule.html"
CENSUS_SOURCE = "U.S. Census Bureau"
CENSUS_SCOPE = "macro:census"


def parse_retail_schedule(html: str, config: AppConfig) -> list[CalendarEvent]:
    if not config.macro["retail_sales"]:
        return []
    soup = BeautifulSoup(html, "html.parser")
    heading = next(
        (
            node
            for node in soup.find_all(["h2", "h3"])
            if "Advance Monthly Retail Trade Report" in node.get_text(" ", strip=True)
        ),
        None,
    )
    table = heading.find_next("table") if heading else None
    if table is None:
        raise ValueError("Census retail schedule table not found")

    events: list[CalendarEvent] = []
    for row in table.find_all("tr"):
        cells = [" ".join(cell.get_text(" ", strip=True).split()) for cell in row.find_all("td")]
        if len(cells) < 2 or cells[0].lower() == "data month" or "announced" in cells[1].lower():
            continue
        try:
            day = datetime.strptime(cells[1], "%B %d, %Y").date()
        except ValueError:
            continue
        start = datetime(day.year, day.month, day.day, 8, 30, tzinfo=EASTERN)
        period = period_key(cells[0], start)
        events.append(
            macro_event(
                kind="retail_sales",
                summary="🇺🇸 美国零售销售",
                start=start,
                period=period,
                source=CENSUS_SOURCE,
                source_url=CENSUS_URL,
                scope=CENSUS_SCOPE,
                release=f"Advance Monthly Retail Trade Report, {cells[0]}",
            )
        )
    if not events:
        raise ValueError("Census schedule contained no retail-sales releases")
    return events
