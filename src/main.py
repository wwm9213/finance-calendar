from __future__ import annotations

import argparse
import logging
from datetime import datetime, time, timezone
from pathlib import Path

from src.calendar import build_calendar, write_calendar
from src.config import load_config
from src.providers.earnings import fetch_earnings_events
from src.providers.macro import fetch_macro_events
from src.providers.market import fetch_market_events
from src.utils.cache import CacheSnapshot, CacheStore
from src.utils.http import build_session

LOGGER = logging.getLogger("finance-calendar")


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate subscription-ready finance ICS calendars")
    parser.add_argument("--config", default="config.yaml", help="path to config.yaml")
    parser.add_argument("--root", default=".", help="project root containing data/ and dist/")
    parser.add_argument("--offline", action="store_true", help="skip remote sources and use cache")
    parser.add_argument("--today", help="override current UTC date (YYYY-MM-DD), useful for reproducible checks")
    return parser.parse_args()


def generate(
    root: Path,
    config_path: Path,
    *,
    now: datetime | None = None,
    offline: bool = False,
) -> dict[str, int]:
    now = now or datetime.now(timezone.utc)
    config = load_config(config_path)
    store = CacheStore(root / "data")
    session = build_session()

    previous: dict[str, CacheSnapshot] = {
        category: store.load(category) for category in ("macro", "earnings", "market")
    }
    results = {
        "macro": fetch_macro_events(
            config,
            previous["macro"].events,
            session=session,
            now=now,
            offline=offline,
        ),
        "earnings": fetch_earnings_events(
            config,
            previous["earnings"].events,
            now=now,
            offline=offline,
        ),
        "market": fetch_market_events(config, now=now),
    }

    current: dict[str, CacheSnapshot] = {}
    for category, result in results.items():
        if not result.events and previous[category].events:
            LOGGER.warning("%s produced no events; preserving the previous cache", category)
            result.events = previous[category].events
        current[category] = store.save_if_changed(
            category,
            result.events,
            previous[category],
            now=now,
        )
        for warning in result.warnings:
            LOGGER.warning("%s", warning)

    updated_at = {category: snapshot.updated_at for category, snapshot in current.items()}
    for category in ("macro", "earnings", "market"):
        calendar = build_calendar(
            current[category].events,
            category=category,
            calendar_name=config.calendar_name,
            timezone_name=config.timezone,
            updated_at_by_category=updated_at,
        )
        write_calendar(calendar, root / "dist" / f"{category}.ics")

    all_events = [event for category in ("macro", "earnings", "market") for event in current[category].events]
    all_calendar = build_calendar(
        all_events,
        category="all",
        calendar_name=config.calendar_name,
        timezone_name=config.timezone,
        updated_at_by_category=updated_at,
    )
    write_calendar(all_calendar, root / "dist" / "all.ics")

    counts = {category: len(snapshot.events) for category, snapshot in current.items()}
    counts["all"] = len({event.uid for event in all_events})
    for category, count in counts.items():
        LOGGER.info("generated dist/%s.ics (%d events)", category, count)
    return counts


def main() -> int:
    args = _arguments()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    root = Path(args.root).resolve()
    config_path = Path(args.config)
    if not config_path.is_absolute():
        config_path = root / config_path
    now = None
    if args.today:
        day = datetime.strptime(args.today, "%Y-%m-%d").date()
        now = datetime.combine(day, time(12, 0), tzinfo=timezone.utc)
    generate(root, config_path, now=now, offline=args.offline)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
