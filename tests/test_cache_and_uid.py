from dataclasses import replace
from datetime import date, timedelta

from src.models import CalendarEvent, merge_scoped_events
from src.providers.earnings import reconcile_earnings_uids


def _earning(day: date, uid: str) -> CalendarEvent:
    return CalendarEvent(
        uid=uid,
        category="earnings",
        kind="earnings",
        summary="NVDA earnings",
        start=day,
        end=day + timedelta(days=1),
        description={"Fiscal Quarter": "2026Q3"},
        source="Yahoo",
        source_url="https://example.com",
        scope="earnings:NVDA",
        all_day=True,
        metadata={"ticker": "NVDA"},
    )


def test_earnings_date_change_keeps_uid() -> None:
    cached = [_earning(date(2026, 11, 18), "earnings-NVDA-2026Q3@finance-calendar")]
    fresh = [_earning(date(2026, 11, 25), "temporary@finance-calendar")]
    reconcile_earnings_uids(fresh, cached)
    assert fresh[0].uid == cached[0].uid


def test_failed_scope_keeps_cache_while_successful_scope_replaces_it() -> None:
    cached = [
        _earning(date(2026, 11, 18), "nvda-old"),
        replace(
            _earning(date(2026, 10, 20), "amd-old"),
            scope="earnings:AMD",
            metadata={"ticker": "AMD"},
        ),
    ]
    fresh = [_earning(date(2026, 11, 25), "nvda-new")]
    merged = merge_scoped_events(
        cached,
        fresh,
        enabled_scopes={"earnings:NVDA", "earnings:AMD"},
        successful_scopes={"earnings:NVDA"},
    )
    assert {event.uid for event in merged} == {"nvda-new", "amd-old"}
