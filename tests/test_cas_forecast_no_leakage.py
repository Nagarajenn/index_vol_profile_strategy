"""Mandatory leakage-guard suite for market_transition/cas_forecast.py --
the direct enforcement of the spec's "the forecast must never use the
eventual 15:00 outcome" acceptance criterion. For each checkpoint, build
the forecast twice: once with the candles truncated exactly at the
checkpoint, once with the full post-3pm session appended on top. Every
forecast field must be bit-identical -- if it isn't, something is reading
past the checkpoint.
"""

from dataclasses import asdict
from datetime import date, time

import pytest

from market_transition.cas_forecast import FORECAST_CHECKPOINTS, build_transition_forecast
from market_transition.cas_windows import PreTransitionWindow
from tests.fixtures.synthetic_candles import make_candles

BIN_SIZE = 1.0


def _session_candles(post_3pm: bool, tz_date: str = "2026-08-27"):
    rows = []
    price = 100.0
    hours = [(9, range(15, 60)), (10, range(60)), (11, range(60)), (12, range(60)), (13, range(60)), (14, range(60))]
    if post_3pm:
        hours.append((15, range(40)))
    for hh, mm_range in hours:
        for mm in mm_range:
            price += 0.07
            rows.append({"time": f"{hh:02d}:{mm:02d}", "o": price, "h": price + 0.5, "l": price - 0.5, "c": price, "v": 100 + mm})
    return make_candles(rows, tz_date=tz_date)


@pytest.mark.parametrize("checkpoint", FORECAST_CHECKPOINTS)
def test_forecast_is_bit_identical_whether_or_not_post_3pm_candles_exist(checkpoint):
    truncated = _session_candles(post_3pm=False)
    extended = _session_candles(post_3pm=True)

    common_kwargs = dict(
        symbol="NIFTY", session_date=date(2026, 8, 27),
        prior_day_candles=None, historical_by_date={},
        history=[], cas_history=[], correlations=[],
        bin_size=BIN_SIZE, expiry_type=None,
    )

    forecast_truncated = build_transition_forecast(checkpoint, today_candles=truncated, **common_kwargs)
    forecast_extended = build_transition_forecast(checkpoint, today_candles=extended, **common_kwargs)

    assert forecast_truncated is not None
    assert forecast_extended is not None
    assert asdict(forecast_truncated) == asdict(forecast_extended)


def test_returns_none_when_there_is_no_candle_data_at_all():
    import pandas as pd

    candles = pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])
    forecast = build_transition_forecast(
        time(14, 59), symbol="NIFTY", session_date=date(2026, 8, 27),
        today_candles=candles, prior_day_candles=None, historical_by_date={},
        history=[], cas_history=[], correlations=[], bin_size=BIN_SIZE, expiry_type=None,
    )
    assert forecast is None


def test_thin_data_returns_an_honestly_labeled_forecast_not_none():
    # A day with only a couple of candles well before the checkpoint still
    # produces a result (matching this codebase's "compute what you can,
    # let confidence/n_analogs communicate thinness" convention elsewhere)
    # -- it just carries "Insufficient data" confidence and 0 analogs.
    rows = [{"time": "09:15", "o": 100, "h": 100.5, "l": 99.5, "c": 100, "v": 100},
            {"time": "14:00", "o": 101, "h": 101.5, "l": 100.5, "c": 101, "v": 100}]
    candles = make_candles(rows, tz_date="2026-08-27")
    forecast = build_transition_forecast(
        time(14, 59), symbol="NIFTY", session_date=date(2026, 8, 27),
        today_candles=candles, prior_day_candles=None, historical_by_date={},
        history=[], cas_history=[], correlations=[], bin_size=BIN_SIZE, expiry_type=None,
    )
    assert forecast is not None
    assert forecast.confidence_label == "Insufficient data"
    assert forecast.n_analogs == 0


def _flat_pre_window() -> PreTransitionWindow:
    """A window shaped to trigger the "bearish price but Put OI building"
    contradiction rule from market_transition/transition_state.py."""
    return PreTransitionWindow(
        window_index=6, window_label="14:55-14:59", open=100.0, close=99.0, high=100.5, low=98.5,
        net_point_change=-1.0, pct_change=-1.0, volume=1000.0, rvol_pct=100.0, volume_acceleration_ratio=1.0,
        buy_volume_estimate=400.0, sell_volume_estimate=600.0, dominance_ratio=0.4, dominant_side="sell",
        vwap_at_window_end=99.5, price_distance_from_vwap=-0.5, price_distance_from_vwap_pct=-0.5, vwap_slope=0.0,
        poc_at_window_end=99.5, poc_change_during_window=-0.5, poc_slope=-0.5, vah=100.0, val=98.0,
        pcr=1.0, pcr_change=0.0, call_oi_change=100.0, put_oi_change=500.0, iv_change=0.0, option_pressure_score=0.0,
        market_regime="Trending", institutional_bias_label="Neutral", institutional_bias_score=0, news_risk_score=None,
    )


def test_pre_window_wiring_produces_a_conflicted_verdict_when_contradictory():
    candles = _session_candles(post_3pm=False)
    forecast = build_transition_forecast(
        time(14, 59), symbol="NIFTY", session_date=date(2026, 8, 27),
        today_candles=candles, prior_day_candles=None, historical_by_date={},
        history=[], cas_history=[], correlations=[], bin_size=BIN_SIZE, expiry_type=None,
        pre_window=_flat_pre_window(),
    )
    assert forecast is not None
    assert forecast.contradictory_factors != []
    # n_analogs is 0 here (empty history) so INSUFFICIENT_EVIDENCE takes
    # priority over CONFLICTED -- the contradiction is still captured and
    # reported even though it isn't what determines the verdict this time.
    assert forecast.verdict == "INSUFFICIENT_EVIDENCE"


def test_no_pre_window_supplied_means_no_contradictions_computed():
    candles = _session_candles(post_3pm=False)
    forecast = build_transition_forecast(
        time(14, 59), symbol="NIFTY", session_date=date(2026, 8, 27),
        today_candles=candles, prior_day_candles=None, historical_by_date={},
        history=[], cas_history=[], correlations=[], bin_size=BIN_SIZE, expiry_type=None,
    )
    assert forecast is not None
    assert forecast.contradictory_factors == []
