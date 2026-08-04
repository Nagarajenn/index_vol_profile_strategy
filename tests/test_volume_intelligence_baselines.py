from datetime import date, timedelta

import pytest

from analytics.volume_intelligence.baselines import (
    compute_all_baseline_readings,
    compute_baseline_reading,
    resolve_baseline_groups,
)
from market_transition.expiry_calendar import build_expiry_calendar
from tests.fixtures.synthetic_candles import make_candles


def _make_day(date_str: str, volumes: list[float]) -> "object":
    rows = []
    for i, v in enumerate(volumes):
        minute = 15 + i
        hh = 9 + minute // 60
        mm = minute % 60
        rows.append({"time": f"{hh:02d}:{mm:02d}", "o": 100.0, "h": 100.0, "l": 100.0, "c": 100.0, "v": v, "date": date_str})
    return make_candles(rows)


def test_resolve_baseline_groups_last_5_and_20_slicing():
    base = date(2026, 6, 1)
    dates = [base + timedelta(days=i) for i in range(30)]
    historical_by_date = {d: _make_day(d.isoformat(), [100]) for d in dates}
    today = base + timedelta(days=30)

    groups = resolve_baseline_groups("NIFTY", today, historical_by_date)

    assert groups["last_5_days"] == dates[-5:]
    assert groups["last_20_days"] == dates[-20:]
    assert groups["yesterday"] == [dates[-1]]


def test_resolve_baseline_groups_same_weekday():
    base = date(2026, 7, 20)
    same_weekday_date = base + timedelta(days=7)
    other_date = base + timedelta(days=1)
    historical_by_date = {
        base: _make_day(base.isoformat(), [100]),
        same_weekday_date: _make_day(same_weekday_date.isoformat(), [100]),
        other_date: _make_day(other_date.isoformat(), [100]),
    }
    today = base + timedelta(days=14)  # same weekday as base and base+7

    groups = resolve_baseline_groups("NIFTY", today, historical_by_date)

    assert groups["same_weekday"] == sorted([base, same_weekday_date])


def test_resolve_baseline_groups_expiry_day_included_when_today_is_expiry():
    symbol = "NIFTY"
    calendar = build_expiry_calendar(symbol, date(2026, 6, 1), date(2026, 8, 31))
    expiry_dates = sorted(calendar.keys())
    assert len(expiry_dates) >= 4
    today = expiry_dates[-1]
    non_expiry_date = today - timedelta(days=1)

    historical_by_date = {d: _make_day(d.isoformat(), [100]) for d in expiry_dates[:-1]}
    if non_expiry_date not in historical_by_date and non_expiry_date not in calendar:
        historical_by_date[non_expiry_date] = _make_day(non_expiry_date.isoformat(), [100])

    groups = resolve_baseline_groups(symbol, today, historical_by_date, calendar)

    assert set(groups["expiry_day"]) == set(expiry_dates[:-1])
    assert non_expiry_date not in groups["expiry_day"]


def test_resolve_baseline_groups_expiry_day_omitted_when_today_not_expiry():
    symbol = "NIFTY"
    calendar = build_expiry_calendar(symbol, date(2026, 6, 1), date(2026, 8, 31))
    today = date(2026, 7, 22)
    while today in calendar:
        today += timedelta(days=1)
    historical_by_date = {d: _make_day(d.isoformat(), [100]) for d in list(calendar.keys())[:3]}

    groups = resolve_baseline_groups(symbol, today, historical_by_date, calendar)

    assert groups["expiry_day"] == []
    assert groups["monthly_expiry_day"] == []


def test_resolve_baseline_groups_monthly_expiry_only_when_today_is_monthly():
    symbol = "NIFTY"
    calendar = build_expiry_calendar(symbol, date(2026, 4, 1), date(2026, 8, 31))
    monthly_dates = sorted(d for d, t in calendar.items() if t == "monthly")
    weekly_dates = sorted(d for d, t in calendar.items() if t == "weekly")
    assert len(monthly_dates) >= 2
    today = monthly_dates[-1]

    historical_by_date = {d: _make_day(d.isoformat(), [100]) for d in monthly_dates[:-1]}
    for d in weekly_dates[:3]:
        historical_by_date.setdefault(d, _make_day(d.isoformat(), [100]))

    groups = resolve_baseline_groups(symbol, today, historical_by_date, calendar)

    assert set(groups["monthly_expiry_day"]) == set(monthly_dates[:-1])
    assert set(groups["expiry_day"]) >= set(monthly_dates[:-1])


def test_compute_baseline_reading_averages_interval_and_cumulative():
    d1, d2, d3 = date(2026, 7, 1), date(2026, 7, 2), date(2026, 7, 3)
    historical_by_date = {
        d1: _make_day("2026-07-01", [100, 200, 300, 400, 500]),
        d2: _make_day("2026-07-02", [110, 210, 310, 410, 510]),
        d3: _make_day("2026-07-03", [120, 220, 320, 420, 520]),
    }

    reading = compute_baseline_reading("last_5_days", [d1, d2, d3], historical_by_date, elapsed_minutes=2.0)

    assert reading is not None
    assert reading.sample_days == 3
    assert reading.interval_avg_volume == pytest.approx(310.0)  # (300+310+320)/3
    assert reading.cumulative_avg_volume == pytest.approx(630.0)  # (600+630+660)/3


def test_compute_baseline_reading_none_when_insufficient_days():
    d1, d2 = date(2026, 7, 1), date(2026, 7, 2)
    historical_by_date = {d1: _make_day("2026-07-01", [100]), d2: _make_day("2026-07-02", [100])}

    reading = compute_baseline_reading("last_5_days", [d1, d2], historical_by_date, elapsed_minutes=0.0)

    assert reading is None


def test_compute_all_baseline_readings_omits_thin_groups():
    d1 = date(2026, 7, 1)
    historical_by_date = {d1: _make_day("2026-07-01", [100, 200])}
    today = date(2026, 7, 2)

    readings = compute_all_baseline_readings("NIFTY", today, historical_by_date, elapsed_minutes=0.0)

    assert "yesterday" in readings
    assert "last_5_days" not in readings
    assert "expiry_day" not in readings
