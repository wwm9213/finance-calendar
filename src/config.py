from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml


class ConfigError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class AppConfig:
    timezone: str
    calendar_name: str
    lookahead_days: int
    history_days: int
    stocks: tuple[str, ...]
    macro: dict[str, bool]
    market: dict[str, bool]
    request_timeout_seconds: int
    claims_weeks_ahead: int


MACRO_DEFAULTS = {
    "nfp": True,
    "unemployment": True,
    "jobless_claims": True,
    "cpi": True,
    "core_cpi": True,
    "ppi": True,
    "core_ppi": True,
    "pce": True,
    "core_pce": True,
    "gdp": True,
    "retail_sales": True,
    "ism_manufacturing": True,
    "ism_services": True,
    "fomc": True,
    "fomc_minutes": True,
}

MARKET_DEFAULTS = {
    "holidays": True,
    "early_close": True,
    "quadruple_witching": True,
}


def _bool_section(raw: Any, defaults: dict[str, bool], name: str) -> dict[str, bool]:
    if raw is None:
        return dict(defaults)
    if not isinstance(raw, dict):
        raise ConfigError(f"{name} must be a mapping")
    unknown = set(raw) - set(defaults)
    if unknown:
        raise ConfigError(f"unknown {name} keys: {', '.join(sorted(unknown))}")
    result = dict(defaults)
    for key, value in raw.items():
        if not isinstance(value, bool):
            raise ConfigError(f"{name}.{key} must be true or false")
        result[key] = value
    return result


def load_config(path: str | Path) -> AppConfig:
    config_path = Path(path)
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigError(f"cannot read {config_path}: {exc}") from exc

    if not isinstance(raw, dict):
        raise ConfigError("config root must be a mapping")

    timezone = str(raw.get("timezone", "Asia/Shanghai"))
    try:
        ZoneInfo(timezone)
    except ZoneInfoNotFoundError as exc:
        raise ConfigError(f"unknown timezone: {timezone}") from exc

    stocks_raw = raw.get("stocks", [])
    if not isinstance(stocks_raw, list) or not all(
        isinstance(symbol, str) and symbol.strip() for symbol in stocks_raw
    ):
        raise ConfigError("stocks must be a list of non-empty ticker strings")
    stocks = tuple(dict.fromkeys(symbol.strip().upper() for symbol in stocks_raw))

    lookahead_days = int(raw.get("lookahead_days", 400))
    history_days = int(raw.get("history_days", 30))
    request_timeout_seconds = int(raw.get("request_timeout_seconds", 30))
    claims_weeks_ahead = int(raw.get("claims_weeks_ahead", 16))
    if not 30 <= lookahead_days <= 1095:
        raise ConfigError("lookahead_days must be between 30 and 1095")
    if not 0 <= history_days <= 366:
        raise ConfigError("history_days must be between 0 and 366")
    if not 5 <= request_timeout_seconds <= 120:
        raise ConfigError("request_timeout_seconds must be between 5 and 120")
    if not 1 <= claims_weeks_ahead <= 104:
        raise ConfigError("claims_weeks_ahead must be between 1 and 104")

    return AppConfig(
        timezone=timezone,
        calendar_name=str(raw.get("calendar_name", "金融市场动态")),
        lookahead_days=lookahead_days,
        history_days=history_days,
        stocks=stocks,
        macro=_bool_section(raw.get("macro"), MACRO_DEFAULTS, "macro"),
        market=_bool_section(raw.get("market"), MARKET_DEFAULTS, "market"),
        request_timeout_seconds=request_timeout_seconds,
        claims_weeks_ahead=claims_weeks_ahead,
    )
