"""Refresh only the verified BLS snapshot from a network that can reach BLS."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.config import load_config
from src.providers.bls import BLS_SCOPE, fetch_bls_schedules
from src.utils.cache import CacheStore
from src.utils.http import build_session


def refresh(root: Path, *, now: datetime) -> tuple[int, list[str]]:
    config = load_config(root / "config.yaml")
    today = now.astimezone(timezone.utc).date()
    first = today - timedelta(days=config.history_days)
    last = today + timedelta(days=config.lookahead_days)
    with build_session() as session:
        releases, errors = fetch_bls_schedules(session, config)

    store = CacheStore(root / "data")
    previous = store.load("macro")
    by_uid = {event.uid: event for event in previous.events}
    updates = 0
    for event in releases:
        if event.scope != BLS_SCOPE or not first <= event.start.date() <= last:
            continue
        old = by_uid.get(event.uid)
        if old is None or old.start != event.start:
            by_uid[event.uid] = event
            updates += 1
    if releases and not errors and not any(
        event.scope == BLS_SCOPE and today <= event.start.date() <= last for event in releases
    ):
        errors.append("BLS returned no upcoming releases within the configured window")
    if updates:
        store.save_if_changed("macro", list(by_uid.values()), previous, now=now)
    return updates, errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    args = parser.parse_args()
    updates, errors = refresh(args.root.resolve(), now=datetime.now(timezone.utc))
    print(f"Verified BLS dates added or changed: {updates}")
    for error in errors:
        print(f"BLS warning: {error}")
    return 1 if errors and not updates else 0


if __name__ == "__main__":
    raise SystemExit(main())
