"""Market regime classification: combines today's realized volatility
(compared against its own historical average at the same elapsed session
time -- the same pattern Volume Pace already uses in
analytics/volume_profile_intelligence.py) with today's trend-consistency
(reusing compute_rotation_factor) into one label.

Deliberately a simple 3-category scheme rather than a full volatility x
rotation matrix: with ~70-80 historical trading days, a finer taxonomy
would leave too few days per category for the correlation study in
statistics.py to say anything meaningful.
"""

from datetime import timedelta

import pandas as pd

from analytics.volume_profile_intelligence import compute_rotation_factor
from market_transition.models import MarketRegime

HIGH_VOL_THRESHOLD_PCT = 115.0
LOW_VOL_THRESHOLD_PCT = 85.0


def _realized_range(candles: pd.DataFrame) -> float:
    if candles.empty:
        return 0.0
    return float(candles["high"].max() - candles["low"].min())


def compute_volatility_pace_pct(today_candles: pd.DataFrame, historical_by_date: dict[object, pd.DataFrame]) -> float | None:
    """Today's realized range so far vs. the average realized range across
    the supplied historical days at the same elapsed session time, as a
    percentage (100 = exactly average)."""
    if today_candles.empty or not historical_by_date:
        return None

    session_start = today_candles["timestamp"].iloc[0]
    elapsed_minutes = (today_candles["timestamp"].iloc[-1] - session_start).total_seconds() / 60
    today_range = _realized_range(today_candles)

    reference_ranges: list[float] = []
    for day_df in historical_by_date.values():
        if day_df is None or day_df.empty:
            continue
        day_start = day_df["timestamp"].iloc[0]
        cutoff = day_start + timedelta(minutes=elapsed_minutes)
        window = day_df[day_df["timestamp"] <= cutoff]
        if not window.empty:
            reference_ranges.append(_realized_range(window))

    if not reference_ranges:
        return None
    avg_range = sum(reference_ranges) / len(reference_ranges)
    if avg_range <= 0:
        return None
    return today_range / avg_range * 100


def classify_market_regime(
    today_candles: pd.DataFrame,
    historical_by_date: dict[object, pd.DataFrame],
    rotation_period_minutes: int = 30,
) -> MarketRegime | None:
    if today_candles.empty:
        return None

    vol_pct = compute_volatility_pace_pct(today_candles, historical_by_date)
    rotation = compute_rotation_factor(today_candles, rotation_period_minutes)

    if vol_pct is not None and vol_pct >= HIGH_VOL_THRESHOLD_PCT:
        return "Volatile"
    if rotation.label == "Trending":
        return "Trending"
    return "Range-Bound"
