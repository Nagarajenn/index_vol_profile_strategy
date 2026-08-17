import pandas as pd
import pytest

from analytics.breakout_boxes import compute_atr
from quant_features.price_features import compute_price_volatility_features
from quant_features.vwap_features import compute_vwap_features
from tests.fixtures.synthetic_candles import make_candles


def _candles_with_closes(closes: list[float]) -> pd.DataFrame:
    rows = []
    for i, c in enumerate(closes):
        minute = 15 + i
        hh = 9 + minute // 60
        mm = minute % 60
        rows.append({"time": f"{hh:02d}:{mm:02d}", "o": c, "h": c + 1, "l": c - 1, "c": c, "v": 100})
    return make_candles(rows)


def test_ret_1m_and_ret_5m():
    candles = _candles_with_closes([90, 91, 92, 93, 94, 95, 100])
    result = compute_price_volatility_features(candles, prior_day_close=None)
    assert result.ret_1m == pytest.approx((100 - 95) / 95)
    assert result.ret_5m == pytest.approx((100 - 91) / 91)


def test_ret_1m_none_with_single_candle():
    candles = _candles_with_closes([100])
    result = compute_price_volatility_features(candles, prior_day_close=None)
    assert result.ret_1m is None
    assert result.ret_5m is None


def test_ret_5m_none_with_fewer_than_six_candles():
    candles = _candles_with_closes([100, 101, 102, 103, 104])
    result = compute_price_volatility_features(candles, prior_day_close=None)
    assert result.ret_1m is not None
    assert result.ret_5m is None


def test_realized_vol_20m_needs_at_least_five_returns():
    candles = _candles_with_closes([100, 101, 102, 103])  # 3 returns
    result = compute_price_volatility_features(candles, prior_day_close=None)
    assert result.realized_vol_20m is None


def test_realized_vol_20m_computed_when_enough_data():
    closes = [100 + i * (1 if i % 2 == 0 else -1) for i in range(25)]
    candles = _candles_with_closes(closes)
    result = compute_price_volatility_features(candles, prior_day_close=None)
    assert result.realized_vol_20m is not None
    assert result.realized_vol_20m > 0


def test_atr_matches_direct_compute_atr_call():
    closes = [100 + i for i in range(20)]
    candles = _candles_with_closes(closes)
    result = compute_price_volatility_features(candles, prior_day_close=None, atr_period=14)
    expected = compute_atr(candles, period=14).iloc[-1]
    assert result.atr_14 == pytest.approx(float(expected))


def test_gap_open_pct():
    candles = _candles_with_closes([105, 106])
    result = compute_price_volatility_features(candles, prior_day_close=100.0)
    assert result.gap_open_pct == pytest.approx((105 - 100) / 100)


def test_gap_open_pct_none_without_prior_close():
    candles = _candles_with_closes([105])
    result = compute_price_volatility_features(candles, prior_day_close=None)
    assert result.gap_open_pct is None


def test_body_and_wick_ratios():
    rows = [{"time": "09:15", "o": 100, "h": 110, "l": 95, "c": 108, "v": 100}]
    candles = make_candles(rows)
    result = compute_price_volatility_features(candles, prior_day_close=None)
    assert result.body_pct == pytest.approx(8 / 15)
    assert result.upper_wick_pct == pytest.approx(2 / 15)
    assert result.lower_wick_pct == pytest.approx(5 / 15)


def test_body_and_wick_ratios_none_for_degenerate_candle():
    rows = [{"time": "09:15", "o": 100, "h": 100, "l": 100, "c": 100, "v": 100}]
    candles = make_candles(rows)
    result = compute_price_volatility_features(candles, prior_day_close=None)
    assert result.body_pct is None
    assert result.upper_wick_pct is None
    assert result.lower_wick_pct is None


def test_vwap_features_basic():
    vwap_series = pd.Series([100.0, 100.5, 101.0, 101.5, 102.0, 102.5, 103.0])
    result = compute_vwap_features(vwap_series, close=104.0, atr_14=2.0)
    assert result.vwap_now == pytest.approx(103.0)
    assert result.vwap_distance_pct == pytest.approx((104.0 - 103.0) / 103.0)
    assert result.vwap_distance_atr == pytest.approx((104.0 - 103.0) / 2.0)
    assert result.vwap_slope_5m == pytest.approx((103.0 - 100.5) / 100.5)


def test_vwap_features_empty_series():
    result = compute_vwap_features(pd.Series(dtype=float), close=100.0, atr_14=2.0)
    assert result.vwap_now is None
    assert result.vwap_distance_pct is None
    assert result.vwap_distance_atr is None
    assert result.vwap_slope_5m is None


def test_vwap_features_no_atr_leaves_distance_atr_none():
    vwap_series = pd.Series([100.0, 101.0])
    result = compute_vwap_features(vwap_series, close=102.0, atr_14=None)
    assert result.vwap_now == pytest.approx(101.0)
    assert result.vwap_distance_atr is None


def test_vwap_slope_none_when_series_too_short():
    vwap_series = pd.Series([100.0, 101.0])
    result = compute_vwap_features(vwap_series, close=102.0, atr_14=1.0)
    assert result.vwap_slope_5m is None
