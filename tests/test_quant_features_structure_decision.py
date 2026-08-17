from datetime import datetime

import pandas as pd
import pytest

from analytics.breakout_boxes import BreakoutBox
from analytics.confidence_score import ConfidenceResult
from analytics.levels import LevelsResult
from analytics.support_resistance import Zone
from analytics.trend_classifier import TrendResult
from analytics.trendlines import Trendline
from quant_features.decision_features import compute_decision_feature_set
from quant_features.structure_features import compute_structure_feature_set


def _bare_levels(**overrides) -> LevelsResult:
    defaults = dict(
        symbol="NIFTY",
        as_of=datetime(2026, 7, 1, 10, 0),
        close=100.0,
        vwap_now=99.5,
        candles_5min=pd.DataFrame(),
        vwap_5min=pd.Series(dtype=float),
        today_vp=None,
        yesterday_vp=None,
        swings=[],
        trendlines=[],
        support=None,
        resistance=None,
        breakout_boxes=[],
        trend=None,
        institutional_bias=None,
        confidence=None,
    )
    defaults.update(overrides)
    return LevelsResult(**defaults)


def test_structure_feature_set_all_none_when_nothing_computed():
    levels = _bare_levels()
    result = compute_structure_feature_set(levels)
    assert result.support_low is None
    assert result.resistance_low is None
    assert result.support_distance_pct is None
    assert result.resistance_distance_pct is None
    assert result.nearest_trendline_touch_count is None
    assert result.breakout_box_status is None
    assert result.swing_structure_score is None


def test_structure_feature_set_extracts_support_resistance_and_distance():
    levels = _bare_levels(
        close=100.0,
        support=Zone(low=95.0, high=98.0, strength=2),
        resistance=Zone(low=103.0, high=106.0, strength=1),
    )
    result = compute_structure_feature_set(levels)
    assert result.support_low == 95.0
    assert result.support_high == 98.0
    assert result.resistance_low == 103.0
    assert result.resistance_high == 106.0
    assert result.support_distance_pct == pytest.approx(abs(100.0 - 98.0) / 100.0)
    assert result.resistance_distance_pct == pytest.approx(abs(103.0 - 100.0) / 100.0)


def test_structure_feature_set_picks_highest_touch_count_trendline():
    tl_weak = Trendline(points=[(0, 90), (10, 95)], direction="up", r2=0.8, touch_count=2)
    tl_strong = Trendline(points=[(0, 110), (10, 100)], direction="down", r2=0.9, touch_count=5)
    levels = _bare_levels(trendlines=[tl_weak, tl_strong])
    result = compute_structure_feature_set(levels)
    assert result.nearest_trendline_touch_count == 5
    assert result.nearest_trendline_direction == "down"


def test_structure_feature_set_breakout_box_status_uses_most_recent():
    boxes = [
        BreakoutBox(t_start=pd.Timestamp("2026-07-01 09:15"), t_end=pd.Timestamp("2026-07-01 10:00"), p_low=90, p_high=95, status="confirmed_up", avg_volume=1000),
        BreakoutBox(t_start=pd.Timestamp("2026-07-01 10:05"), t_end=pd.Timestamp("2026-07-01 10:30"), p_low=95, p_high=98, status="forming", avg_volume=1200),
    ]
    levels = _bare_levels(breakout_boxes=boxes)
    result = compute_structure_feature_set(levels)
    assert result.breakout_box_status == "forming"


def test_structure_feature_set_swing_structure_score_from_trend():
    trend = TrendResult(label="Bullish", score=2, price_vs_vwap=1, ema_slope=1, structure=1)
    levels = _bare_levels(trend=trend)
    result = compute_structure_feature_set(levels)
    assert result.swing_structure_score == 1


def test_decision_feature_set_all_none_when_nothing_computed():
    levels = _bare_levels()
    result = compute_decision_feature_set(levels)
    assert result.trend_label is None
    assert result.confidence_score is None
    assert result.sub_score_trend_alignment is None
    assert result.confidence_partial_data is None


def test_decision_feature_set_extracts_trend_and_confidence():
    trend = TrendResult(label="Bullish", score=2, price_vs_vwap=1, ema_slope=1, structure=0)
    confidence = ConfidenceResult(
        score=72,
        sub_scores={"trend_alignment": 0.67, "vwap_position": 1.0, "sr_proximity": 0.5},
        weights_used={"trend_alignment": 0.3, "vwap_position": 0.4, "sr_proximity": 0.3},
        partial_data=True,
    )
    levels = _bare_levels(trend=trend, confidence=confidence)
    result = compute_decision_feature_set(levels)
    assert result.trend_label == "Bullish"
    assert result.trend_score == 2
    assert result.confidence_score == 72
    assert result.sub_score_trend_alignment == pytest.approx(0.67)
    assert result.sub_score_vwap_position == pytest.approx(1.0)
    assert result.sub_score_sr_proximity == pytest.approx(0.5)
    assert result.sub_score_structure_hh_hl is None  # not present in sub_scores -> stays None, not 0
    assert result.confidence_partial_data is True
