import sys
from datetime import date
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from market_transition.feature_extraction import extract_daily_transition_record
from tests.fixtures.synthetic_candles import make_candles


def _full_session(tz_date: str, close_1459: float, close_1501: float, market_close: float) -> pd.DataFrame:
    """A full 09:15-15:29 session where every minute outside the windows
    we care about just drifts gently, and the pre/transition/post windows
    are pinned to the given closes so outcome classification is testable."""
    rows: list[dict] = []
    price = 100.0
    for t in pd.date_range("2026-01-01 09:15", "2026-01-01 13:59", freq="1min"):
        price += 0.01
        rows.append({"time": t.strftime("%H:%M"), "o": price, "h": price + 0.5, "l": price - 0.5, "c": price, "v": 100})

    # Pre-window 14:00-14:59, ramping toward close_1459.
    pre_start_price = price
    for i, t in enumerate(pd.date_range("2026-01-01 14:00", "2026-01-01 14:59", freq="1min")):
        frac = i / 59
        p = pre_start_price + (close_1459 - pre_start_price) * frac
        rows.append({"time": t.strftime("%H:%M"), "o": p, "h": p + 0.5, "l": p - 0.5, "c": p, "v": 100})
    rows[-1]["c"] = close_1459
    rows[-1]["h"] = max(rows[-1]["h"], close_1459)
    rows[-1]["l"] = min(rows[-1]["l"], close_1459)

    # Transition window 15:00-15:01.
    rows.append({"time": "15:00", "o": close_1459, "h": max(close_1459, close_1501), "l": min(close_1459, close_1501), "c": (close_1459 + close_1501) / 2, "v": 200})
    rows.append({"time": "15:01", "o": (close_1459 + close_1501) / 2, "h": max(close_1459, close_1501), "l": min(close_1459, close_1501), "c": close_1501, "v": 200})

    # Post window 15:02-15:29, ramping toward market_close.
    for i, t in enumerate(pd.date_range("2026-01-01 15:02", "2026-01-01 15:29", freq="1min")):
        frac = i / 27
        p = close_1501 + (market_close - close_1501) * frac
        rows.append({"time": t.strftime("%H:%M"), "o": p, "h": p + 0.5, "l": p - 0.5, "c": p, "v": 100})
    rows[-1]["c"] = market_close

    return make_candles(rows, tz_date=tz_date)


def test_continuation_case():
    today = _full_session("2026-07-10", close_1459=150.0, close_1501=155.0, market_close=165.0)
    record = extract_daily_transition_record(
        symbol="NIFTY",
        session_date=date(2026, 7, 10),
        today_candles=today,
        prior_day_candles=None,
        historical_by_date={},
        bin_size=1.0,
        expiry_type=None,
    )
    assert record is not None
    assert record.outcome.transition_direction == "up"
    assert record.outcome.outcome == "continuation"
    assert record.outcome.transition_move == 5.0
    assert record.outcome.post_transition_move == 10.0
    assert record.features.day_of_week == date(2026, 7, 10).weekday()


def test_reversal_case():
    today = _full_session("2026-07-10", close_1459=150.0, close_1501=155.0, market_close=148.0)
    record = extract_daily_transition_record(
        symbol="NIFTY",
        session_date=date(2026, 7, 10),
        today_candles=today,
        prior_day_candles=None,
        historical_by_date={},
        bin_size=1.0,
        expiry_type=None,
    )
    assert record is not None
    assert record.outcome.transition_direction == "up"
    assert record.outcome.outcome == "reversal"


def test_flat_transition_is_neutral():
    today = _full_session("2026-07-10", close_1459=150.0, close_1501=150.005, market_close=160.0)
    record = extract_daily_transition_record(
        symbol="NIFTY",
        session_date=date(2026, 7, 10),
        today_candles=today,
        prior_day_candles=None,
        historical_by_date={},
        bin_size=1.0,
        expiry_type=None,
    )
    assert record is not None
    assert record.outcome.transition_direction == "flat"
    assert record.outcome.outcome == "neutral"


def test_incomplete_day_missing_transition_window_returns_none():
    rows = [{"time": t.strftime("%H:%M"), "o": 100, "h": 101, "l": 99, "c": 100, "v": 10} for t in pd.date_range("2026-01-01 09:15", "2026-01-01 14:59", freq="1min")]
    today = make_candles(rows, tz_date="2026-07-10")
    record = extract_daily_transition_record(
        symbol="NIFTY",
        session_date=date(2026, 7, 10),
        today_candles=today,
        prior_day_candles=None,
        historical_by_date={},
        bin_size=1.0,
        expiry_type=None,
    )
    assert record is None


def test_empty_day_returns_none():
    record = extract_daily_transition_record(
        symbol="NIFTY",
        session_date=date(2026, 7, 10),
        today_candles=make_candles([]),
        prior_day_candles=None,
        historical_by_date={},
        bin_size=1.0,
        expiry_type=None,
    )
    assert record is None


def test_expiry_type_passed_through():
    today = _full_session("2026-07-10", close_1459=150.0, close_1501=155.0, market_close=165.0)
    record = extract_daily_transition_record(
        symbol="NIFTY",
        session_date=date(2026, 7, 10),
        today_candles=today,
        prior_day_candles=None,
        historical_by_date={},
        bin_size=1.0,
        expiry_type="weekly",
    )
    assert record is not None
    assert record.features.expiry_type == "weekly"


def test_prior_day_features_populated_when_prior_day_given():
    today = _full_session("2026-07-10", close_1459=150.0, close_1501=155.0, market_close=165.0)
    prior_rows = [{"time": t.strftime("%H:%M"), "o": 90, "h": 92, "l": 88, "c": 91, "v": 50} for t in pd.date_range("2026-01-01 09:15", "2026-01-01 15:29", freq="1min")]
    prior_day = make_candles(prior_rows, tz_date="2026-07-09")

    record = extract_daily_transition_record(
        symbol="NIFTY",
        session_date=date(2026, 7, 10),
        today_candles=today,
        prior_day_candles=prior_day,
        historical_by_date={},
        bin_size=1.0,
        expiry_type=None,
    )
    assert record is not None
    assert record.features.prior_day_profile_shape is not None
    assert record.features.prior_day_close_vs_poc is not None
