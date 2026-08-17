"""Shared truncation helpers -- the one place that mechanically enforces
"never look past T" for every feature module in this package.

Every wrapped analytics module (vwap, volume_profile, volume_profile_
intelligence, analytics/volume_intelligence, swings/trendlines/support_
resistance/breakout_boxes, trend_classifier, confidence_score,
market_transition.market_regime) is already point-in-time-safe GIVEN
already-truncated inputs -- none of them read a wall clock internally. This
module is the single place responsible for producing those truncated
inputs, so no individual feature function has to remember to do it itself.
"""

from datetime import date

import pandas as pd


def truncate_candles(candles: pd.DataFrame, cutoff: pd.Timestamp) -> pd.DataFrame:
    """Rows with timestamp <= cutoff only, ascending, index reset."""
    if candles.empty:
        return candles
    return candles[candles["timestamp"] <= cutoff].reset_index(drop=True)


def historical_by_date_before(historical_by_date: dict[date, pd.DataFrame], session_date: date) -> dict[date, pd.DataFrame]:
    """Filters a {date: candles} dict to strictly-prior trading days -- the
    caller-side data-hygiene guarantee every wrapped module already assumes
    holds for `historical_by_date` (none of them re-check it themselves)."""
    return {d: df for d, df in historical_by_date.items() if d < session_date}
