"""3-way market regime (market_transition.market_regime.classify_market_regime,
reused unmodified) plus a new, clearly-marked-derived expanded taxonomy built
from the same primitives (compute_volatility_pace_pct, compute_rotation_factor)
plus the already-computed trend vote (analytics.trend_classifier.TrendResult,
passed in rather than recomputed -- see structure_features.py for why).

No 13-category regime classifier exists anywhere else in this codebase --
this is new code. Like Profile Shape/Opening Type/Volume Character before
it, it's a reasonable, deterministic, documented heuristic (first-match-wins),
not a claim of matching any canonical taxonomy.
"""

from datetime import date

import pandas as pd

from analytics.trend_classifier import TrendResult
from analytics.volume_profile_intelligence import RotationFactor, compute_rotation_factor
from market_transition.market_regime import (
    HIGH_VOL_THRESHOLD_PCT,
    LOW_VOL_THRESHOLD_PCT,
    classify_market_regime,
    compute_volatility_pace_pct,
)

from .models import MarketRegime3Way, MarketRegimeExpanded, RegimeFeatureSet


def classify_expanded_regime(
    regime_3way: MarketRegime3Way | None,
    volatility_pace_pct: float | None,
    rotation: RotationFactor,
    trend: TrendResult | None,
) -> MarketRegimeExpanded:
    trend_score = trend.score if trend else 0
    structure = trend.structure if trend else 0

    if volatility_pace_pct is not None and volatility_pace_pct >= HIGH_VOL_THRESHOLD_PCT and rotation.label == "Rotational":
        return "High-Volatility Choppy"
    if volatility_pace_pct is not None and volatility_pace_pct <= LOW_VOL_THRESHOLD_PCT and regime_3way == "Range-Bound":
        return "Low-Volatility Quiet"
    if regime_3way == "Volatile" and rotation.label == "Trending" and trend_score != 0:
        return "Breakout-Up" if trend_score > 0 else "Breakout-Down"
    # Structure vote (recent HH/HL vs LH/LL) disagreeing with the overall
    # trend score is a hint the trend just turned -- same "aligned vs not"
    # comparison analytics.confidence_score's structure_hh_hl sub-score
    # already makes, read here for the opposite (divergence) case.
    if structure != 0 and trend_score != 0 and (structure > 0) != (trend_score > 0):
        return "Reversal-Up" if structure > 0 else "Reversal-Down"
    if regime_3way == "Trending":
        if trend_score >= 2:
            return "Strong Uptrend"
        if trend_score <= -2:
            return "Strong Downtrend"
        if trend_score == 1:
            return "Uptrend" if rotation.label == "Trending" else "Weak Uptrend"
        if trend_score == -1:
            return "Downtrend" if rotation.label == "Trending" else "Weak Downtrend"
    return "Range-Bound"


def compute_regime_feature_set(
    today_candles: pd.DataFrame,
    historical_by_date: dict[date, pd.DataFrame],
    trend: TrendResult | None,
    rotation_period_minutes: int = 30,
) -> RegimeFeatureSet:
    """`today_candles` must already be truncated to T; `historical_by_date`
    must already be filtered to strictly-prior trading days (see
    quant_features.cutoff)."""
    regime_3way = classify_market_regime(today_candles, historical_by_date, rotation_period_minutes)
    if regime_3way is None:
        return RegimeFeatureSet(market_regime_3way=None, market_regime_expanded=None, volatility_pace_pct=None)

    volatility_pace_pct = compute_volatility_pace_pct(today_candles, historical_by_date)
    rotation = compute_rotation_factor(today_candles, rotation_period_minutes)
    expanded = classify_expanded_regime(regime_3way, volatility_pace_pct, rotation, trend)

    return RegimeFeatureSet(
        market_regime_3way=regime_3way,
        market_regime_expanded=expanded,
        volatility_pace_pct=volatility_pace_pct,
    )
