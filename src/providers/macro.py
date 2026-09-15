from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Callable

import requests

from src.config import AppConfig
from src.models import CalendarEvent, FetchResult, merge_scoped_events
from src.providers.bea import BEA_SCOPE, BEA_URL, parse_bea_schedule
from src.providers.bls import BLS_ICS_URL, BLS_SCOPE, parse_bls_ics
from src.providers.census import CENSUS_SCOPE, CENSUS_URL, parse_retail_schedule
from src.providers.fed import FED_SCOPE, FED_URL, parse_fomc_calendar
from src.providers.fred import fetch_fred_bls_fallback
from src.providers.ism import ISM_SCOPE, ISM_URL, derived_ism_schedule, parse_ism_schedule
from src.providers.recurring import DOL_SCOPE, initial_claims_schedule
from src.utils.http import get_text

KIND_FLAGS = {
    "nfp": "nfp",
    "unemployment": "unemployment",
    "jobless_claims": "jobless_claims",
    "cpi": "cpi",
    "core_cpi": "core_cpi",
    "ppi": "ppi",
    "core_ppi": "core_ppi",
    "pce": "pce",
    "core_pce": "core_pce",
    "gdp": "gdp",
    "retail_sales": "retail_sales",
    "ism_manufacturing": "ism_manufacturing",
    "ism_services": "ism_services",
    "fomc_meeting": "fomc",
    "fomc_decision": "fomc",
    "fomc_minutes": "fomc_minutes",
}


def _within_window(event: CalendarEvent, start: date, end: date) -> bool:
    event_day = event.start.date() if isinstance(event.start, datetime) else event.start
    return start <= event_day <= end


def fetch_macro_events(
    config: AppConfig,
    cached: list[CalendarEvent],
    *,
    session: requests.Session,
    now: datetime | None = None,
    offline: bool = False,
) -> FetchResult:
    now = now or datetime.now(timezone.utc)
    today = now.astimezone(timezone.utc).date()
    range_start = today - timedelta(days=config.history_days)
    range_end = today + timedelta(days=config.lookahead_days)

    enabled_scopes: set[str] = set()
    if any(config.macro[key] for key in ("nfp", "unemployment", "cpi", "core_cpi", "ppi", "core_ppi")):
        enabled_scopes.add(BLS_SCOPE)
    if any(config.macro[key] for key in ("pce", "core_pce", "gdp")):
        enabled_scopes.add(BEA_SCOPE)
    if config.macro["retail_sales"]:
        enabled_scopes.add(CENSUS_SCOPE)
    if any(config.macro[key] for key in ("ism_manufacturing", "ism_services")):
        enabled_scopes.add(ISM_SCOPE)
    if any(config.macro[key] for key in ("fomc", "fomc_minutes")):
        enabled_scopes.add(FED_SCOPE)
    if config.macro["jobless_claims"]:
        enabled_scopes.add(DOL_SCOPE)

    fresh: list[CalendarEvent] = []
    successful: set[str] = set()
    failed: dict[str, str] = {}
    warnings: list[str] = []

    def run_remote(scope: str, url: str, parser: Callable[[str, AppConfig], list[CalendarEvent]], *, accept: str = "text/html") -> None:
        if scope not in enabled_scopes:
            return
        if offline:
            failed[scope] = "offline mode"
            return
        try:
            payload = get_text(
                session,
                url,
                timeout=config.request_timeout_seconds,
                accept=accept,
            )
            fresh.extend(parser(payload, config))
            successful.add(scope)
        except Exception as exc:  # Each source fails independently by design.
            message = f"{scope} failed: {type(exc).__name__}: {exc}"
            failed[scope] = message
            warnings.append(message)

    if BLS_SCOPE in enabled_scopes:
        if offline:
            failed[BLS_SCOPE] = "offline mode"
        else:
            try:
                payload = get_text(
                    session,
                    BLS_ICS_URL,
                    timeout=config.request_timeout_seconds,
                    accept="text/calendar,*/*;q=0.8",
                )
                fresh.extend(parse_bls_ics(payload, config))
                successful.add(BLS_SCOPE)
            except Exception as primary_exc:
                try:
                    fresh.extend(
                        fetch_fred_bls_fallback(
                            session,
                            config,
                            start_year=range_start.year,
                            end_year=range_end.year,
                        )
                    )
                    successful.add(BLS_SCOPE)
                    message = (
                        f"{BLS_SCOPE} official ICS unavailable ({type(primary_exc).__name__}: "
                        f"{primary_exc}); used FRED's BLS-supplied release calendar"
                    )
                    warnings.append(message)
                except Exception as fallback_exc:
                    message = (
                        f"{BLS_SCOPE} failed: primary={type(primary_exc).__name__}: {primary_exc}; "
                        f"fallback={type(fallback_exc).__name__}: {fallback_exc}"
                    )
                    failed[BLS_SCOPE] = message
                    warnings.append(message)
    run_remote(BEA_SCOPE, BEA_URL, parse_bea_schedule)
    run_remote(CENSUS_SCOPE, CENSUS_URL, parse_retail_schedule)
    run_remote(FED_SCOPE, FED_URL, parse_fomc_calendar)

    if ISM_SCOPE in enabled_scopes:
        try:
            if offline:
                raise RuntimeError("offline mode")
            payload = get_text(session, ISM_URL, timeout=config.request_timeout_seconds)
            fresh.extend(parse_ism_schedule(payload, config))
            successful.add(ISM_SCOPE)
        except Exception as exc:
            fallback = derived_ism_schedule(config, range_start.year, range_end.year)
            fresh.extend(fallback)
            successful.add(ISM_SCOPE)
            message = (
                f"{ISM_SCOPE} official table unavailable ({type(exc).__name__}: {exc}); "
                "used the published first/third-business-day rule"
            )
            warnings.append(message)

    if DOL_SCOPE in enabled_scopes:
        fresh.extend(initial_claims_schedule(today, config))
        successful.add(DOL_SCOPE)

    enabled_kinds = {kind for kind, flag in KIND_FLAGS.items() if config.macro[flag]}
    filtered_cache = [event for event in cached if event.kind in enabled_kinds]
    merged = merge_scoped_events(
        filtered_cache,
        fresh,
        enabled_scopes=enabled_scopes,
        successful_scopes=successful,
    )
    merged = [event for event in merged if _within_window(event, range_start, range_end)]
    return FetchResult(merged, successful, failed, warnings)
