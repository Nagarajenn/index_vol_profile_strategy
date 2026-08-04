"""Volume magnitude vs. baseline: Relative Volume (RVOL), Acceleration/
Deceleration, Spike Detection, Dry-up Detection.

All four answer variations of "is volume, right now, unusually large/small/
speeding-up/slowing-down relative to a baseline" -- distinct from
pressure.py, which is about WHICH SIDE (buy/sell) has volume, not how much.
"""

import pandas as pd

from .models import BaselineGroup, BaselineReading, RvolBaselineResult, RvolLabel, RvolReading, VolumeAcceleration, VolumeDryUp, VolumeSpike

# Same 115%/85% thresholds analytics/volume_profile_intelligence.py's
# compute_volume_pace() already uses -- kept consistent across the codebase.
RVOL_ABOVE_THRESHOLD_PCT = 115.0
RVOL_BELOW_THRESHOLD_PCT = 85.0

DEFAULT_ACCELERATION_WINDOW = 5
ACCELERATION_UP_RATIO = 1.2
ACCELERATION_DOWN_RATIO = 0.8

DEFAULT_ROLLING_WINDOW = 20
SPIKE_MULTIPLE = 2.5
DRYUP_FRACTION = 0.4


def _rvol_label(interval_pct: float) -> RvolLabel:
    if interval_pct >= RVOL_ABOVE_THRESHOLD_PCT:
        return "Above Average"
    if interval_pct <= RVOL_BELOW_THRESHOLD_PCT:
        return "Below Average"
    return "Average"


def compute_rvol(today_candles: pd.DataFrame, baseline_readings: dict[BaselineGroup, BaselineReading]) -> RvolReading:
    """Interval RVOL (this minute vs. the baseline's average volume at the
    same elapsed minute) and cumulative RVOL (today's cumulative volume so
    far vs. the baseline's average cumulative volume at the same elapsed
    point), for every baseline group supplied. `primary` is the
    last_20_days read, used for the headline figure."""
    if today_candles.empty or not baseline_readings:
        return RvolReading()

    current_volume = float(today_candles["volume"].iloc[-1])
    cum_volume = float(today_candles["volume"].sum())

    by_baseline: dict[BaselineGroup, RvolBaselineResult] = {}
    for group, baseline in baseline_readings.items():
        interval_pct = (current_volume / baseline.interval_avg_volume * 100) if baseline.interval_avg_volume else None
        cumulative_pct = (cum_volume / baseline.cumulative_avg_volume * 100) if baseline.cumulative_avg_volume else None
        by_baseline[group] = RvolBaselineResult(
            group=group,
            interval_rvol_pct=interval_pct,
            cumulative_rvol_pct=cumulative_pct,
            label=_rvol_label(interval_pct) if interval_pct is not None else None,
            sample_days=baseline.sample_days,
        )

    return RvolReading(by_baseline=by_baseline, primary=by_baseline.get("last_20_days"))


def compute_volume_acceleration(today_candles: pd.DataFrame, window: int = DEFAULT_ACCELERATION_WINDOW) -> VolumeAcceleration | None:
    """Is the RATE of total volume itself speeding up or slowing down --
    compares the average volume of the most recent `window` candles against
    the `window` candles before that. Returns None with fewer than
    2*window candles available (too little data for either half)."""
    if len(today_candles) < window * 2:
        return None

    volumes = today_candles["volume"]
    recent_avg = float(volumes.iloc[-window:].mean())
    prior_avg = float(volumes.iloc[-2 * window : -window].mean())

    ratio = recent_avg / prior_avg if prior_avg > 0 else None
    pct_change = (ratio - 1) * 100 if ratio is not None else None

    if ratio is not None and ratio >= ACCELERATION_UP_RATIO:
        label = "Accelerating"
    elif ratio is not None and ratio <= ACCELERATION_DOWN_RATIO:
        label = "Decelerating"
    else:
        label = "Stable"

    return VolumeAcceleration(recent_avg_volume=recent_avg, prior_avg_volume=prior_avg, ratio=ratio, pct_change=pct_change, label=label)


def _resolve_magnitude_baseline(
    today_candles: pd.DataFrame, baseline_20d: BaselineReading | None, rolling_window: int = DEFAULT_ROLLING_WINDOW
) -> tuple[float | None, str | None]:
    """Prefers the historical 20-day baseline (already gated to >=3 sample
    days by baselines.py before it's ever passed in here); falls back to an
    intraday rolling average of the prior `rolling_window` candles
    (excluding the current one) when the historical baseline isn't
    available yet -- e.g. early in the dataset's life, or the first few
    weeks of live data."""
    if baseline_20d is not None and baseline_20d.interval_avg_volume:
        return baseline_20d.interval_avg_volume, "historical_20d"

    volumes = today_candles["volume"]
    if len(volumes) < 2:
        return None, None
    window = volumes.iloc[:-1].tail(rolling_window)
    if window.empty:
        return None, None
    avg = float(window.mean())
    return (avg if avg > 0 else None), "intraday_rolling"


def compute_volume_spike(today_candles: pd.DataFrame, baseline_20d: BaselineReading | None) -> VolumeSpike:
    if today_candles.empty:
        return VolumeSpike(is_spike=False, multiple=None, baseline_source=None, baseline_volume=None)

    current = float(today_candles["volume"].iloc[-1])
    baseline_volume, source = _resolve_magnitude_baseline(today_candles, baseline_20d)
    if baseline_volume is None:
        return VolumeSpike(is_spike=False, multiple=None, baseline_source=None, baseline_volume=None)

    multiple = current / baseline_volume
    return VolumeSpike(is_spike=multiple >= SPIKE_MULTIPLE, multiple=multiple, baseline_source=source, baseline_volume=baseline_volume)


def compute_volume_dryup(today_candles: pd.DataFrame, baseline_20d: BaselineReading | None) -> VolumeDryUp:
    if today_candles.empty:
        return VolumeDryUp(is_dryup=False, fraction=None, baseline_source=None, baseline_volume=None)

    current = float(today_candles["volume"].iloc[-1])
    baseline_volume, source = _resolve_magnitude_baseline(today_candles, baseline_20d)
    if baseline_volume is None:
        return VolumeDryUp(is_dryup=False, fraction=None, baseline_source=None, baseline_volume=None)

    fraction = current / baseline_volume
    return VolumeDryUp(is_dryup=fraction <= DRYUP_FRACTION, fraction=fraction, baseline_source=source, baseline_volume=baseline_volume)
