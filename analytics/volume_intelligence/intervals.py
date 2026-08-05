"""Significant 5-Minute Intervals: buckets today's session into 5-minute
windows and flags the ones whose volume is notably above the historical
average for that same time-of-day window -- a coarser-grained, historized
sibling of rvol.py's single-point Spike Detection, aimed at surfacing
*where in today's session so far* unusual participation showed up, not
just whether the current minute is one.

Only buckets that clear the significance bar are ever returned -- most of
a session should produce few or none, same "don't spam" philosophy as
narrative.py's observation gate.
"""

import statistics as pystats
from datetime import date

import pandas as pd

from .models import DominantSide, PriceDirection, SignificantInterval
from .pressure import _dominant_side
from .proxy import attach_buy_sell_columns

BUCKET_MINUTES = 5
# Lower than rvol.py's SPIKE_MULTIPLE (2.5) -- a 5-min sum naturally smooths
# out the single-minute extremes that justify a stricter bar there, so a
# lower relative threshold is still a genuinely notable 5-min window.
SIGNIFICANCE_MULTIPLE = 1.8
MIN_BASELINE_DAYS_FOR_BUCKET = 3
PRICE_FLAT_THRESHOLD_PCT = 0.05  # matches character.py's threshold


def _bucket_baseline(historical_by_date: dict[date, pd.DataFrame], start_elapsed: float, end_elapsed: float) -> float | None:
    """Average volume, across historical days, within the same
    [start_elapsed, end_elapsed) window measured from each day's own
    session start -- only counts a day if its data actually covers the
    full bucket (no partial-bucket days silently pulling the average
    down)."""
    volumes: list[float] = []
    for day_df in historical_by_date.values():
        if day_df is None or day_df.empty:
            continue
        day_start = day_df["timestamp"].iloc[0]
        window_start = day_start + pd.Timedelta(minutes=start_elapsed)
        window_end = day_start + pd.Timedelta(minutes=end_elapsed)
        window = day_df[(day_df["timestamp"] >= window_start) & (day_df["timestamp"] < window_end)]
        if len(window) >= BUCKET_MINUTES:
            volumes.append(float(window["volume"].sum()))
    if len(volumes) < MIN_BASELINE_DAYS_FOR_BUCKET:
        return None
    return pystats.mean(volumes)


def _price_direction(open_price: float, close_price: float) -> PriceDirection:
    if open_price <= 0:
        return "flat"
    pct = (close_price - open_price) / open_price * 100
    if pct >= PRICE_FLAT_THRESHOLD_PCT:
        return "up"
    if pct <= -PRICE_FLAT_THRESHOLD_PCT:
        return "down"
    return "flat"


def _institutional_note(multiple: float, dominant_side: DominantSide) -> str:
    side_phrase = {"buy": "buy-side dominance", "sell": "sell-side dominance", "balanced": "no clear side dominance"}[dominant_side]
    return f"Volume {multiple:.1f}x the norm for this time of day with {side_phrase} -- consistent with possible institutional activity."


def _trend_note(price_direction: PriceDirection, dominant_side: DominantSide) -> str:
    if price_direction == "flat":
        return "Price barely moved despite the volume surge -- may indicate absorption; watch for a delayed move or reversal."
    aligned = (price_direction == "up" and dominant_side == "buy") or (price_direction == "down" and dominant_side == "sell")
    if aligned:
        return f"Price moved {price_direction} in line with the volume surge -- supports continuation of the {price_direction}-move."
    return f"Price moved {price_direction} while volume leaned the other way -- a divergence that may signal a coming reversal."


def compute_significant_intervals(
    today_candles: pd.DataFrame,
    historical_by_date: dict[date, pd.DataFrame],
    bucket_minutes: int = BUCKET_MINUTES,
    significance_multiple: float = SIGNIFICANCE_MULTIPLE,
) -> list[SignificantInterval]:
    if today_candles.empty:
        return []

    enriched = attach_buy_sell_columns(today_candles)
    session_start = enriched["timestamp"].iloc[0]
    elapsed = (enriched["timestamp"] - session_start).dt.total_seconds() / 60
    bucket_idx = (elapsed // bucket_minutes).astype(int)

    results: list[SignificantInterval] = []
    for idx, group in enriched.groupby(bucket_idx):
        start_elapsed = float(idx * bucket_minutes)
        end_elapsed = start_elapsed + bucket_minutes

        interval_volume = float(group["volume"].sum())
        buy = float(group["buy_volume"].sum())
        sell = float(group["sell_volume"].sum())
        ratio = buy / (buy + sell) if (buy + sell) > 0 else 0.5
        dominant_side = _dominant_side(ratio)

        baseline_volume = _bucket_baseline(historical_by_date, start_elapsed, end_elapsed)
        if baseline_volume is None or baseline_volume <= 0:
            continue
        multiple = interval_volume / baseline_volume
        if multiple < significance_multiple:
            continue
        pct_change = (interval_volume - baseline_volume) / baseline_volume * 100

        price_direction = _price_direction(float(group["open"].iloc[0]), float(group["close"].iloc[-1]))

        results.append(
            SignificantInterval(
                start_time=group["timestamp"].iloc[0].to_pydatetime(),
                end_time=group["timestamp"].iloc[-1].to_pydatetime(),
                interval_volume=interval_volume,
                baseline_volume=baseline_volume,
                pct_change=pct_change,
                multiple=multiple,
                dominant_side=dominant_side,
                price_direction=price_direction,
                institutional_note=_institutional_note(multiple, dominant_side),
                trend_note=_trend_note(price_direction, dominant_side),
            )
        )

    return results
