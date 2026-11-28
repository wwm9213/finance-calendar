from __future__ import annotations

import calendar as month_calendar
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, time, timedelta
from urllib.parse import urlsplit

import requests
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
ISM_PRESS_RELEASE = "Official ISM press release via PR Newswire"
ISM_CONFIRMED_METHODS = {ISM_OFFICIAL, ISM_PRESS_RELEASE}
ISM_KINDS = ("ism_manufacturing", "ism_services")
WIRE_ORIGIN = "https://www.prnewswire.com"
ISM_WIRE_URL = WIRE_ORIGIN + "/news/institute-for-supply-management/"
_WIRE_PATH = re.compile(r"/news-releases/[a-z0-9-]+-ism-(manufacturing|services)-pmi-report-\d+\.html")
_NEXT_RELEASE = re.compile(
    r"\bthe next ism (manufacturing|services) pmi report\b[^.!?]{0,140}?\bwill be released at\s+"
    r"(\d{1,2}:\d{2})\s*(a\.?m\.?|p\.?m\.?)\s+(?:ET|EST|EDT)\s+on\s+"
    r"(?:[a-z]+,\s+)?([a-z]+ \d{1,2}, 20\d{2})\b",
    re.IGNORECASE,
)


def _build_event(
    kind: str, day: date, *, method: str, source_url: str = ISM_URL, release_time: time = time(10)
) -> CalendarEvent:
    summary = "🇺🇸 ISM 制造业 PMI" if kind == "ism_manufacturing" else "🇺🇸 ISM 服务业 PMI"
    name = "Manufacturing PMI" if kind == "ism_manufacturing" else "Services PMI"
    start = datetime.combine(day, release_time, tzinfo=EASTERN)
    return macro_event(
        kind=kind,
        summary=summary,
        start=start,
        period=f"{day.year}-{day.month:02d}",
        source=ISM_SOURCE,
        source_url=source_url,
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
            for kind, cell in zip(ISM_KINDS, cells[1:3]):
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
                event = _build_event(kind, day, method=ISM_OFFICIAL)
                events[event.uid] = event
    if not events:
        raise ValueError("ISM schedule contained no supported releases")
    return list(events.values())


def latest_ism_wire_urls(html: str | bytes, kinds: set[str]) -> dict[str, str]:
    """Read the latest report of each requested series from ISM's newsroom."""
    links: dict[str, str] = {}
    for link in BeautifulSoup(html, "html.parser").select("a[href]"):
        try:
            url = urlsplit(link["href"])
        except ValueError:
            continue
        if url.scheme not in ("", "https") or url.netloc not in ("", "www.prnewswire.com"):
            continue
        match = _WIRE_PATH.fullmatch(url.path)
        if match:
            kind = f"ism_{match[1]}"
            if kind in kinds:
                # The issuer listing is newest first.
                links.setdefault(kind, WIRE_ORIGIN + url.path)
    return links


def parse_ism_wire_release(html: str | bytes, *, kind: str, url: str) -> CalendarEvent:
    """Use the next release announced by ISM, not the news article's date."""
    soup = BeautifulSoup(html, "html.parser")
    author = soup.select_one('meta[name="author"]')
    if not author or author.get("content", "").replace("®", "").strip().casefold() != "institute for supply management":
        raise ValueError("PR Newswire article is not attributed to ISM")
    for paragraph in soup.select("section.release-body .release-content p"):
        text = " ".join(paragraph.get_text(" ", strip=True).replace("®", "").split())
        match = _NEXT_RELEASE.search(text)
        if match and f"ism_{match[1].lower()}" == kind:
            release_time = datetime.strptime(f"{match[2]} {match[3].replace('.', '')}", "%I:%M %p").time()
            day = datetime.strptime(match[4], "%B %d, %Y").date()
            return _build_event(kind, day, method=ISM_PRESS_RELEASE, source_url=url, release_time=release_time)
    raise ValueError("ISM article contained no explicit next release for this series")


def _get_wire_html(session: requests.Session, url: str, *, timeout: int) -> bytes:
    # PR Newswire may omit the HTTP charset; let BeautifulSoup read the HTML metadata.
    response = session.get(url, timeout=timeout, headers={"Accept": "text/html,application/xhtml+xml"})
    response.raise_for_status()
    return response.content


def fetch_ism_press_releases(
    session: requests.Session, config: AppConfig, *, kinds: set[str], today: date
) -> tuple[list[CalendarEvent], list[str]]:
    if not kinds:
        return [], []
    timeout = min(config.request_timeout_seconds, 8)
    try:
        listing = _get_wire_html(session, ISM_WIRE_URL, timeout=timeout)
        links = latest_ism_wire_urls(listing, kinds)
    except (requests.RequestException, ValueError) as exc:
        return [], [f"newsroom: {type(exc).__name__}: {exc}"]

    def fetch_one(kind: str) -> tuple[CalendarEvent | None, str | None]:
        if kind not in links:
            return None, f"{kind}: no matching report in newsroom"
        try:
            url = links[kind]
            release = parse_ism_wire_release(_get_wire_html(session, url, timeout=timeout), kind=kind, url=url)
            if not today <= release.start.date() <= today + timedelta(days=45):
                return None, f"{kind}: next release outside the upcoming window"
            return release, None
        except (requests.RequestException, ValueError) as exc:
            return None, f"{kind}: {type(exc).__name__}: {exc}"

    with ThreadPoolExecutor(max_workers=len(kinds)) as executor:
        outcomes = list(executor.map(fetch_one, sorted(kinds)))
    return (
        [event for event, _ in outcomes if event is not None],
        [error for _, error in outcomes if error is not None],
    )


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
                        method="Fallback: ISM first-business-day rule",
                    )
                )
            if config.macro["ism_services"]:
                events.append(
                    _build_event(
                        "ism_services",
                        business_days[2],
                        method="Fallback: ISM third-business-day rule",
                    )
                )
    return events
