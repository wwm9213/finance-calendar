from datetime import datetime, timezone

from src import refresh_bls_cache
from src.models import CalendarEvent
from src.providers.common import macro_event
from src.utils.cache import CacheStore
from src.utils.timezone import EASTERN

NOW = datetime(2026, 11, 28, 17, tzinfo=timezone.utc)


def event(kind: str, scope: str, period: str, start: datetime) -> CalendarEvent:
    return macro_event(
        kind=kind, summary=kind, start=start, period=period, source="official",
        source_url="https://example.com", scope=scope, release=kind,
    )


def test_refresh_seeds_known_dates_without_replacing_other_scopes_or_pruning(tmp_path, monkeypatch):
    (tmp_path / "config.yaml").write_text("{}")
    store = CacheStore(tmp_path / "data")
    old = [
        event("nfp", "macro:bls", "2026-11", datetime(2026, 12, 4, 8, 30, tzinfo=EASTERN)),
        event("cpi", "macro:bls", "2026-11", datetime(2026, 12, 10, 8, 30, tzinfo=EASTERN)),
        event("pce", "macro:bea", "2026-11", datetime(2026, 12, 23, 8, 30, tzinfo=EASTERN)),
    ]
    store.save_if_changed("macro", old, store.load("macro"), now=NOW)
    new = event("nfp", "macro:bls", "2026-12", datetime(2027, 1, 8, 8, 30, tzinfo=EASTERN))
    dated_history = event("nfp", "macro:bls", "2026-01", datetime(2026, 2, 6, 8, 30, tzinfo=EASTERN))
    monkeypatch.setattr(refresh_bls_cache, "fetch_bls_schedules", lambda *_a: ([new, dated_history], ["one source failed"]))
    assert refresh_bls_cache.refresh(tmp_path, now=NOW) == (1, ["one source failed"])
    assert {e.uid: e for e in store.load("macro").events} == {e.uid: e for e in [*old, new]}

    saved = store.path_for("macro").read_bytes()
    assert refresh_bls_cache.refresh(tmp_path, now=NOW)[0] == 0
    monkeypatch.setattr(refresh_bls_cache, "fetch_bls_schedules", lambda *_a: ([], ["403"]))
    assert refresh_bls_cache.refresh(tmp_path, now=NOW) == (0, ["403"])
    assert store.path_for("macro").read_bytes() == saved
