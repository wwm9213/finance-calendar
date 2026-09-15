from __future__ import annotations

import logging
import math
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable

import pandas as pd
import yfinance as yf

from src.config import AppConfig
from src.models import CalendarEvent, FetchResult, merge_scoped_events
from src.utils.timezone import EASTERN, ensure_aware

LOGGER = logging.getLogger(__name__)
SOURCE = "Yahoo Finance via yfinance"


def _clean_number(value: Any) -> str | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, (int, float)):
        if isinstance(value, float) and math.isnan(value):
            return None
        return f"{value:,.4g}"
    return str(value)


def _calendar_quarter(day: date) -> str:
    return f"{day.year}Q{(day.month - 1) // 3 + 1}"


def _cached_company(cached: Iterable[CalendarEvent], ticker: str) -> str | None:
    return next(
        (
            str(event.metadata.get("company"))
            for event in cached
            if event.metadata.get("ticker") == ticker and event.metadata.get("company")
        ),
        None,
    )


def reconcile_earnings_uids(
    fresh: list[CalendarEvent], cached: list[CalendarEvent], *, max_shift_days: int = 75
) -> list[CalendarEvent]:
    """Preserve a quarter's UID when a provider moves the expected report date."""
    for ticker in {str(event.metadata.get("ticker")) for event in fresh}:
        new_items = sorted(
            [event for event in fresh if event.metadata.get("ticker") == ticker],
            key=lambda event: event.start,
        )
        old_items = sorted(
            [event for event in cached if event.metadata.get("ticker") == ticker],
            key=lambda event: event.start,
        )
        available = set(range(len(old_items)))
        for event in new_items:
            event_day = event.start.date() if isinstance(event.start, datetime) else event.start
            choices: list[tuple[int, int]] = []
            for index in available:
                old_start = old_items[index].start
                old_day = old_start.date() if isinstance(old_start, datetime) else old_start
                choices.append((abs((event_day - old_day).days), index))
            if choices:
                distance, index = min(choices)
                if distance <= max_shift_days:
                    old_event = old_items[index]
                    event.uid = old_event.uid
                    old_quarter = old_event.description.get("Fiscal Quarter")
                    if old_quarter:
                        event.description["Fiscal Quarter"] = old_quarter
                    available.remove(index)
    return fresh


def _extract_calendar_estimates(ticker: yf.Ticker) -> tuple[dict[str, Any], list[Any]]:
    try:
        calendar = ticker.calendar or {}
        dates = calendar.get("Earnings Date") or []
        if not isinstance(dates, list):
            dates = [dates]
        return calendar, dates
    except Exception:
        return {}, []


def _future_rows(ticker: yf.Ticker) -> list[tuple[datetime, dict[str, Any]]]:
    table = ticker.get_earnings_dates(limit=12)
    rows: list[tuple[datetime, dict[str, Any]]] = []
    if table is None or table.empty:
        return rows
    for index, row in table.iterrows():
        timestamp = pd.Timestamp(index)
        if pd.isna(timestamp):
            continue
        value = ensure_aware(timestamp.to_pydatetime(), EASTERN)
        rows.append((value, row.to_dict()))
    return rows


