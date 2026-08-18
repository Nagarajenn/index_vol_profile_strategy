import pandas as pd
import pytest

from quant_features.labeling import _forward_window, compute_forward_outcome_row
from tests.fixtures.synthetic_candles import make_candles


def _minute_time(i: int) -> str:
    minute = 15 + i
    hh = 9 + minute // 60
    mm = minute % 60
    return f"{hh:02d}:{mm:02d}"


def _session(closes: list[float], date: str = "2026-07-01") -> pd.DataFrame:
    rows = []
    for i, c in enumerate(closes):
        rows.append({"time": _minute_time(i), "date": date, "o": c, "h": c + 0.5, "l": c - 0.5, "c": c, "v": 100})
    return make_candles(rows)


def test_forward_window_excludes_entry_index_itself():
    # Entry candle (t_index) has an extreme price -- it must never appear
    # in its own forward window. horizon=3 exactly matches the 3 remaining
    # future rows, so the horizon is genuinely reached.
    candles = _session([100, 101, 999, 103, 104, 105])
    window = _forward_window(candles, t_index=2, horizon_minutes=3)
    assert 999 not in window["close"].values
    assert list(window["close"]) == [103, 104, 105]


def test_forward_window_empty_when_horizon_not_reached():
    candles = _session([100, 101, 999, 103, 104, 105])
    window = _forward_window(candles, t_index=2, horizon_minutes=30)
    assert window.empty


def test_fwd_return_values_correct():
    candles = _session([100, 101, 102, 103, 104, 106])
    result = compute_forward_outcome_row("NIFTY", candles["timestamp"].iloc[0], "v1", candles, t_index=0, atr_at_t=1.0)
    assert result.fwd_return_1m == pytest.approx((101 - 100) / 100)
    assert result.fwd_return_5m == pytest.approx((106 - 100) / 100)


def test_mfe_mae_values_correct():
    # High/low deliberately wider than close so mfe/mae differ from fwd_return.
    rows = [
        {"time": _minute_time(0), "date": "2026-07-01", "o": 100, "h": 100.5, "l": 99.5, "c": 100, "v": 100},
        {"time": _minute_time(1), "date": "2026-07-01", "o": 100, "h": 108, "l": 95, "c": 101, "v": 100},
        {"time": _minute_time(2), "date": "2026-07-01", "o": 100, "h": 103, "l": 98, "c": 102, "v": 100},
    ]
    candles = make_candles(rows)
    result = compute_forward_outcome_row("NIFTY", candles["timestamp"].iloc[0], "v1", candles, t_index=0, atr_at_t=1.0)
    # 1m horizon window = row index 1 only: high=108, low=95
    assert result.mfe_1m == pytest.approx((108 - 100) / 100)
    assert result.mae_1m == pytest.approx((95 - 100) / 100)


def test_label_up_down_flat_thresholds():
    # atr_at_t = 2.0, LABEL_ATR_THRESHOLD = 0.5 -> +/-1.0 price move needed.
    up = _session([100, 100, 100, 100, 100, 101.5])  # move of +1.5 by minute 5
    down = _session([100, 100, 100, 100, 100, 98.5])  # move of -1.5
    flat = _session([100, 100, 100, 100, 100, 100.2])  # move of +0.2, under threshold

    up_result = compute_forward_outcome_row("NIFTY", up["timestamp"].iloc[0], "v1", up, t_index=0, atr_at_t=2.0)
    down_result = compute_forward_outcome_row("NIFTY", down["timestamp"].iloc[0], "v1", down, t_index=0, atr_at_t=2.0)
    flat_result = compute_forward_outcome_row("NIFTY", flat["timestamp"].iloc[0], "v1", flat, t_index=0, atr_at_t=2.0)

    assert up_result.label_5m == "Up"
    assert down_result.label_5m == "Down"
    assert flat_result.label_5m == "Flat"


def test_label_none_without_atr():
    candles = _session([100, 100, 100, 100, 100, 110])
    result = compute_forward_outcome_row("NIFTY", candles["timestamp"].iloc[0], "v1", candles, t_index=0, atr_at_t=None)
    assert result.label_5m is None
    assert result.label_15m is None
    assert result.label_30m is None


def test_truncated_flag_true_when_session_ends_before_longest_horizon():
    candles = _session([100, 101, 102])  # only 2 minutes of future data -- far short of 30m
    result = compute_forward_outcome_row("NIFTY", candles["timestamp"].iloc[0], "v1", candles, t_index=0, atr_at_t=1.0)
    assert result.horizon_truncated_by_session_close is True
    assert result.fwd_return_1m is not None
    assert result.fwd_return_30m is None


def test_truncated_flag_false_with_a_full_trading_day():
    closes = [100 + i * 0.01 for i in range(400)]  # ~6.5 hours of 1-min candles
    candles = _session(closes)
    t_index = 10  # plenty of room for every horizon up to 30m
    result = compute_forward_outcome_row("NIFTY", candles["timestamp"].iloc[t_index], "v1", candles, t_index=t_index, atr_at_t=1.0)
    assert result.horizon_truncated_by_session_close is False
    assert result.fwd_return_30m is not None


def test_never_crosses_into_next_day_even_if_present_in_input():
    day1 = _session([100, 101, 102], date="2026-07-01")
    day2 = _session([500, 501, 502], date="2026-07-02")  # deliberately extreme, must never leak in
    combined = pd.concat([day1, day2], ignore_index=True)

    t_index = 2  # last candle of day1
    result = compute_forward_outcome_row("NIFTY", combined["timestamp"].iloc[t_index], "v1", combined, t_index=t_index, atr_at_t=1.0)

    assert result.fwd_return_1m is None
    assert result.fwd_return_30m is None
    assert result.horizon_truncated_by_session_close is True
