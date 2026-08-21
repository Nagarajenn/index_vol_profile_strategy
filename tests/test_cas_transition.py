from datetime import date

import pandas as pd
import pytest

from market_transition.cas_transition import extract_cas_transition_record
from tests.fixtures.synthetic_candles import make_candles

BIN_SIZE = 25.0


def _session(prices: dict[str, float], tz_date: str = "2026-08-10") -> pd.DataFrame:
    rows = [{"time": t, "o": p, "h": p + 1, "l": p - 1, "c": p, "v": 100} for t, p in prices.items()]
    return make_candles(rows, tz_date=tz_date)


def _prewindow_and_postwindow(pre_start=100.0, pre_end=110.0, post_end=120.0, close_time="15:39") -> dict[str, float]:
    return {
        "09:15": pre_start,
        "14:30": pre_start,
        "14:45": (pre_start + pre_end) / 2,
        "14:59": pre_end,
        "15:00": pre_end,
        "15:20": (pre_end + post_end) / 2,
        close_time: post_end,
    }


def test_none_when_no_pre_window_data():
    # Session ends before 14:30 -- no pre-window candles at all.
    candles = _session({"09:15": 100.0, "14:00": 101.0})
    record = extract_cas_transition_record("NIFTY", date(2026, 8, 10), candles, None, {}, BIN_SIZE, None)
    assert record is None


def test_none_when_no_post_window_data():
    # Session ends right at 14:59 -- no post-window candles at all.
    candles = _session({"09:15": 100.0, "14:30": 100.0, "14:59": 105.0})
    record = extract_cas_transition_record("NIFTY", date(2026, 8, 10), candles, None, {}, BIN_SIZE, None)
    assert record is None


def test_continuation_when_both_windows_trend_same_direction():
    prices = _prewindow_and_postwindow(pre_start=100.0, pre_end=110.0, post_end=130.0)
    candles = _session(prices)
    record = extract_cas_transition_record("NIFTY", date(2026, 8, 10), candles, None, {}, BIN_SIZE, None)
    assert record is not None
    assert record.outcome.outcome == "continuation"
    assert record.outcome.transition_direction == "up"


def test_reversal_when_windows_trend_opposite_directions():
    prices = _prewindow_and_postwindow(pre_start=100.0, pre_end=110.0, post_end=90.0)
    candles = _session(prices)
    record = extract_cas_transition_record("NIFTY", date(2026, 8, 10), candles, None, {}, BIN_SIZE, None)
    assert record is not None
    assert record.outcome.outcome == "reversal"


def test_neutral_when_pre_window_trend_is_flat():
    prices = _prewindow_and_postwindow(pre_start=100.0, pre_end=100.005, post_end=130.0)
    candles = _session(prices)
    record = extract_cas_transition_record("NIFTY", date(2026, 8, 10), candles, None, {}, BIN_SIZE, None)
    assert record is not None
    assert record.outcome.outcome == "neutral"


def test_market_close_uses_actual_last_candle_not_a_fixed_time():
    # One session's last candle is 15:39 (new CAS-era close); confirm
    # market_close reflects that actual last price, not a hardcoded 15:30.
    prices = _prewindow_and_postwindow(pre_start=100.0, pre_end=110.0, post_end=155.0, close_time="15:39")
    candles = _session(prices)
    record = extract_cas_transition_record("NIFTY", date(2026, 8, 10), candles, None, {}, BIN_SIZE, None)
    assert record is not None
    assert record.outcome.market_close == pytest.approx(155.0)


def test_close_1459_is_the_pivot_close():
    prices = _prewindow_and_postwindow(pre_start=100.0, pre_end=112.5, post_end=130.0)
    candles = _session(prices)
    record = extract_cas_transition_record("NIFTY", date(2026, 8, 10), candles, None, {}, BIN_SIZE, None)
    assert record is not None
    assert record.outcome.close_1459 == pytest.approx(112.5)