def _fetch_ticker(
    symbol: str,
    config: AppConfig,
    cached: list[CalendarEvent],
    *,
    today: date,
) -> list[CalendarEvent]:
    ticker = yf.Ticker(symbol)
    calendar, fallback_dates = _extract_calendar_estimates(ticker)
    try:
        rows = _future_rows(ticker)
    except Exception:
        rows = []

    if not rows:
        for raw_date in fallback_dates[:1]:
            value = raw_date.to_pydatetime() if hasattr(raw_date, "to_pydatetime") else raw_date
            if isinstance(value, date) and not isinstance(value, datetime):
                value = datetime(value.year, value.month, value.day, tzinfo=EASTERN)
            if isinstance(value, datetime):
                rows.append((ensure_aware(value, EASTERN), {}))
    if not rows:
        raise ValueError("no earnings date returned")

    company = _cached_company(cached, symbol) or symbol
    try:
        info = ticker.get_info()
        company = info.get("shortName") or info.get("longName") or company
    except Exception as exc:
        LOGGER.warning("%s company-name lookup failed: %s", symbol, exc)

    range_start = today - timedelta(days=config.history_days)
    range_end = today + timedelta(days=config.lookahead_days)
    scope = f"earnings:{symbol}"
    events: list[CalendarEvent] = []
    seen_days: set[date] = set()
    for raw_start, row in sorted(rows, key=lambda item: item[0]):
        local = raw_start.astimezone(EASTERN)
        day = local.date()
        if day in seen_days or not range_start <= day <= range_end:
            continue
        seen_days.add(day)
        if local.hour < 11 and local.hour != 0:
            timing = "BMO"
        elif local.hour >= 16:
            timing = "AMC"
        else:
            timing = "TAS"

        quarter = _calendar_quarter(day)
        fiscal_source = "calendar-quarter fallback; Yahoo does not expose a fiscal period here"
        fiscal_value = row.get("Fiscal Quarter") or row.get("Fiscal Quarter Ending")
        if fiscal_value and not pd.isna(fiscal_value):
            quarter = str(fiscal_value)
            fiscal_source = "Yahoo Finance"

        description = {
            "Ticker": symbol,
            "Company": company,
            "Earnings Date": day.isoformat(),
            "Earnings Time": timing,
            "Fiscal Quarter": quarter,
            "Fiscal Quarter Source": fiscal_source,
            "EPS Estimate": _clean_number(row.get("EPS Estimate") or calendar.get("Earnings Average")),
            "Revenue Estimate": _clean_number(calendar.get("Revenue Average")),
        }
        source_url = f"https://finance.yahoo.com/quote/{symbol}/"
        uid = f"earnings-{symbol}-{quarter.replace(' ', '-')}@finance-calendar"
        if timing == "TAS":
            event = CalendarEvent(
                uid=uid,
                category="earnings",
                kind="earnings",
                summary=f"📊 {symbol} · {company} 财报 [TAS]",
                start=day,
                end=day + timedelta(days=1),
                description=description,
                source=SOURCE,
                source_url=source_url,
                scope=scope,
                all_day=True,
                metadata={"ticker": symbol, "company": company},
            )
        else:
            event = CalendarEvent(
                uid=uid,
                category="earnings",
                kind="earnings",
                summary=f"📊 {symbol} · {company} 财报 [{timing}]",
                start=local,
                end=local + timedelta(minutes=30),
                description=description,
                source=SOURCE,
                source_url=source_url,
                scope=scope,
                metadata={"ticker": symbol, "company": company},
            )
        events.append(event)
    if not events:
        raise ValueError("no earnings dates in configured window")
    return reconcile_earnings_uids(events, cached)


def fetch_earnings_events(
    config: AppConfig,
    cached: list[CalendarEvent],
    *,
    now: datetime | None = None,
    offline: bool = False,
) -> FetchResult:
    now = now or datetime.now(timezone.utc)
    today = now.astimezone(EASTERN).date()
    enabled_scopes = {f"earnings:{symbol}" for symbol in config.stocks}
    successful: set[str] = set()
    failed: dict[str, str] = {}
    fresh: list[CalendarEvent] = []
    warnings: list[str] = []

    for symbol in config.stocks:
        scope = f"earnings:{symbol}"
        if offline:
            failed[scope] = "offline mode"
            continue
        try:
            fresh.extend(_fetch_ticker(symbol, config, cached, today=today))
            successful.add(scope)
        except Exception as exc:
            message = f"{scope} failed: {type(exc).__name__}: {exc}"
            failed[scope] = message
            warnings.append(message)

    merged = merge_scoped_events(
        cached,
        fresh,
        enabled_scopes=enabled_scopes,
        successful_scopes=successful,
    )
    return FetchResult(merged, successful, failed, warnings)
