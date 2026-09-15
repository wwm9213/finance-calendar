from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from src.models import CalendarEvent


@dataclass(slots=True)
class CacheSnapshot:
    events: list[CalendarEvent]
    updated_at: datetime


class CacheStore:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def path_for(self, category: str) -> Path:
        return self.data_dir / f"{category}.json"

    def load(self, category: str) -> CacheSnapshot:
        path = self.path_for(category)
        if not path.exists():
            return CacheSnapshot([], datetime(1970, 1, 1, tzinfo=timezone.utc))
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            events = [CalendarEvent.from_dict(item) for item in payload.get("events", [])]
            updated_at = datetime.fromisoformat(payload["updated_at"])
            return CacheSnapshot(events, updated_at)
        except (OSError, ValueError, TypeError, KeyError) as exc:
            raise RuntimeError(f"invalid cache {path}: {exc}") from exc

    def save_if_changed(
        self,
        category: str,
        events: list[CalendarEvent],
        previous: CacheSnapshot,
        *,
        now: datetime,
    ) -> CacheSnapshot:
        normalized = sorted((event.to_dict() for event in events), key=lambda item: item["uid"])
        previous_normalized = sorted(
            (event.to_dict() for event in previous.events), key=lambda item: item["uid"]
        )
        if normalized == previous_normalized and self.path_for(category).exists():
            return previous

        updated_at = now.astimezone(timezone.utc).replace(microsecond=0)
        payload = {
            "version": 1,
            "updated_at": updated_at.isoformat(),
            "events": normalized,
        }
        self.path_for(category).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return CacheSnapshot(events, updated_at)
