"""Flattens analytics.volume_intelligence.engine.compute_volume_intelligence
(called unmodified) into a single feature row. `narrative`,
`daily_volume_trend`, and `significant_intervals` are deliberately omitted --
they're prose/table outputs for the live dashboard, not per-minute numeric
features."""

from datetime import date

import pandas as pd

from analytics.volume_intelligence.engine import compute_volume_intelligence
from market_transition.expiry_calendar import ExpiryType

from .models import VolumeIntelligenceFeatureSet


def compute_volume_intelligence_feature_set(
    symbol: str,
    today_candles: pd.DataFrame,
    historical_by_date: dict[date, pd.DataFrame],
    expiry_calendar: dict[date, ExpiryType] | None = None,
) -> VolumeIntelligenceFeatureSet:
    """`today_candles` must already be truncated to T; `historical_by_date`
    must already be filtered to strictly-prior trading days (see
    quant_features.cutoff)."""
    vi = compute_volume_intelligence(symbol, today_candles, historical_by_date, expiry_calendar)

    primary = vi.rvol.primary if vi.rvol else None
    top_similar = vi.similarity.top_days[0] if vi.similarity and vi.similarity.top_days else None

    return VolumeIntelligenceFeatureSet(
        rvol_interval_pct=primary.interval_rvol_pct if primary else None,
        rvol_cumulative_pct=primary.cumulative_rvol_pct if primary else None,
        rvol_label=primary.label if primary else None,
        volume_acceleration_label=vi.acceleration.label if vi.acceleration else None,
        dominance_ratio=vi.dominance.dominance_ratio if vi.dominance else None,
        dominant_side=vi.dominance.dominant_side if vi.dominance else None,
        consecutive_dominant_minutes=vi.dominance.consecutive_dominant_minutes if vi.dominance else None,
        cumulative_pressure_ratio=vi.cumulative_pressure.pressure_ratio if vi.cumulative_pressure else None,
        momentum_score=vi.momentum.normalized_score if vi.momentum else None,
        momentum_label=vi.momentum.label if vi.momentum else None,
        institutional_participation_score=vi.institutional.score if vi.institutional else None,
        institutional_participation_label=vi.institutional.label if vi.institutional else None,
        is_volume_spike=vi.spike.is_spike if vi.spike else None,
        is_volume_dryup=vi.dryup.is_dryup if vi.dryup else None,
        is_absorption=vi.absorption.detected if vi.absorption else None,
        is_exhaustion=vi.exhaustion.detected if vi.exhaustion else None,
        volume_trend_label=vi.trend.label if vi.trend else None,
        volume_character_label=vi.character.label if vi.character else None,
        historical_similarity_top1_score=top_similar.similarity if top_similar else None,
        forecast_probability_continuation=vi.forecast.probability_continuation if vi.forecast else None,
        forecast_confidence=vi.forecast.confidence if vi.forecast else None,
    )
