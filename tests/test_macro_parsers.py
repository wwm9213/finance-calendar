from datetime import datetime, timezone

from src.config import AppConfig
from src.providers.bea import parse_bea_schedule
from src.providers.bls import parse_bls_ics
from src.providers.census import parse_retail_schedule
from src.providers.fed import parse_fomc_calendar
from src.providers.fred import parse_fred_release_calendar
from src.providers.ism import parse_ism_schedule


def config() -> AppConfig:
    return AppConfig(
        timezone="Asia/Shanghai",
        calendar_name="Test",
        lookahead_days=400,
        history_days=30,
        stocks=(),
        macro={
            "nfp": True,
            "unemployment": True,
            "jobless_claims": True,
            "cpi": True,
            "core_cpi": True,
            "ppi": True,
            "core_ppi": True,
            "pce": True,
            "core_pce": True,
            "gdp": True,
            "retail_sales": True,
            "ism_manufacturing": True,
            "ism_services": True,
            "fomc": True,
            "fomc_minutes": True,
        },
        market={"holidays": True, "early_close": True, "quadruple_witching": True},
        request_timeout_seconds=30,
        claims_weeks_ahead=16,
    )


def test_bls_parser_splits_headline_and_core_events() -> None:
    payload = """BEGIN:VCALENDAR\r
VERSION:2.0\r
BEGIN:VEVENT\r
UID:bls-cpi\r
DTSTART;TZID=America/New_York:20261014T083000\r
DTEND;TZID=America/New_York:20261014T090000\r
SUMMARY:Consumer Price Index for September 2026\r
URL:https://www.bls.gov/schedule/news_release/cpi.htm\r
END:VEVENT\r
END:VCALENDAR\r
"""
    events = parse_bls_ics(payload, config())
    assert {event.kind for event in events} == {"cpi", "core_cpi"}
    assert {event.uid for event in events} == {
        "macro-US-CPI-2026-09@finance-calendar",
        "macro-US-CORE_CPI-2026-09@finance-calendar",
    }


def test_bea_parser_extracts_pce_and_gdp() -> None:
    html = """
    <table id="release-schedule-table"><thead><tr><th>Year 2026</th></tr></thead><tbody>
      <tr><td class="scheduled-date"><div class="release-date">September 30</div><small>8:30 AM</small></td><td class="release-title">Personal Income and Outlays, August 2026</td></tr>
      <tr><td class="scheduled-date"><div class="release-date">October 29</div><small>8:30 AM</small></td><td class="release-title">GDP (Advance Estimate), 3rd Quarter 2026</td></tr>
    </tbody></table>
    """
    events = parse_bea_schedule(html, config())
    assert {event.kind for event in events} == {"pce", "core_pce", "gdp"}


def test_census_parser_extracts_advance_retail_sales() -> None:
    html = """
    <h2>Advance Monthly Retail Trade Report</h2><table>
      <tr><td>Data Month</td><td>Release Date</td></tr>
      <tr><td>September 2026</td><td>October 15, 2026</td></tr>
    </table>
    """
    event = parse_retail_schedule(html, config())[0]
    assert event.uid == "macro-US-RETAIL_SALES-2026-09@finance-calendar"


def test_ism_parser_uses_official_dates() -> None:
    html = """
    <table><tr><th>Month</th><th>Manufacturing PMI</th><th>Services PMI</th></tr>
      <tr><td>October 2026</td><td>1</td><td>5</td></tr>
    </table>
    """
    events = parse_ism_schedule(html, config())
    assert [event.start.day for event in events] == [1, 5]


def test_fomc_parser_creates_meeting_decision_and_minutes() -> None:
    html = """
    <div class="panel"><div class="panel-heading">2026 FOMC Meetings</div>
      <div class="row fomc-meeting">
        <div class="fomc-meeting__month">September</div>
        <div class="fomc-meeting__date">15-16*</div>
        <div class="fomc-meeting__minutes">(Released October 07, 2026)</div>
      </div>
    </div>
    """
    events = parse_fomc_calendar(html, config())
    assert {event.kind for event in events} == {"fomc_meeting", "fomc_decision", "fomc_minutes"}
    decision = next(event for event in events if event.kind == "fomc_decision")
    assert decision.start.astimezone(timezone.utc) == datetime(2026, 9, 16, 18, 0, tzinfo=timezone.utc)


def test_fred_calendar_is_a_bls_date_fallback() -> None:
    html = """
    <main>Friday October 02, 2026 Updated 7:30 am | Employment Situation
    Friday November 06, 2026 7:30 am | Employment Situation</main>
    """
    events = parse_fred_release_calendar(html, release_id=50, config=config())
    assert {event.kind for event in events} == {"nfp", "unemployment"}
    assert events[0].start.hour == 8
    assert events[0].description["Reference Period"] == "2026-09"
