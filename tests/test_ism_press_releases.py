from datetime import date, datetime, timezone

import pytest
import requests

from src.config import load_config
from src.providers import ism, macro

MFG = "/news-releases/manufacturing-pmi-at-55-5-october-2026-ism-manufacturing-pmi-report-302925617.html"
SVC = "/news-releases/services-pmi-at-54-5-october-2026-ism-services-pmi-report-302928112.html"
NOW = datetime(2026, 11, 28, 17, tzinfo=timezone.utc)


def release(series, *, day="Tuesday, December 1, 2026", time="10:00 a.m.", issuer="Institute for Supply Management"):
    return f"""<meta name="author" content="{issuer}">
      <section class="release-body"><div class="release-content"><p>
      The next ISM<sup>®</sup> {series} PMI<sup>®</sup> Report featuring November 2026 data
      will be released at <strong>{time}</strong> ET on {day}.
      </p></div></section>"""


def ism_only():
    config = load_config("config.yaml")
    for kind in config.macro:
        config.macro[kind] = kind in ism.ISM_KINDS
    return config


def test_newsroom_uses_latest_official_series_link_on_expected_host():
    page = f"""
    <a href="https://example.com{MFG}">Other host</a>
    <a href="{SVC}?tracking=1">Services report</a>
    <a href="{MFG}">Manufacturing report</a>
    <a href="{MFG.replace('302925617', '302894520')}">Older manufacturing report</a>
    """
    assert ism.latest_ism_wire_urls(page, set(ism.ISM_KINDS)) == {
        "ism_services": ism.WIRE_ORIGIN + SVC,
        "ism_manufacturing": ism.WIRE_ORIGIN + MFG,
    }


def test_wire_uses_exact_announcement_and_keeps_release_month_uid():
    event = ism.parse_ism_wire_release(
        release("Services", day="Thursday, December 3, 2026", time="11:15 a.m.").encode(),
        kind="ism_services", url=ism.WIRE_ORIGIN + SVC,
    )
    assert event.start.astimezone(timezone.utc) == datetime(2026, 12, 3, 16, 15, tzinfo=timezone.utc)
    assert event.uid == "macro-US-ISM_SERVICES-2026-12@finance-calendar"
    assert event.source_url == ism.WIRE_ORIGIN + SVC
    assert event.description["Schedule Method"] == ism.ISM_PRESS_RELEASE


@pytest.mark.parametrize("html", [
    release("Services", issuer="Not the issuer"),
    release("Manufacturing"),
    release("Services").replace("will be released", "may be released"),
])
def test_wire_does_not_confirm_wrong_issuer_wrong_series_or_estimates(html):
    with pytest.raises(ValueError):
        ism.parse_ism_wire_release(html, kind="ism_services", url=ism.WIRE_ORIGIN + SVC)


def test_wire_fetch_keeps_one_success_if_other_series_fails_or_is_stale(monkeypatch):
    listing = f'<a href="{MFG}">MFG</a><a href="{SVC}">SVC</a>'
    calls = []

    def get_text(_session, url, *, timeout):
        assert timeout <= 8
        calls.append(url)
        if url == ism.ISM_WIRE_URL:
            return listing
        if url == ism.WIRE_ORIGIN + MFG:
            return release("Manufacturing")
        if url == ism.WIRE_ORIGIN + SVC:
            return release("Services", day="Wednesday, November 4, 2026")
        raise AssertionError(url)

    monkeypatch.setattr(ism, "_get_wire_html", get_text)
    with requests.Session() as session:
        events, errors = ism.fetch_ism_press_releases(
            session, ism_only(), kinds=set(ism.ISM_KINDS), today=NOW.date(),
        )
    assert [e.kind for e in events] == ["ism_manufacturing"]
    assert len(errors) == 1 and "outside the upcoming window" in errors[0]
    assert len(calls) == 3


def test_partial_official_table_uses_wire_only_for_missing_series(monkeypatch):
    table = """<table><tr><th>Month</th><th>Manufacturing PMI</th><th>Services PMI</th></tr>
    <tr><td>December 2026</td><td>1</td><td></td></tr></table>"""
    service = ism.parse_ism_wire_release(
        release("Services", day="Thursday, December 3, 2026"), kind="ism_services", url=ism.WIRE_ORIGIN + SVC,
    )
    monkeypatch.setattr(macro, "get_text", lambda *_a, **_kw: table)

    def wire(_session, _config, *, kinds, today):
        assert kinds == {"ism_services"}
        assert today == NOW.date()
        return [service], []

    monkeypatch.setattr(macro, "fetch_ism_press_releases", wire)
    with requests.Session() as session:
        result = macro.fetch_macro_events(ism_only(), [], session=session, now=NOW)
    dec = {e.kind: e.description["Schedule Method"] for e in result.events if e.start.month == 12 and e.start.year == 2026}
    assert dec == {"ism_manufacturing": ism.ISM_OFFICIAL, "ism_services": ism.ISM_PRESS_RELEASE}


def test_wire_confirmation_survives_captcha_and_network_failure(monkeypatch):
    event = ism.parse_ism_wire_release(
        release("Manufacturing", day="Wednesday, December 2, 2026"),
        kind="ism_manufacturing", url=ism.WIRE_ORIGIN + MFG,
    )
    monkeypatch.setattr(macro, "get_text", lambda *_a, **_kw: "<form name='captcha_form'></form>")
    monkeypatch.setattr(macro, "fetch_ism_press_releases", lambda *_a, **_kw: ([], ["wire unavailable"]))
    with requests.Session() as session:
        result = macro.fetch_macro_events(ism_only(), [event], session=session, now=NOW)
    assert next(e for e in result.events if e.uid == event.uid) == event
    assert any("CAPTCHA" in msg for msg in result.warnings)
    assert any("PR Newswire fallback incomplete" in msg for msg in result.warnings)
    assert next(e for e in result.events if e.kind == "ism_services" and e.start.date() == date(2026, 12, 3)).description["Schedule Method"].startswith("Fallback:")
