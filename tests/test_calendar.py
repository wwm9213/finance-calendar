from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from icalendar import Calendar

from src.calendar import build_calendar, write_calendar
from src.models import CalendarEvent
from src.validate import validate_directory, validate_file
from src.utils.timezone import EASTERN


def _timed(uid: str, category: str = "macro") -> CalendarEvent:
    start = datetime(2026, 10, 14, 8, 30, tzinfo=EASTERN)
    return CalendarEvent(
        uid=uid,
        category=category,
        kind="test",
        summary="Test timed event",
        start=start,
        end=start + timedelta(minutes=30),
        description={"Field": "Value"},
        source="Test",
        source_url="https://example.com",
        scope="test",
    )


def _all_day(uid: str, category: str = "market") -> CalendarEvent:
    return CalendarEvent(
        uid=uid,
        category=category,
        kind="test",
        summary="Test all-day event",
        start=date(2026, 12, 25),
        end=date(2026, 12, 26),
        description={"Field": "Value"},
        source="Test",
        source_url="https://example.com",
        scope="test",
        all_day=True,
    )


def _write(events: list[CalendarEvent], category: str, path: Path) -> None:
    stamp = datetime(2026, 9, 15, tzinfo=timezone.utc)
    calendar = build_calendar(
        events,
        category=category,
        calendar_name="Test",
        timezone_name="Asia/Shanghai",
        updated_at_by_category={"macro": stamp, "earnings": stamp, "market": stamp},
    )
    write_calendar(calendar, path)


def test_timed_event_is_serialized_as_utc_and_valid(tmp_path: Path) -> None:
    path = tmp_path / "macro.ics"
    _write([_timed("timed@example")], "macro", path)
    assert validate_file(path) == {"timed@example"}
    parsed = Calendar.from_ical(path.read_bytes())
    event = parsed.walk("VEVENT")[0]
    assert event.decoded("DTSTART") == datetime(2026, 10, 14, 12, 30, tzinfo=timezone.utc)
    assert parsed["REFRESH-INTERVAL"].to_ical() == b"PT12H"


def test_all_day_event_uses_date_value(tmp_path: Path) -> None:
    path = tmp_path / "market.ics"
    _write([_all_day("all-day@example")], "market", path)
    event = Calendar.from_ical(path.read_bytes()).walk("VEVENT")[0]
    assert event.decoded("DTSTART") == date(2026, 12, 25)
    assert event["DTSTART"].params["VALUE"] == "DATE"


def test_description_output_is_independent_of_mapping_order(tmp_path: Path) -> None:
    first = _all_day("stable@example")
    first.description = {"Ticker": "NVDA", "Company": "NVIDIA"}
    second = _all_day("stable@example")
    second.description = {"Company": "NVIDIA", "Ticker": "NVDA"}

    first_path = tmp_path / "first.ics"
    second_path = tmp_path / "second.ics"
    _write([first], "market", first_path)
    _write([second], "market", second_path)

    assert first_path.read_bytes() == second_path.read_bytes()


def test_description_is_localized_to_chinese(tmp_path: Path) -> None:
    item = _all_day("localized@example", "earnings")
    item.description = {
        "Ticker": "NVDA",
        "Company": "NVIDIA Corporation",
        "Release": "Consumer Price Index for November 2026",
        "Earnings Time": "TAS",
        "Fiscal Quarter": "2026Q4",
        "Fiscal Quarter Source": "calendar-quarter fallback; Yahoo does not expose a fiscal period here",
    }
    item.source = "Yahoo Finance via yfinance"
    item.metadata = {"ticker": "NVDA"}
    path = tmp_path / "earnings.ics"

    _write([item], "earnings", path)

    description = str(Calendar.from_ical(path.read_bytes()).walk("VEVENT")[0]["DESCRIPTION"])
    assert "股票代码: NVDA" in description
    assert "公司: 英伟达" in description
    assert "发布项目: 消费者价格指数，2026年十一月" in description
    assert "财报时段: 时间待定（TAS）" in description
    assert "财务季度: 2026年第4季度" in description
    assert "财务季度来源: 采用自然季度备用值" in description
    assert "来源: 雅虎财经（通过 yfinance）" in description
    assert "来源链接: https://example.com" in description
    assert "最后更新: 2026-09-15T00:00:00+00:00" in description
    assert "Source:" not in description
    assert "Last Updated:" not in description


def test_all_calendar_is_exact_union_without_duplicates(tmp_path: Path) -> None:
    macro = [_timed("macro@example")]
    earnings = [_all_day("earnings@example", "earnings")]
    market = [_all_day("market@example")]
    _write(macro, "macro", tmp_path / "macro.ics")
    _write(earnings, "earnings", tmp_path / "earnings.ics")
    _write(market, "market", tmp_path / "market.ics")
    _write(macro + earnings + market + macro, "all", tmp_path / "all.ics")
    result = validate_directory(tmp_path)
    assert len(result["all"]) == 3
