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

from .models import BaselineGroup, BaselineReading

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
