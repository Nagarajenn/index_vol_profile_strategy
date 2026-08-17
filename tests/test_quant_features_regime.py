import pandas as pd
import pytest

from analytics.trend_classifier import TrendResult
from analytics.volume_profile_intelligence import RotationFactor
from market_transition.market_regime import classify_market_regime
from quant_features.regime_features import classify_expanded_regime, compute_regime_feature_set
from tests.fixtures.synthetic_candles import flat_candle, make_candles


def _trending_rotation():
    return RotationFactor(value=0, periods=4, label="Trending")


def _rotational_rotation():
    return RotationFactor(value=3, periods=4, label="Rotational")


def test_high_volatility_choppy():
    result = classify_expanded_regime("Volatile", 130.0, _rotational_rotation(), TrendResult("Neutral", 0, 0, 0, 0))
    assert result == "High-Volatility Choppy"


def test_low_volatility_quiet():
    result = classify_expanded_regime("Range-Bound", 70.0, _trending_rotation(), None)
    assert result == "Low-Volatility Quiet"


def test_breakout_up_and_down():
    up = classify_expanded_regime("Volatile", 120.0, _trending_rotation(), TrendResult("Bullish", 2, 1, 1, 0))
    down = classify_expanded_regime("Volatile", 120.0, _trending_rotation(), TrendResult("Bearish", -2, -1, -1, 0))
    assert up == "Breakout-Up"
    assert down == "Breakout-Down"


def test_reversal_up_and_down():
    # trend score negative (still bearish overall) but structure just turned positive -> Reversal-Up
    up = classify_expanded_regime("Trending", 100.0, _trending_rotation(), TrendResult("Bearish", -1, -1, 0, 1))
    down = classify_expanded_regime("Trending", 100.0, _trending_rotation(), TrendResult("Bullish", 1, 1, 0, -1))
    assert up == "Reversal-Up"
    assert down == "Reversal-Down"


def test_strong_and_weak_uptrend_downtrend():
    strong_up = classify_expanded_regime("Trending", 100.0, _trending_rotation(), TrendResult("Strong Bullish", 3, 1, 1, 1))
    strong_down = classify_expanded_regime("Trending", 100.0, _trending_rotation(), TrendResult("Strong Bearish", -3, -1, -1, -1))
    uptrend = classify_expanded_regime("Trending", 100.0, _trending_rotation(), TrendResult("Bullish", 1, 1, 0, 0))
    weak_uptrend = classify_expanded_regime("Trending", 100.0, _rotational_rotation(), TrendResult("Bullish", 1, 1, 0, 0))
    downtrend = classify_expanded_regime("Trending", 100.0, _trending_rotation(), TrendResult("Bearish", -1, -1, 0, 0))
    weak_downtrend = classify_expanded_regime("Trending", 100.0, _rotational_rotation(), TrendResult("Bearish", -1, -1, 0, 0))
    assert strong_up == "Strong Uptrend"
    assert strong_down == "Strong Downtrend"
    assert uptrend == "Uptrend"
    assert weak_uptrend == "Weak Uptrend"
    assert downtrend == "Downtrend"
    assert weak_downtrend == "Weak Downtrend"


def test_range_bound_default():
    result = classify_expanded_regime("Range-Bound", 100.0, _trending_rotation(), TrendResult("Neutral", 0, 0, 0, 0))
    assert result == "Range-Bound"


def test_compute_regime_feature_set_none_on_empty_candles():
    empty = make_candles([])
    result = compute_regime_feature_set(empty, {}, trend=None)
    assert result.market_regime_3way is None
    assert result.market_regime_expanded is None
    assert result.volatility_pace_pct is None


def test_compute_regime_feature_set_matches_direct_classify_call():
    today_rows = [flat_candle(f"09:{15+i:02d}", 100.0 + i * 0.3, 500) for i in range(20)]
    today = make_candles(today_rows)
    hist_rows = [flat_candle(f"09:{15+i:02d}", 100.0, 500, date="2026-06-30") for i in range(20)]
    historical = {pd.Timestamp("2026-06-30").date(): make_candles(hist_rows)}

    result = compute_regime_feature_set(today, historical, trend=None)
    direct = classify_market_regime(today, historical)
    assert result.market_regime_3way == direct
    assert result.market_regime_expanded is not None
