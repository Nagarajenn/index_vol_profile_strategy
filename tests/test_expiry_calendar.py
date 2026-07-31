import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from market_transition.expiry_calendar import build_expiry_calendar, classify_expiry_day


def test_nifty_weekly_expiry_is_tuesday():
    cal = build_expiry_calendar("NIFTY", date(2026, 7, 1), date(2026, 7, 31))
    assert cal[date(2026, 7, 7)] == "weekly"
    assert cal[date(2026, 7, 14)] == "weekly"
    assert cal[date(2026, 7, 21)] == "weekly"


def test_sensex_weekly_expiry_is_thursday():
    cal = build_expiry_calendar("SENSEX", date(2026, 7, 1), date(2026, 7, 31))
    assert cal[date(2026, 7, 2)] == "weekly"
    assert cal[date(2026, 7, 9)] == "weekly"
    assert cal[date(2026, 7, 16)] == "weekly"


def test_last_tuesday_of_month_is_monthly_for_nifty():
    cal = build_expiry_calendar("NIFTY", date(2026, 4, 1), date(2026, 4, 30))
    # April 2026 Tuesdays: 7, 14, 21, 28 -- the last one is monthly.
    assert cal[date(2026, 4, 28)] == "monthly"
    assert cal.get(date(2026, 4, 21)) == "weekly"


def test_holiday_on_expiry_weekday_shifts_to_previous_trading_day():
    # 2026-04-14 (Tue) is a trading holiday -> NIFTY weekly expiry moves to
    # the previous trading day, 2026-04-13 (Mon).
    cal = build_expiry_calendar("NIFTY", date(2026, 4, 1), date(2026, 4, 30))
    assert date(2026, 4, 14) not in cal
    assert cal[date(2026, 4, 13)] == "weekly"

    # 2026-05-28 (Thu) is both the last Thursday of May (monthly expiry) and
    # a trading holiday -> SENSEX monthly expiry moves to 2026-05-27 (Wed),
    # still classified "monthly".
    cal2 = build_expiry_calendar("SENSEX", date(2026, 5, 1), date(2026, 5, 31))
    assert date(2026, 5, 28) not in cal2
    assert cal2[date(2026, 5, 27)] == "monthly"

    # 2026-01-15 (Thu) is a holiday but NOT the last Thursday of January
    # (that's Jan 29) -> a genuine weekly-expiry holiday shift, to 2026-01-14.
    cal3 = build_expiry_calendar("SENSEX", date(2026, 1, 1), date(2026, 1, 31))
    assert date(2026, 1, 15) not in cal3
    assert cal3[date(2026, 1, 14)] == "weekly"
    assert cal3[date(2026, 1, 29)] == "monthly"


def test_classify_expiry_day_returns_none_for_non_expiry_date():
    cal = build_expiry_calendar("NIFTY", date(2026, 7, 1), date(2026, 7, 31))
    assert classify_expiry_day("NIFTY", date(2026, 7, 8), calendar=cal) is None


def test_classify_expiry_day_builds_calendar_on_demand():
    assert classify_expiry_day("NIFTY", date(2026, 7, 7)) == "weekly"
