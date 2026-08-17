"""Expiry classification and simple time-of-session features, built on
market_transition.expiry_calendar.classify_expiry_day/build_expiry_calendar
(reused unmodified) -- the canonical expiry source of truth in this codebase.
"""

from datetime import date, timedelta

import pandas as pd

from market_transition.expiry_calendar import ExpiryType, build_expiry_calendar, classify_expiry_day

from .models import ExpiryFeatureSet

FORWARD_LOOKUP_DAYS = 35  # enough to always find both a weekly and a monthly expiry ahead


def _next_expiry_on_or_after(
    symbol: str,
    start_date: date,
    calendar: dict[date, ExpiryType],
    type_filter: ExpiryType | None,
) -> date | None:
    candidates = sorted(d for d, t in calendar.items() if d >= start_date and (type_filter is None or t == type_filter))
    return candidates[0] if candidates else None


def compute_expiry_feature_set(
    symbol: str,
    session_date: date,
    today_candles: pd.DataFrame,
    expiry_calendar: dict[date, ExpiryType] | None = None,
) -> ExpiryFeatureSet:
    """`today_candles` must already be truncated to T (used only to derive
    minutes-since-open -- elapsed time relative to the session's own first
    candle, matching the elapsed-time-alignment technique used throughout
    this codebase, not a config session-open constant)."""
    calendar = expiry_calendar
    if calendar is None:
        calendar = build_expiry_calendar(symbol, session_date, session_date + timedelta(days=FORWARD_LOOKUP_DAYS))

    expiry_type = classify_expiry_day(symbol, session_date, calendar)
    is_expiry_day = expiry_type is not None

    next_any_expiry = _next_expiry_on_or_after(symbol, session_date, calendar, type_filter=None)
    next_monthly_expiry = _next_expiry_on_or_after(symbol, session_date, calendar, type_filter="monthly")

    days_to_weekly_expiry = (next_any_expiry - session_date).days if next_any_expiry else None
    days_to_monthly_expiry = (next_monthly_expiry - session_date).days if next_monthly_expiry else None

    minutes_since_open = 0
    if not today_candles.empty:
        start = today_candles["timestamp"].iloc[0]
        end = today_candles["timestamp"].iloc[-1]
        minutes_since_open = int((end - start).total_seconds() // 60)

    return ExpiryFeatureSet(
        expiry_type=expiry_type,
        is_expiry_day=is_expiry_day,
        days_to_weekly_expiry=days_to_weekly_expiry,
        days_to_monthly_expiry=days_to_monthly_expiry,
        day_of_week=session_date.weekday(),
        minutes_since_open=minutes_since_open,
    )
