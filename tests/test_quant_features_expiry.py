from datetime import date, timedelta

import pytest

from market_transition.expiry_calendar import build_expiry_calendar, classify_expiry_day
from quant_features.expiry_features import compute_expiry_feature_set
from tests.fixtures.synthetic_candles import flat_candle, make_candles


def _candles_for(session_date: date, n_minutes: int):
    rows = [flat_candle(f"09:{15+i:02d}", 100.0, 500, date=session_date.isoformat()) for i in range(n_minutes)]
    return make_candles(rows)


def test_expiry_type_matches_direct_classify_expiry_day():
    session_date = date(2026, 7, 1)
    calendar = build_expiry_calendar("NIFTY", session_date, session_date + timedelta(days=35))
    candles = _candles_for(session_date, 10)
    result = compute_expiry_feature_set("NIFTY", session_date, candles, calendar)
    assert result.expiry_type == classify_expiry_day("NIFTY", session_date, calendar)
    assert result.is_expiry_day == (result.expiry_type is not None)


def test_days_to_weekly_expiry_zero_on_expiry_day():
    calendar = build_expiry_calendar("NIFTY", date(2026, 7, 1), date(2026, 8, 5))
    weekly_dates = sorted(calendar)
    assert weekly_dates, "expected at least one NIFTY expiry date in range"
    expiry_date = weekly_dates[0]
    candles = _candles_for(expiry_date, 5)
    result = compute_expiry_feature_set("NIFTY", expiry_date, candles, calendar)
    assert result.days_to_weekly_expiry == 0
    assert result.is_expiry_day is True


def test_days_to_monthly_expiry_matches_nearest_monthly_entry():
    calendar = build_expiry_calendar("NIFTY", date(2026, 7, 1), date(2026, 9, 1))
    monthly_dates = sorted(d for d, t in calendar.items() if t == "monthly")
    assert monthly_dates, "expected at least one monthly expiry in range"

    start = date(2026, 7, 1)
    next_monthly = next(d for d in monthly_dates if d >= start)
    candles = _candles_for(start, 5)
    result = compute_expiry_feature_set("NIFTY", start, candles, calendar)
    assert result.days_to_monthly_expiry == (next_monthly - start).days


def test_day_of_week_and_minutes_since_open():
    session_date = date(2026, 7, 6)  # a Monday
    candles = _candles_for(session_date, 45)
    calendar = build_expiry_calendar("NIFTY", session_date, session_date + timedelta(days=35))
    result = compute_expiry_feature_set("NIFTY", session_date, candles, calendar)
    assert result.day_of_week == 0
    assert result.minutes_since_open == 44


def test_minutes_since_open_zero_on_empty_candles():
    session_date = date(2026, 7, 6)
    empty = make_candles([])
    calendar = build_expiry_calendar("NIFTY", session_date, session_date + timedelta(days=35))
    result = compute_expiry_feature_set("NIFTY", session_date, empty, calendar)
    assert result.minutes_since_open == 0


def test_builds_own_calendar_when_none_supplied():
    session_date = date(2026, 7, 1)
    candles = _candles_for(session_date, 5)
    result = compute_expiry_feature_set("NIFTY", session_date, candles, expiry_calendar=None)
    assert result.expiry_type == classify_expiry_day("NIFTY", session_date)
