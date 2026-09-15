from datetime import date

from src.utils.timezone import eastern_datetime


def test_dst_conversion_uses_real_new_york_offset() -> None:
    winter = eastern_datetime(date(2026, 1, 14), 8, 30)
    summer = eastern_datetime(date(2026, 7, 14), 8, 30)
    assert winter.utcoffset().total_seconds() == -5 * 3600
    assert summer.utcoffset().total_seconds() == -4 * 3600
    assert winter.astimezone().tzinfo is not None
