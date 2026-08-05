from datetime import date, timedelta

import pytest

from analytics.volume_intelligence.baselines import _daily_comparison_label, compute_daily_volume_trend
from tests.fixtures.synthetic_candles import make_candles


def _make_day(date_str: str, volumes: list[float]):
    rows = []
    for i, v in enumerate(volumes):
        minute = 15 + i
        hh = 9 + minute // 60
        mm = minute % 60
        rows.append({"time": f"{hh:02d}:{mm:02d}", "o": 100.0, "h": 100.0, "l": 100.0, "c": 100.0, "v": v, "date": date_str})
    return make_candles(rows)


def test_daily_comparison_label_thresholds():
    assert _daily_comparison_label(75.0) == "Much Higher"
    assert _daily_comparison_label(20.0) == "Higher"
    assert _daily_comparison_label(0.0) == "Similar"
    assert _daily_comparison_label(-20.0) == "Lower"
    assert _daily_comparison_label(-75.0) == "Much Lower"


def test_compute_daily_volume_trend_chain_and_pct_change():
    base = date(2026, 7, 1)
    today_date = base + timedelta(days=5)
    today_df = _make_day(today_date.isoformat(), [140, 140, 140, 140, 140])  # cumulative 700 at elapsed=4min

    historical_by_date = {
        base + timedelta(days=4): _make_day((base + timedelta(days=4)).isoformat(), [80] * 5),  # 400
        base + timedelta(days=3): _make_day((base + timedelta(days=3)).isoformat(), [90] * 5),  # 450
        base + timedelta(days=2): _make_day((base + timedelta(days=2)).isoformat(), [100] * 5),  # 500
        base + timedelta(days=1): _make_day((base + timedelta(days=1)).isoformat(), [100] * 5),  # 500
        base: _make_day(base.isoformat(), [100] * 5),  # 500
    }

    result = compute_daily_volume_trend(today_df, historical_by_date, n_days=5)

    assert result is not None
    assert len(result.days) == 5
    row0 = result.days[0]
    assert row0.session_date == today_date
    assert row0.volume_as_of == pytest.approx(700.0)
    assert row0.prior_day_volume_as_of == pytest.approx(400.0)
    assert row0.pct_change == pytest.approx(75.0)
    assert row0.label == "Much Higher"
    assert "institutional participation" in row0.interpretation.lower()


def test_compute_daily_volume_trend_no_prior_days():
    today_date = date(2026, 7, 10)
    today_df = _make_day(today_date.isoformat(), [100, 100])

    result = compute_daily_volume_trend(today_df, {}, n_days=5)

    assert result is not None
    assert result.days == []


def test_compute_daily_volume_trend_limits_to_n_days():
    base = date(2026, 7, 1)
    today_date = base + timedelta(days=10)
    today_df = _make_day(today_date.isoformat(), [100, 100])
    historical_by_date = {base + timedelta(days=i): _make_day((base + timedelta(days=i)).isoformat(), [100, 100]) for i in range(10)}

    result = compute_daily_volume_trend(today_df, historical_by_date, n_days=3)

    assert len(result.days) == 3


def test_compute_daily_volume_trend_empty_today_returns_none():
    assert compute_daily_volume_trend(make_candles([]), {}) is None
