from datetime import date

from market_transition.cas_windows import PreTransitionWindow
from market_transition.transition_state import build_market_state_vector


def _window(**overrides) -> PreTransitionWindow:
    defaults = dict(
        window_index=6, window_label="14:55-14:59", open=100.0, close=100.0, high=100.5, low=99.5,
        net_point_change=0.0, pct_change=0.0, volume=1000.0, rvol_pct=100.0, volume_acceleration_ratio=1.0,
        buy_volume_estimate=500.0, sell_volume_estimate=500.0, dominance_ratio=0.5, dominant_side="balanced",
        vwap_at_window_end=100.0, price_distance_from_vwap=0.0, price_distance_from_vwap_pct=0.0, vwap_slope=0.0,
        poc_at_window_end=100.0, poc_change_during_window=0.0, poc_slope=0.0, vah=101.0, val=99.0,
        pcr=1.0, pcr_change=0.0, call_oi_change=0.0, put_oi_change=0.0, iv_change=0.0, option_pressure_score=0.0,
        market_regime="Trending", institutional_bias_label="Neutral", institutional_bias_score=0, news_risk_score=None,
    )
    defaults.update(overrides)
    return PreTransitionWindow(**defaults)


def test_bearish_price_from_negative_pct_change():
    vector = build_market_state_vector(_window(pct_change=-0.5))
    assert vector.price_bias == "bearish"


def test_bullish_price_from_positive_pct_change():
    vector = build_market_state_vector(_window(pct_change=0.5))
    assert vector.price_bias == "bullish"


def test_flat_price_within_threshold():
    vector = build_market_state_vector(_window(pct_change=0.01))
    assert vector.price_bias == "flat"


def test_volume_bias_reads_dominant_side():
    assert build_market_state_vector(_window(dominant_side="sell")).volume_bias == "Increasing sell pressure"
    assert build_market_state_vector(_window(dominant_side="buy")).volume_bias == "Increasing buy pressure"


def test_vwap_position_reads_distance_sign():
    assert build_market_state_vector(_window(price_distance_from_vwap=5.0)).vwap_position == "Above VWAP"
    assert build_market_state_vector(_window(price_distance_from_vwap=-5.0)).vwap_position == "Below VWAP"


def test_poc_migration_reads_slope():
    assert build_market_state_vector(_window(poc_slope=-2.0)).poc_migration == "Migrating lower"
    assert build_market_state_vector(_window(poc_slope=2.0)).poc_migration == "Migrating higher"


def test_profile_acceptance_above_and_below_value_area():
    assert build_market_state_vector(_window(close=102.0, vah=101.0, val=99.0)).profile_acceptance == "Acceptance above VAH"
    assert build_market_state_vector(_window(close=98.0, vah=101.0, val=99.0)).profile_acceptance == "Acceptance below VAL"
    assert build_market_state_vector(_window(close=100.0, vah=101.0, val=99.0)).profile_acceptance == "Within value area"


def test_oi_structure_reads_which_side_is_building():
    assert build_market_state_vector(_window(call_oi_change=500.0, put_oi_change=100.0)).oi_structure == "Call-side concentration increasing"
    assert build_market_state_vector(_window(call_oi_change=100.0, put_oi_change=500.0)).oi_structure == "Put-side concentration increasing"


def test_contradiction_flagged_when_bearish_price_meets_rising_put_oi():
    vector = build_market_state_vector(_window(pct_change=-0.5, call_oi_change=100.0, put_oi_change=500.0))
    assert vector.price_bias == "bearish"
    assert vector.oi_structure == "Put-side concentration increasing"
    assert any("Put OI" in c for c in vector.contradictions)


def test_no_contradiction_when_bearish_price_meets_rising_call_oi():
    # Consistent evidence -- call-side building while price falls (matches
    # the spec's own non-contradictory example) should NOT be flagged.
    vector = build_market_state_vector(_window(pct_change=-0.5, call_oi_change=500.0, put_oi_change=100.0))
    assert vector.contradictions == []


def test_contradiction_flagged_when_price_and_option_bias_disagree():
    vector = build_market_state_vector(_window(pct_change=-0.5, call_oi_change=100.0, put_oi_change=100.0), option_bias="BULLISH")
    assert any("bullish option positioning" in c for c in vector.contradictions)


def test_option_bias_defaults_to_na_when_not_supplied():
    vector = build_market_state_vector(_window())
    assert vector.option_bias == "N/A"


def test_news_bias_labels_by_score():
    assert build_market_state_vector(_window(news_risk_score=None)).news_bias == "Neutral"
    assert build_market_state_vector(_window(news_risk_score=10)).news_bias == "Neutral"
    assert build_market_state_vector(_window(news_risk_score=40)).news_bias == "Mild risk"
    assert build_market_state_vector(_window(news_risk_score=80)).news_bias == "Elevated risk"


def test_unknown_when_underlying_fields_are_none():
    vector = build_market_state_vector(_window(pct_change=None, price_distance_from_vwap=None, poc_slope=None, poc_change_during_window=None, pcr_change=None, call_oi_change=None, put_oi_change=None, iv_change=None))
    assert vector.price_bias == "Unknown"
    assert vector.vwap_position == "Unknown"
    assert vector.poc_migration == "Unknown"
    assert vector.pcr_trend == "Unknown"
    assert vector.oi_structure == "Unknown"
    assert vector.iv_trend == "Unknown"
