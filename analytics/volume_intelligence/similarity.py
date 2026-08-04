"""Historical Volume Similarity: compares today's cumulative-volume-shape
and rolling buy/sell-dominance curves against each historical day's, via a
lightweight distance metric -- NOT market_transition/scoring.py's k-NN/
correlation-study machinery (that validates which FACTORS are
statistically significant across history; this is a single-pair curve
distance per day, a much simpler and cheaper problem).
"""

import statistics as pystats
from datetime import date

import pandas as pd

from .models import BaselineReading, DominantSide, HistoricalSimilarity, ResemblanceLabel, SimilarDay
from .pressure import _dominant_side
from .proxy import attach_buy_sell_columns

MIN_SIMILARITY_DAYS = 5
MIN_ELAPSED_MINUTES = 5.0
TOP_N_SIMILAR_DAYS = 5
N_CHECKPOINTS = 10  # points sampled along each day's 0..T curve for the distance calc
DOMINANCE_ROLL_WINDOW = 8

HIGH_VOLUME_RATIO_THRESHOLD = 1.3
LOW_VOLUME_RATIO_THRESHOLD = 0.7


def _build_curves(day_df: pd.DataFrame, elapsed_minutes: float, n_checkpoints: int) -> tuple[list[float], list[float]] | None:
    """Samples `n_checkpoints` evenly-spaced elapsed-minute marks from 0 to
    `elapsed_minutes` (using the last available row at or before each
    mark) and returns (cumulative-volume-fraction curve, rolling
    dominance-ratio curve). None if this day doesn't have data reaching
    `elapsed_minutes` yet, or has zero volume by that point."""
    if day_df is None or day_df.empty:
        return None

    start = day_df["timestamp"].iloc[0]
    elapsed = (day_df["timestamp"] - start).dt.total_seconds() / 60
    if elapsed.iloc[-1] < elapsed_minutes:
        return None

    enriched = attach_buy_sell_columns(day_df)
    cum_volume = enriched["volume"].cumsum()
    roll_buy = enriched["buy_volume"].rolling(DOMINANCE_ROLL_WINDOW, min_periods=1).sum()
    roll_sell = enriched["sell_volume"].rolling(DOMINANCE_ROLL_WINDOW, min_periods=1).sum()
    roll_total = roll_buy + roll_sell
    dominance_ratio = (roll_buy / roll_total).where(roll_total > 0, 0.5)

    marks = [elapsed_minutes * k / (n_checkpoints - 1) for k in range(n_checkpoints)] if n_checkpoints > 1 else [elapsed_minutes]
    cum_frac_curve: list[float] = []
    dominance_curve: list[float] = []
    for mark in marks:
        idx = max(0, int(elapsed.searchsorted(mark, side="right")) - 1)
        cum_frac_curve.append(float(cum_volume.iloc[idx]))
        dominance_curve.append(float(dominance_ratio.iloc[idx]))

    total_at_cutoff = cum_frac_curve[-1]
    if total_at_cutoff <= 0:
        return None
    cum_frac_curve = [v / total_at_cutoff for v in cum_frac_curve]
    return cum_frac_curve, dominance_curve


def _resemblance_label(top_days: list[SimilarDay]) -> ResemblanceLabel | None:
    if not top_days:
        return None

    avg_ratio = pystats.mean(d.total_volume_ratio for d in top_days)
    if avg_ratio >= HIGH_VOLUME_RATIO_THRESHOLD:
        return "climactic/high-volume sessions"
    if avg_ratio <= LOW_VOLUME_RATIO_THRESHOLD:
        return "quiet/low-volume sessions"

    sides = [d.dominant_side for d in top_days]
    buy_count = sides.count("buy")
    sell_count = sides.count("sell")
    if buy_count > sell_count and buy_count > len(sides) / 2:
        return "accumulation-like sessions"
    if sell_count > buy_count and sell_count > len(sides) / 2:
        return "distribution-like sessions"
    return "mixed/typical sessions"


def compute_historical_similarity(
    enriched: pd.DataFrame,
    historical_by_date: dict[date, pd.DataFrame],
    rvol_20d_baseline: BaselineReading | None = None,
) -> HistoricalSimilarity:
    """`enriched` is today's candles (buy/sell columns are re-derived
    internally for consistency with how each historical day is processed,
    so a plain OHLCV DataFrame works too). `rvol_20d_baseline`, if
    supplied (the engine already computes it for RVOL), lets each
    SimilarDay's total_volume_ratio be reported against the same 20-day
    reference the rest of the panel uses; without it, the ratio falls back
    to a neutral 1.0 (informational field only, doesn't affect ranking)."""
    if enriched.empty:
        return HistoricalSimilarity()

    elapsed_minutes = float((enriched["timestamp"].iloc[-1] - enriched["timestamp"].iloc[0]).total_seconds() / 60)
    if elapsed_minutes < MIN_ELAPSED_MINUTES:
        return HistoricalSimilarity(n_days_compared=0)

    today_curves = _build_curves(enriched, elapsed_minutes, N_CHECKPOINTS)
    if today_curves is None:
        return HistoricalSimilarity(n_days_compared=0)
    today_cum_frac, today_dominance = today_curves

    scored: list[tuple[float, date, DominantSide, float]] = []
    n_compared = 0
    for d, day_df in historical_by_date.items():
        curves = _build_curves(day_df, elapsed_minutes, N_CHECKPOINTS)
        if curves is None:
            continue
        n_compared += 1
        day_cum_frac, day_dominance = curves

        volume_distance = pystats.mean(abs(a - b) for a, b in zip(today_cum_frac, day_cum_frac))
        dominance_distance = pystats.mean(abs(a - b) for a, b in zip(today_dominance, day_dominance))
        distance = 0.5 * volume_distance + 0.5 * dominance_distance

        day_enriched = attach_buy_sell_columns(day_df)
        start = day_df["timestamp"].iloc[0]
        cutoff = start + pd.Timedelta(minutes=elapsed_minutes)
        window = day_enriched[day_enriched["timestamp"] <= cutoff]
        day_cum_buy = float(window["buy_volume"].sum())
        day_cum_sell = float(window["sell_volume"].sum())
        day_ratio = day_cum_buy / (day_cum_buy + day_cum_sell) if (day_cum_buy + day_cum_sell) > 0 else 0.5
        day_side = _dominant_side(day_ratio)

        day_total_volume = float(window["volume"].sum())
        volume_ratio = (
            day_total_volume / rvol_20d_baseline.cumulative_avg_volume
            if rvol_20d_baseline is not None and rvol_20d_baseline.cumulative_avg_volume
            else 1.0
        )

        scored.append((distance, d, day_side, volume_ratio))

    if n_compared < MIN_SIMILARITY_DAYS:
        return HistoricalSimilarity(n_days_compared=n_compared)

    scored.sort(key=lambda t: t[0])
    top_days = [
        SimilarDay(session_date=d, distance=distance, similarity=1 / (1 + distance), dominant_side=side, total_volume_ratio=ratio)
        for distance, d, side, ratio in scored[:TOP_N_SIMILAR_DAYS]
    ]

    return HistoricalSimilarity(top_days=top_days, resemblance_label=_resemblance_label(top_days), n_days_compared=n_compared)
