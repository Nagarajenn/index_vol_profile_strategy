"""Volume Trend Classification and Volume Character Classification.

Character is explicitly a reasonable, documented heuristic synthesis
(Wyckoff-inspired), not a claim of matching one canonical textbook
definition -- same framing already used for Profile Shape/Opening Type/
Rotation Factor in analytics/volume_profile_intelligence.py.
"""

from typing import Literal

import pandas as pd

from .models import AbsorptionSignal, BuySellDominance, ExhaustionSignal, VolumeCharacter, VolumeTrend, VolumeTrendLabel

TREND_WINDOW = 20  # split 10 older / 10 newer
TREND_STRONG_THRESHOLD_PCT = 30.0
TREND_THRESHOLD_PCT = 10.0

# +/- this price change over the trend window counts as "flat" for the
# character synthesis below (chosen over an exact 0% cutoff so ordinary
# tick-level noise on a genuinely flat session doesn't tip into up/down).
PRICE_FLAT_THRESHOLD_PCT = 0.05


def compute_volume_trend(enriched: pd.DataFrame, window: int = TREND_WINDOW) -> VolumeTrend | None:
    """Splits the trailing `window` candles in half and compares average
    volume between the two halves. Returns None with fewer than `window`
    candles available."""
    if len(enriched) < window:
        return None

    half = window // 2
    recent = enriched["volume"].tail(window)
    first_half_avg = float(recent.iloc[:half].mean())
    second_half_avg = float(recent.iloc[half:].mean())

    if first_half_avg <= 0:
        return VolumeTrend(window_minutes=window, pct_change=None, label="Stable")

    pct_change = (second_half_avg - first_half_avg) / first_half_avg * 100
    label: VolumeTrendLabel
    if pct_change >= TREND_STRONG_THRESHOLD_PCT:
        label = "Strong Increasing"
    elif pct_change >= TREND_THRESHOLD_PCT:
        label = "Increasing"
    elif pct_change <= -TREND_STRONG_THRESHOLD_PCT:
        label = "Strong Decreasing"
    elif pct_change <= -TREND_THRESHOLD_PCT:
        label = "Decreasing"
    else:
        label = "Stable"

    return VolumeTrend(window_minutes=window, pct_change=pct_change, label=label)


def _price_direction(enriched: pd.DataFrame, window: int) -> Literal["up", "down", "flat"]:
    if len(enriched) < window:
        return "flat"
    recent = enriched.tail(window)
    start = float(recent["close"].iloc[0])
    end = float(recent["close"].iloc[-1])
    if start <= 0:
        return "flat"
    pct = (end - start) / start * 100
    if pct >= PRICE_FLAT_THRESHOLD_PCT:
        return "up"
    if pct <= -PRICE_FLAT_THRESHOLD_PCT:
        return "down"
    return "flat"


def classify_volume_character(
    enriched: pd.DataFrame,
    trend: VolumeTrend | None,
    dominance: BuySellDominance,
    absorption: AbsorptionSignal,
    exhaustion: ExhaustionSignal,
) -> VolumeCharacter:
    """First-match-wins heuristic. Falls back to Quiet-Consolidation (a
    safe default, mirroring market_transition/live_advisor.py's
    compute_transition_risk_level() "Observe" fallback philosophy) rather
    than forcing a confident label out of ambiguous or thin signals."""
    if exhaustion.detected or absorption.detected:
        pattern = "an exhaustion signal (climactic volume after an extended move, with a rejection wick)" if exhaustion.detected else "an absorption signal (a volume spike with little price movement)"
        return VolumeCharacter(label="Climactic", rationale=f"{pattern} was detected.")

    window = trend.window_minutes if trend is not None else TREND_WINDOW
    price_dir = _price_direction(enriched, window)
    trend_rising = trend is not None and trend.label in ("Increasing", "Strong Increasing")
    trend_not_falling = trend is None or trend.label not in ("Decreasing", "Strong Decreasing")
    side = dominance.dominant_side

    if price_dir in ("flat", "down") and trend_rising and side == "buy":
        return VolumeCharacter(label="Accumulation", rationale="rising volume with sustained buy dominance while price holds flat or drifts down")
    if price_dir in ("flat", "up") and trend_rising and side == "sell":
        return VolumeCharacter(label="Distribution", rationale="rising volume with sustained sell dominance while price holds flat or drifts up")
    if price_dir == "up" and trend_not_falling and side == "buy":
        return VolumeCharacter(label="Markup", rationale="price advancing on buy-dominant volume that isn't fading")
    if price_dir == "down" and trend_not_falling and side == "sell":
        return VolumeCharacter(label="Markdown", rationale="price declining on sell-dominant volume that isn't fading")

    return VolumeCharacter(label="Quiet-Consolidation", rationale="no clear directional volume/price synthesis detected")
