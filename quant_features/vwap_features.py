"""VWAP-distance and VWAP-slope features, built on top of an already-computed
VWAP series (analytics.vwap.compute_vwap, called once by the orchestrator and
shared with every feature module that needs it -- never recomputed here).
"""

import pandas as pd

from .models import VwapFeatures

VWAP_SLOPE_LOOKBACK_BARS = 5


def compute_vwap_features(
    vwap_series: pd.Series,
    close: float,
    atr_14: float | None,
    slope_lookback_bars: int = VWAP_SLOPE_LOOKBACK_BARS,
) -> VwapFeatures:
    """`vwap_series` must already be truncated to the desired cutoff T (it's
    the same series analytics.vwap.compute_vwap produces when called on
    already-truncated candles -- cumulative by construction, so truncating
    the input candles is sufficient, no separate truncation needed here)."""
    if vwap_series.empty:
        return VwapFeatures(vwap_now=None, vwap_distance_pct=None, vwap_distance_atr=None, vwap_slope_5m=None)

    vwap_now = float(vwap_series.iloc[-1])
    vwap_distance_pct = (close - vwap_now) / vwap_now if vwap_now else None
    vwap_distance_atr = (close - vwap_now) / atr_14 if atr_14 else None

    vwap_slope_5m = None
    if len(vwap_series) > slope_lookback_bars:
        prior = float(vwap_series.iloc[-1 - slope_lookback_bars])
        if prior:
            vwap_slope_5m = (vwap_now - prior) / prior

    return VwapFeatures(
        vwap_now=vwap_now,
        vwap_distance_pct=vwap_distance_pct,
        vwap_distance_atr=vwap_distance_atr,
        vwap_slope_5m=vwap_slope_5m,
    )
