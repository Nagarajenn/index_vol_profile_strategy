"""Historical comparison baseline builder: resolves the 6 comparison
groupings (yesterday, last 5 days, last 20 days, same weekday, expiry day,
monthly expiry day) and computes elapsed-time-aligned average volume curves
for each -- generalizing the same "average across days, at the same
elapsed session time" technique analytics/volume_profile_intelligence.py's
compute_volume_pace() already uses for a single overall pace read, across
6 distinct groupings and reporting both interval and cumulative figures.

Elapsed time is measured relative to each day's OWN first candle (not a
config session-open constant), matching compute_volume_pace()'s exact
technique -- this keeps the module dependency-free (no config/ import) and
robust to days where the pipeline started late.

Expiry classification is reused from market_transition.expiry_calendar --
not reimplemented here.
"""

import statistics as pystats
from datetime import date, timedelta

import pandas as pd

from market_transition.expiry_calendar import ExpiryType, classify_expiry_day

from .models import BaselineGroup, BaselineReading, DailyComparisonLabel, DailyVolumeComparison, DailyVolumeTrend

# last_5_days/last_20_days/same_weekday need enough days for the average to
# mean anything; expiry groups occur far less often in a 60-day window
# (~8-9 weekly, ~2-3 monthly) so get a lower bar; yesterday is inherently a
# single day.
MIN_BASELINE_GROUP_DAYS: dict[BaselineGroup, int] = {
    "yesterday": 1,
    "last_5_days": 3,
    "last_20_days": 3,
    "same_weekday": 3,
    "expiry_day": 2,
    "monthly_expiry_day": 2,
}


def resolve_baseline_groups(
    symbol: str,
    today_date: date,
    historical_by_date: dict[date, pd.DataFrame],
    expiry_calendar: dict[date, ExpiryType] | None = None,
) -> dict[BaselineGroup, list[date]]:
    """Resolves WHICH historical dates belong to each of the 6 groups.
    Groups below their minimum sample count (see MIN_BASELINE_GROUP_DAYS)
    are left as-is here (empty or thin) -- compute_baseline_reading() is
    what actually omits them, based on how many days genuinely produced a
    usable reading, not just how many were candidates.
    """
    sorted_dates = sorted(d for d in historical_by_date if d < today_date)

    groups: dict[BaselineGroup, list[date]] = {
        "yesterday": sorted_dates[-1:],
        "last_5_days": sorted_dates[-5:],
        "last_20_days": sorted_dates[-20:],
        "same_weekday": [d for d in sorted_dates if d.weekday() == today_date.weekday()],
        "expiry_day": [],
        "monthly_expiry_day": [],
    }

    today_expiry_type = classify_expiry_day(symbol, today_date, expiry_calendar)
    if today_expiry_type is not None:
        groups["expiry_day"] = [d for d in sorted_dates if classify_expiry_day(symbol, d, expiry_calendar) is not None]
    if today_expiry_type == "monthly":
        groups["monthly_expiry_day"] = [d for d in sorted_dates if classify_expiry_day(symbol, d, expiry_calendar) == "monthly"]

    return groups


def compute_baseline_reading(
    group: BaselineGroup,
    dates: list[date],
    historical_by_date: dict[date, pd.DataFrame],
    elapsed_minutes: float,
) -> BaselineReading | None:
    """For each candidate date, finds the last candle at or before that
    day's own (session-start + elapsed_minutes) cutoff -- its volume is
    that day's "interval volume at this elapsed point," the sum of every
    candle up to and including it is that day's "cumulative volume."
    Returns None if fewer days produced a usable reading than
    MIN_BASELINE_GROUP_DAYS requires for this group.
    """
    interval_volumes: list[float] = []
    cumulative_volumes: list[float] = []
    dates_used: list[date] = []

    for d in dates:
        day_df = historical_by_date.get(d)
        if day_df is None or day_df.empty:
            continue
        day_start = day_df["timestamp"].iloc[0]
        cutoff = day_start + timedelta(minutes=elapsed_minutes)
        window = day_df[day_df["timestamp"] <= cutoff]
        if window.empty:
            continue
        interval_volumes.append(float(window["volume"].iloc[-1]))
        cumulative_volumes.append(float(window["volume"].sum()))
        dates_used.append(d)

    sample_days = len(dates_used)
    if sample_days < MIN_BASELINE_GROUP_DAYS.get(group, 3):
        return None

    return BaselineReading(
        group=group,
        elapsed_minutes=round(elapsed_minutes),
        interval_avg_volume=pystats.mean(interval_volumes) if interval_volumes else None,
        cumulative_avg_volume=pystats.mean(cumulative_volumes) if cumulative_volumes else None,
        sample_days=sample_days,
        dates_used=dates_used,
    )


