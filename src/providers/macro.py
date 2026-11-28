from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Callable

import requests

from src.config import AppConfig
from src.models import CalendarEvent, FetchResult, merge_scoped_events
from src.providers.bea import BEA_SCOPE, BEA_URL, parse_bea_schedule
from src.providers.bls import BLS_SCOPE, fetch_bls_schedules
from src.providers.census import CENSUS_SCOPE, CENSUS_URL, parse_retail_schedule
from src.providers.fed import FED_SCOPE, FED_URL, parse_fomc_calendar
from src.providers.ism import (
    ISM_CONFIRMED_METHODS,
    ISM_KINDS,
    ISM_SCOPE,
    ISM_URL,
    derived_ism_schedule,
    fetch_ism_press_releases,
    parse_ism_schedule,
)
from src.providers.recurring import DOL_SCOPE, initial_claims_schedule
from src.utils.http import get_text
from src.utils.timezone import EASTERN

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
            events, errors = fetch_bls_schedules(session, config)
            if events:
                # A shorter feed or one failed table must not erase other UIDs.
                by_uid = {
                    event.uid: event for event in cached
                    if event.scope == BLS_SCOPE and config.macro[event.kind]
                }
                by_uid.update((event.uid, event) for event in events)
                fresh.extend(by_uid.values())
                successful.add(BLS_SCOPE)
            else:
                failed[BLS_SCOPE] = "; ".join(errors) or "no enabled releases"
            if errors:
                status = "partial source refresh" if events else "cached dates retained"
                warnings.append(f"{BLS_SCOPE} {status}: {'; '.join(errors)}")
    run_remote(BEA_SCOPE, BEA_URL, parse_bea_schedule)
    run_remote(CENSUS_SCOPE, CENSUS_URL, parse_retail_schedule)
    run_remote(FED_SCOPE, FED_URL, parse_fomc_calendar)

    if ISM_SCOPE in enabled_scopes:
        # Rules fill only uncovered UIDs. Confirmed dates survive blocked or
        # partial official pages, and newly published official rows win.
        by_uid = {
            event.uid: event
            for event in derived_ism_schedule(config, range_start.year, range_end.year)
        }
        by_uid.update(
            (event.uid, event) for event in cached
            if event.scope == ISM_SCOPE and config.macro[event.kind]
            and event.description.get("Schedule Method") in ISM_CONFIRMED_METHODS
        )
        if not offline:
            official: list[CalendarEvent] = []
            try:
                payload = get_text(session, ISM_URL, timeout=config.request_timeout_seconds)
                official = parse_ism_schedule(payload, config)
            except (requests.RequestException, ValueError) as exc:
                warnings.append(f"{ISM_SCOPE} official table unavailable ({type(exc).__name__}: {exc})")

            eastern_today = now.astimezone(EASTERN).date()
            upcoming_kinds = {
                event.kind for event in official
                if eastern_today <= event.start.date() <= eastern_today + timedelta(days=45)
            }
            missing_kinds = {kind for kind in ISM_KINDS if config.macro[kind]} - upcoming_kinds
            if missing_kinds:
                wire_dates, wire_errors = fetch_ism_press_releases(
                    session, config, kinds=missing_kinds, today=eastern_today,
                )
                by_uid.update((event.uid, event) for event in wire_dates)
                if wire_errors:
                    warnings.append(
                        f"{ISM_SCOPE} PR Newswire fallback incomplete: {'; '.join(wire_errors)}; "
                        "kept confirmed dates and used rules where needed"
                    )
            by_uid.update((event.uid, event) for event in official)
        fresh.extend(by_uid.values())
        successful.add(ISM_SCOPE)

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
