from datetime import date, datetime, timezone

import pytest
import requests

from src.config import load_config
from src.providers import bls, macro
from src.providers.ism import ISM_OFFICIAL, ISM_SCOPE, ISM_URL, parse_ism_schedule

TODAY = datetime(2026, 11, 28, 7, tzinfo=timezone.utc)


@pytest.fixture
def config():
    cfg = load_config("config.yaml")
    for key in cfg.macro:
        cfg.macro[key] = key in {"nfp", "unemployment", "cpi", "core_cpi", "ppi", "core_ppi",
                                 "ism_manufacturing", "ism_services"}
    return cfg


def bls_table(reference, publication, hour="08:30 AM"):
    return f"""
    <table class="release-list"><thead><tr>
      <th>Reference Month</th><th>Release Date</th><th>Release Time</th>
    </tr></thead><tbody><tr><td>{reference}</td><td>{publication}</td><td>{hour}</td>
    </tr></tbody></table>
    """


def ism_table(rows):
    return f"""<table><tr><th>Month</th><th>MANUFACTURING PMI</th><th>Services PMI</th></tr>
    {rows}</table>"""


def fake_bls(monkeypatch, feeds):
    urls = []

    def fetch(_session, url, *, timeout, **_kw):
        urls.append(url)
        assert timeout <= 8
        if url == bls.BLS_ICS_URL:
            payload = feeds[None]
        else:
            payload = feeds[url.rsplit("/", 1)[-1]]
        if isinstance(payload, Exception):
            raise payload
        return payload

    monkeypatch.setattr(bls, "get_text", fetch)
    return urls


DECEMBER_ICS = """BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:bls-cpi
DTSTART;TZID=America/New_York:20261210T083000
SUMMARY:Consumer Price Index for November 2026
END:VEVENT
END:VCALENDAR
"""


@pytest.mark.parametrize("ics_status", [DECEMBER_ICS, requests.HTTPError("403 Forbidden")])
def test_official_tables_fill_new_year_even_if_ics_is_blocked_or_short(config, monkeypatch, ics_status):
    calls = fake_bls(monkeypatch, {
        None: ics_status,
        "empsit.htm": bls_table("December 2026", "Jan. 08, 2027"),
        "cpi.htm": bls_table("December 2026", "Jan. 13, 2027"),
        "ppi.htm": bls_table("December 2026", "Jan. 14, 2027"),
    })
    events, errors = bls.fetch_bls_schedules(requests.Session(), config)
    jan = {event.kind: event for event in events if event.start.month == 1}
    assert len(jan) == 6
    assert jan["nfp"].start.date() == date(2027, 1, 8)
    assert jan["cpi"].start.date() == date(2027, 1, 13)
    assert jan["ppi"].start.date() == date(2027, 1, 14)
    assert jan["cpi"].uid == "macro-US-CPI-2026-12@finance-calendar"
    assert jan["cpi"].start.astimezone(timezone.utc) == datetime(2027, 1, 13, 13, 30, tzinfo=timezone.utc)
    assert len(calls) == 4
    assert bool(errors) is isinstance(ics_status, Exception)


def test_release_table_uses_explicit_period_and_dst(config):
    event = bls.parse_bls_release_schedule(
        bls_table("January 2027", "Mar. 12, 2027", "09:00 AM"), config, page="cpi.htm"
    )[0]
    moved = bls.parse_bls_release_schedule(
        bls_table("January 2027", "March 16, 2027", "09:00 AM"), config, page="cpi.htm"
    )[0]
    assert event.uid == moved.uid == "macro-US-CPI-2027-01@finance-calendar"
    assert event.start.astimezone(timezone.utc).hour == 14
    assert moved.start.astimezone(timezone.utc).hour == 13


def test_official_table_can_correct_an_existing_ics_date(config, monkeypatch):
    fake_bls(monkeypatch, {
        None: DECEMBER_ICS, "cpi.htm": bls_table("November 2026", "Dec. 11, 2026"),
        "empsit.htm": requests.Timeout(), "ppi.htm": requests.Timeout(),
    })
    events, _ = bls.fetch_bls_schedules(requests.Session(), config)
    assert len(events) == 2
    assert all(event.start.day == 11 for event in events)
    assert {event.uid for event in events} == {
        "macro-US-CPI-2026-11@finance-calendar", "macro-US-CORE_CPI-2026-11@finance-calendar"
    }


