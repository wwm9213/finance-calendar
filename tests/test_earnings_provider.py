from dataclasses import replace
from datetime import date, datetime

import pandas as pd

from src.config import AppConfig, MACRO_DEFAULTS, MARKET_DEFAULTS
from src.models import CalendarEvent
from src.providers import earnings
from src.utils.timezone import EASTERN


def _config() -> AppConfig:
    return AppConfig(
        timezone="Asia/Shanghai",
        calendar_name="Test",
        lookahead_days=400,
        history_days=30,
        stocks=("NVDA",),
        macro=dict(MACRO_DEFAULTS),
        market=dict(MARKET_DEFAULTS),
        request_timeout_seconds=30,
        claims_weeks_ahead=16,
    )


def test_cached_company_avoids_extra_yahoo_requests(monkeypatch) -> None:
    class FakeTicker:
        @property
        def calendar(self):
            raise AssertionError("calendar fallback must not run when earnings rows exist")

        def get_earnings_dates(self, limit=12):
            index = pd.DatetimeIndex([datetime(2026, 11, 18, 0, 0, tzinfo=EASTERN)])
            return pd.DataFrame([{"EPS Estimate": 1.25}], index=index)

        def get_info(self):
            raise AssertionError("cached company must avoid the info lookup")

    monkeypatch.setattr(earnings.yf, "Ticker", lambda _symbol: FakeTicker())
    cached = [
        CalendarEvent(
            uid="earnings-NVDA-2026Q3@finance-calendar",
            category="earnings",
            kind="earnings",
            summary="NVDA earnings",
            start=date(2026, 11, 18),
            end=date(2026, 11, 19),
            description={"Fiscal Quarter": "2026Q3"},
            source="cache",
            source_url="https://example.com",
            scope="earnings:NVDA",
            all_day=True,
            metadata={"ticker": "NVDA", "company": "NVIDIA Corporation"},
        )
    ]

    events = earnings._fetch_ticker("NVDA", _config(), cached, today=date(2026, 9, 15))

    assert len(events) == 1
    assert events[0].metadata["company"] == "NVIDIA Corporation"
    assert events[0].description["EPS Estimate"] == "1.25"


def test_empty_stock_list_needs_no_worker_pool() -> None:
    result = earnings.fetch_earnings_events(
        replace(_config(), stocks=()),
        [],
        now=datetime(2026, 9, 15, tzinfo=EASTERN),
    )

    assert result.events == []
    assert result.failed_scopes == {}
