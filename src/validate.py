from __future__ import annotations

import argparse
from datetime import date, datetime
from pathlib import Path

from icalendar import Calendar

REQUIRED = ("UID", "DTSTAMP", "DTSTART", "DTEND", "SUMMARY", "DESCRIPTION")


def validate_file(path: Path) -> set[str]:
    try:
        calendar = Calendar.from_ical(path.read_bytes())
    except Exception as exc:
        raise ValueError(f"{path}: invalid iCalendar: {exc}") from exc
    if str(calendar.get("version", "")) != "2.0":
        raise ValueError(f"{path}: VERSION must be 2.0")

    uids: set[str] = set()
    for event in calendar.walk("VEVENT"):
        missing = [key for key in REQUIRED if event.get(key) is None]
        if missing:
            raise ValueError(f"{path}: VEVENT missing {', '.join(missing)}")
        uid = str(event["UID"])
        if uid in uids:
            raise ValueError(f"{path}: duplicate UID {uid}")
        uids.add(uid)
        start = event.decoded("DTSTART")
        end = event.decoded("DTEND")
        if type(start) is not type(end):
            raise ValueError(f"{path}: DTSTART/DTEND types differ for {uid}")
        if end <= start:
            raise ValueError(f"{path}: DTEND must be after DTSTART for {uid}")
        if isinstance(start, datetime) and start.tzinfo is None:
            raise ValueError(f"{path}: timed event is not timezone-aware for {uid}")
        if isinstance(start, date) and not isinstance(start, datetime):
            if event["DTSTART"].params.get("VALUE") != "DATE":
                raise ValueError(f"{path}: all-day DTSTART lacks VALUE=DATE for {uid}")
    return uids


def validate_directory(dist: Path) -> dict[str, set[str]]:
    expected = {name: dist / f"{name}.ics" for name in ("macro", "earnings", "market", "all")}
    missing = [str(path) for path in expected.values() if not path.exists()]
    if missing:
        raise ValueError(f"missing calendar files: {', '.join(missing)}")
    uid_sets = {name: validate_file(path) for name, path in expected.items()}
    combined = uid_sets["macro"] | uid_sets["earnings"] | uid_sets["market"]
    if uid_sets["all"] != combined:
        raise ValueError("all.ics UID set does not equal the three component calendars")
    return uid_sets


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate generated finance calendars")
    parser.add_argument("dist", nargs="?", default="dist")
    args = parser.parse_args()
    result = validate_directory(Path(args.dist))
    print("ICS validation passed: " + ", ".join(f"{name}={len(uids)}" for name, uids in result.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
