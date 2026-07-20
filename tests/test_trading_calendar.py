import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.trading_calendar import is_trading_day, trading_days_between


def test_weekends_are_not_trading_days():
    assert is_trading_day(date(2026, 7, 18)) is False  # Saturday
    assert is_trading_day(date(2026, 7, 19)) is False  # Sunday


def test_ordinary_weekday_is_a_trading_day():
    assert is_trading_day(date(2026, 7, 17)) is True  # Friday


def test_known_holiday_is_not_a_trading_day():
    assert is_trading_day(date(2026, 1, 26)) is False  # Republic Day (Monday)


def test_trading_days_between_excludes_weekend_and_holiday():
    days = trading_days_between(date(2026, 1, 23), date(2026, 1, 27))
    # Fri 23rd (trading), Sat/Sun off, Mon 26th Republic Day off, Tue 27th trading
    assert days == [date(2026, 1, 23), date(2026, 1, 27)]
