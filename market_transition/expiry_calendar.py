"""Weekly/monthly expiry-day classification, derived purely from the
calendar -- no dependency on option_chain history (which only goes back to
when Postgres persistence for it started, far less than the price history
this module needs to cover).

Current rules (verified live, effective 2025-09-01, stable across this
project's entire price-history window):
  - NIFTY weekly expiry: every Tuesday. Monthly: last Tuesday of the month.
  - SENSEX weekly expiry: every Thursday. Monthly: last Thursday of the month.
  - If the natural expiry weekday is a trading holiday, expiry moves to the
    previous trading day.
Source: NSE/BSE circulars, SEBI Oct-2024 one-weekly-expiry-per-exchange
mandate. If a future date range needs pre-2025-09-01 dates, this table
would need a second rule set -- not needed for this project's data (starts
2026-04-09).
"""

from datetime import date, timedelta
from typing import Literal

from pipeline.trading_calendar import is_trading_day

EXPIRY_WEEKDAY: dict[str, int] = {
    "NIFTY": 1,  # Tuesday
    "SENSEX": 3,  # Thursday
}

ExpiryType = Literal["weekly", "monthly"]


def _adjust_for_holiday(d: date) -> date:
    """Walk backward to the nearest trading day if `d` is a holiday/weekend."""
    while not is_trading_day(d):
        d -= timedelta(days=1)
    return d


def _last_weekday_of_month(year: int, month: int, weekday: int) -> date:
    if month == 12:
        next_month_first = date(year + 1, 1, 1)
    else:
        next_month_first = date(year, month + 1, 1)
    d = next_month_first - timedelta(days=1)
    while d.weekday() != weekday:
        d -= timedelta(days=1)
    return d


def build_expiry_calendar(symbol: str, start: date, end: date) -> dict[date, ExpiryType]:
    """Maps each actual (holiday-adjusted) expiry trading date in
    [start, end] to "weekly" or "monthly" for the given symbol."""
    weekday = EXPIRY_WEEKDAY[symbol]
    calendar: dict[date, ExpiryType] = {}

    monthly_by_month: dict[tuple[int, int], date] = {}
    cur = date(start.year, start.month, 1)
    end_scan = date(end.year, end.month, 1)
    while cur <= end_scan:
        natural_monthly = _last_weekday_of_month(cur.year, cur.month, weekday)
        monthly_by_month[(cur.year, cur.month)] = _adjust_for_holiday(natural_monthly)
        if cur.month == 12:
            cur = date(cur.year + 1, 1, 1)
        else:
            cur = date(cur.year, cur.month + 1, 1)

    d = start
    while d <= end:
        if d.weekday() == weekday:
            actual = _adjust_for_holiday(d)
            if start <= actual <= end:
                is_monthly = actual == monthly_by_month.get((d.year, d.month))
                calendar[actual] = "monthly" if is_monthly else "weekly"
        d += timedelta(days=1)

    return calendar


def classify_expiry_day(symbol: str, d: date, calendar: dict[date, ExpiryType] | None = None) -> ExpiryType | None:
    """Returns "weekly"/"monthly" if `d` is an expiry day for `symbol`, else
    None. Pass a precomputed `calendar` (from build_expiry_calendar) when
    classifying many dates to avoid rebuilding it each time."""
    if calendar is not None:
        return calendar.get(d)
    lookup = build_expiry_calendar(symbol, d - timedelta(days=35), d + timedelta(days=1))
    return lookup.get(d)
