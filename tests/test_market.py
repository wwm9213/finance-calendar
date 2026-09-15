from datetime import datetime, timezone

from src.config import AppConfig
from src.providers.market import fetch_market_events


def test_nyse_observed_holiday_early_close_and_witching() -> None:
    config = AppConfig(
        timezone="Asia/Shanghai",
        calendar_name="Test",
        lookahead_days=140,
        history_days=0,
        stocks=(),
        macro={},
        market={"holidays": True, "early_close": True, "quadruple_witching": True},
        request_timeout_seconds=30,
        claims_weeks_ahead=16,
    )
    result = fetch_market_events(config, now=datetime(2026, 6, 1, tzinfo=timezone.utc))
    by_kind = {kind: [event for event in result.events if event.kind == kind] for kind in ("holiday", "early_close", "quadruple_witching")}
    assert any(event.start.isoformat() == "2026-07-03" for event in by_kind["holiday"])
    assert any(event.start.isoformat() == "2026-09-18" for event in by_kind["quadruple_witching"])
