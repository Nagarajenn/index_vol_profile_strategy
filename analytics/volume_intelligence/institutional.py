"""Institutional Participation Score -- a volume-side-only heuristic
composite of RVOL magnitude, candle "blockiness" (a handful of unusually
large-volume bars vs. evenly spread volume), and sustained buy/sell
dominance. Deliberately does NOT read option-chain OI -- that's
analytics/institutional_bias.py's job (OI writer-positioning + PCR); this
is a complementary, distinct signal source, not a duplicate, and the two
are only cross-referenced as separate context at the narrative layer.
"""

import pandas as pd

from .models import BuySellDominance, InstitutionalLabel, InstitutionalParticipation, RvolReading

BLOCKINESS_WINDOW = 10
BLOCKINESS_MULTIPLE = 1.5

RVOL_WEIGHT = 0.4
BLOCKINESS_WEIGHT = 0.35
DOMINANCE_WEIGHT = 0.25


def _compute_blockiness(enriched: pd.DataFrame) -> float:
    """Fraction of the trailing window's candles whose volume is at least
    BLOCKINESS_MULTIPLE times the window's median volume -- a handful of
    unusually large prints (vs. evenly spread small ones) is a documented
    proxy for larger, less retail-like participation."""
    window = enriched.tail(BLOCKINESS_WINDOW)
    if window.empty:
        return 0.0
    median_vol = window["volume"].median()
    if median_vol <= 0:
        return 0.0
    big_count = int((window["volume"] >= BLOCKINESS_MULTIPLE * median_vol).sum())
    return big_count / len(window)


def _institutional_label(score: int) -> InstitutionalLabel:
    if score < 20:
        return "Minimal"
    if score < 40:
        return "Low"
    if score < 60:
        return "Moderate"
    if score < 80:
        return "High"
    return "Very High"


def compute_institutional_participation(
    rvol: RvolReading, dominance: BuySellDominance, enriched: pd.DataFrame
) -> InstitutionalParticipation:
    rvol_component = 0.5  # neutral default when the historical RVOL baseline isn't available yet
    if rvol.primary is not None and rvol.primary.interval_rvol_pct is not None:
        rvol_component = min(rvol.primary.interval_rvol_pct / 200.0, 1.0)

    blockiness_component = _compute_blockiness(enriched)
    dominance_component = (dominance.consecutive_dominant_minutes / dominance.window_minutes) if dominance.window_minutes > 0 else 0.0

    score = round(100 * (RVOL_WEIGHT * rvol_component + BLOCKINESS_WEIGHT * blockiness_component + DOMINANCE_WEIGHT * dominance_component))
    score = max(0, min(100, score))

    return InstitutionalParticipation(
        score=score,
        label=_institutional_label(score),
        rvol_component=rvol_component,
        blockiness_component=blockiness_component,
        dominance_component=dominance_component,
    )