def compute_all_baseline_readings(
    symbol: str,
    today_date: date,
    historical_by_date: dict[date, pd.DataFrame],
    elapsed_minutes: float,
    expiry_calendar: dict[date, ExpiryType] | None = None,
) -> dict[BaselineGroup, BaselineReading]:
    """Convenience: resolve_baseline_groups() + compute_baseline_reading()
    for all 6 groups, omitting any that come back None (thin data or "not
    applicable today", e.g. expiry_day/monthly_expiry_day on a non-expiry
    day)."""
    groups = resolve_baseline_groups(symbol, today_date, historical_by_date, expiry_calendar)
    readings: dict[BaselineGroup, BaselineReading] = {}
    for group, dates in groups.items():
        reading = compute_baseline_reading(group, dates, historical_by_date, elapsed_minutes)
        if reading is not None:
            readings[group] = reading
    return readings


DAILY_TREND_DEFAULT_DAYS = 5

_DAILY_COMPARISON_INTERPRETATION: dict[DailyComparisonLabel, str] = {
    "Much Higher": "Volume well above the prior day -- often reflects stronger institutional participation or a reaction to a significant event.",
    "Higher": "Volume above the prior day -- modestly increased participation.",
    "Similar": "Volume in line with the prior day -- no notable change in participation.",
    "Lower": "Volume below the prior day -- modestly reduced participation.",
    "Much Lower": "Volume well below the prior day -- often reflects fading interest or a lack of conviction.",
}


def _cumulative_volume_as_of(day_df: pd.DataFrame | None, elapsed_minutes: float) -> float | None:
    if day_df is None or day_df.empty:
        return None
    day_start = day_df["timestamp"].iloc[0]
    cutoff = day_start + timedelta(minutes=elapsed_minutes)
    window = day_df[day_df["timestamp"] <= cutoff]
    return float(window["volume"].sum()) if not window.empty else None


def _daily_comparison_label(pct_change: float) -> DailyComparisonLabel:
    if pct_change >= 50.0:
        return "Much Higher"
    if pct_change >= 15.0:
        return "Higher"
    if pct_change <= -50.0:
        return "Much Lower"
    if pct_change <= -15.0:
        return "Lower"
    return "Similar"


def compute_daily_volume_trend(
    today_candles: pd.DataFrame,
    historical_by_date: dict[date, pd.DataFrame],
    n_days: int = DAILY_TREND_DEFAULT_DAYS,
) -> DailyVolumeTrend | None:
    """Chain of day-over-day volume-so-far comparisons for the last
    `n_days` trading days (today, then each of the n_days most recent
    priors) -- each day compared only to the ONE day immediately before
    it, not to a multi-day average (that's compute_all_baseline_readings'
    job -- RVOL). "Volume-so-far" is elapsed-time-aligned to the current
    moment (today's last candle's elapsed time since session start), so
    it's a same-time-of-day comparison even while today's session is
    still in progress: "yesterday's volume as of 11:40am" vs "today's
    volume as of 11:40am", not yesterday's full-day total.
    """
    if today_candles.empty:
        return None

    elapsed_minutes = float((today_candles["timestamp"].iloc[-1] - today_candles["timestamp"].iloc[0]).total_seconds() / 60)
    today_date = today_candles["timestamp"].iloc[-1].date()

    sorted_prior_dates = sorted((d for d in historical_by_date if d < today_date), reverse=True)
    chain_dates: list[date] = [today_date] + sorted_prior_dates[:n_days]

    day_volumes: dict[date, float | None] = {}
    for d in chain_dates:
        day_df = today_candles if d == today_date else historical_by_date.get(d)
        day_volumes[d] = _cumulative_volume_as_of(day_df, elapsed_minutes)

    rows: list[DailyVolumeComparison] = []
    for i in range(min(n_days, len(chain_dates) - 1)):
        current_date, prior_date = chain_dates[i], chain_dates[i + 1]
        current_vol = day_volumes.get(current_date)
        if current_vol is None:
            continue
        prior_vol = day_volumes.get(prior_date)
        pct_change = ((current_vol - prior_vol) / prior_vol * 100) if prior_vol else None
        label = _daily_comparison_label(pct_change) if pct_change is not None else None
        interpretation = _DAILY_COMPARISON_INTERPRETATION[label] if label else "Not enough data to compare against the prior day."
        rows.append(
            DailyVolumeComparison(
                session_date=current_date,
                volume_as_of=current_vol,
                prior_day_volume_as_of=prior_vol,
                pct_change=pct_change,
                label=label,
                interpretation=interpretation,
            )
        )

    return DailyVolumeTrend(elapsed_minutes=round(elapsed_minutes), days=rows)