def test_partial_bls_refresh_preserves_other_releases(config, monkeypatch):
    fake_bls(monkeypatch, {
        None: requests.HTTPError("403 Forbidden"), "empsit.htm": requests.Timeout("timed out"),
        "cpi.htm": bls_table("November 2026", "Dec. 11, 2026"),
        "ppi.htm": "<html>unexpected page</html>",
    })
    monkeypatch.setattr(macro, "get_text", lambda *_a, **_k: "<form name='captcha_form'></form>")
    cached = [
        *bls.parse_bls_release_schedule(bls_table("November 2026", "Dec. 04, 2026"), config, page="empsit.htm"),
        *bls.parse_bls_release_schedule(bls_table("November 2026", "Dec. 10, 2026"), config, page="cpi.htm"),
        *bls.parse_bls_release_schedule(bls_table("November 2026", "Dec. 15, 2026"), config, page="ppi.htm"),
    ]
    result = macro.fetch_macro_events(config, cached, session=requests.Session(), now=TODAY)
    dates = {e.kind: e.start.day for e in result.events if e.scope == bls.BLS_SCOPE}
    assert dates == {"nfp": 4, "unemployment": 4, "cpi": 11, "core_cpi": 11, "ppi": 15, "core_ppi": 15}
    assert any("partial source refresh" in warning for warning in result.warnings)


def test_all_bls_sources_fail_without_pruning_valid_cached_dates(config, monkeypatch):
    fake_bls(monkeypatch, dict.fromkeys((None, "empsit.htm", "cpi.htm", "ppi.htm"), requests.Timeout()))
    monkeypatch.setattr(macro, "get_text", lambda *_a, **_k: "")
    cached = bls.parse_bls_release_schedule(bls_table("November 2026", "Dec. 04, 2026"), config, page="empsit.htm")
    result = macro.fetch_macro_events(config, cached, session=requests.Session(), now=TODAY)
    assert [e for e in result.events if e.scope == bls.BLS_SCOPE] == cached
    assert bls.BLS_SCOPE in result.failed_scopes
    assert bls.BLS_SCOPE not in result.successful_scopes


def test_ism_parses_all_year_tables_ignores_footnotes_and_preserves_valid_cells(config):
    html = ism_table("""
      <tr><td>January 2026</td><td>5<sup>1</sup></td><td>7</td></tr>
      <tr><td>July 2026</td><td>1</td><td>6**</td></tr>
      <tr><td>ISM Supply Chain Planning Forecast</td><td>16</td><td>16</td></tr>
    """) + ism_table("<tr><td>February 2027</td><td>31</td><td>3</td></tr>")
    events = parse_ism_schedule(html, config)
    assert [e.start.date() for e in events] == [
        date(2026, 1, 5), date(2026, 1, 7), date(2026, 7, 1), date(2026, 7, 6), date(2027, 2, 3)
    ]
    assert all(e.description["Schedule Method"] == ISM_OFFICIAL for e in events)


@pytest.mark.parametrize("official_page", [
    "<form name='captcha_form'></form>",
    ism_table("<tr><td>December 2026</td><td>1</td><td>3</td></tr>"),
])
def test_ism_keeps_confirmed_cache_and_fills_gaps(config, monkeypatch, official_page):
    def fetch(_session, url, **_kwargs):
        assert url == ISM_URL
        return official_page

    # Synthetic January 2027 exception to check precedence, not a forecast.
    cached = parse_ism_schedule(
        ism_table("<tr><td>January 2027</td><td>5</td><td>7</td></tr>"), config
    )
    config.macro["nfp"] = config.macro["unemployment"] = config.macro["cpi"] = False
    config.macro["core_cpi"] = config.macro["ppi"] = config.macro["core_ppi"] = False
    monkeypatch.setattr(macro, "get_text", fetch)
    result = macro.fetch_macro_events(config, cached, session=requests.Session(), now=TODAY)
    events = {e.uid: e for e in result.events if e.scope == ISM_SCOPE}
    assert events[cached[0].uid].start.day == 5
    assert events[cached[0].uid].description["Schedule Method"] == ISM_OFFICIAL
    assert events["macro-US-ISM_SERVICES-2027-03@finance-calendar"].description["Schedule Method"].startswith("Fallback:")
    dec = events["macro-US-ISM_SERVICES-2026-12@finance-calendar"]
    assert dec.start.day == 3
    if "captcha" in official_page:
        assert any("CAPTCHA" in warning for warning in result.warnings)
    else:
        assert dec.description["Schedule Method"] == ISM_OFFICIAL


def test_ism_new_official_date_updates_same_uid(config, monkeypatch):
    for flag in ("nfp", "unemployment", "cpi", "core_cpi", "ppi", "core_ppi"):
        config.macro[flag] = False
    cached = parse_ism_schedule(ism_table("<tr><td>December 2026</td><td>1</td><td>4</td></tr>"), config)
    updated = ism_table("<tr><td>December 2026</td><td>1</td><td>3</td></tr>")
    monkeypatch.setattr(macro, "get_text", lambda *_a, **_kw: updated)
    result = macro.fetch_macro_events(config, cached, session=requests.Session(), now=TODAY)
    matches = [e for e in result.events if e.uid == cached[1].uid]
    assert len(matches) == 1
    assert matches[0].start.day == 3
