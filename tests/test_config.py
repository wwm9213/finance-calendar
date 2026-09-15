from pathlib import Path

import pytest

from src.config import ConfigError, load_config


def test_config_normalizes_and_deduplicates_stocks(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(
        "timezone: Asia/Shanghai\nstocks: [nvda, MU, NVDA]\nmacro:\n  cpi: false\n",
        encoding="utf-8",
    )
    config = load_config(path)
    assert config.stocks == ("NVDA", "MU")
    assert config.macro["cpi"] is False
    assert config.macro["nfp"] is True


def test_config_rejects_unknown_macro_key(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text("macro:\n  magic_number: true\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="unknown macro keys"):
        load_config(path)
