from datetime import date

import pytest

from analytics.volume_intelligence.intervals import compute_significant_intervals
from tests.fixtures.synthetic_candles import make_candles


def _bucket_rows(start_minute: int, closes: list[float], volumes: list[float], lean: str = "flat", date_str: str | None = None) -> list[dict]:
    rows = []
    for i, (c, v) in enumerate(zip(closes, volumes)):
        minute = start_minute + i
        hh = 9 + minute // 60
        mm = minute % 60
        if lean == "buy":
            o, h, l = c - 1, c, c - 1  # close at the high
        elif lean == "sell":
            o, h, l = c + 1, c + 1, c  # close at the low
        else:
            o, h, l = c, c, c
        row = {"time": f"{hh:02d}:{mm:02d}", "o": o, "h": h, "l": l, "c": c, "v": v}
        if date_str:
            row["date"] = date_str
        rows.append(row)
    return rows


def _flat_historical(n_days: int, bucket0_close: float = 100, bucket0_volume: float = 100, bucket1_volume: float = 100) -> dict:
    historical = {}
    for d in range(1, n_days + 1):
        date_str = f"2026-06-{d:02d}"
        rows = _bucket_rows(15, [bucket0_close] * 5, [bucket0_volume] * 5, date_str=date_str)
        rows += _bucket_rows(20, [bucket0_close] * 5, [bucket1_volume] * 5, date_str=date_str)
        historical[date(2026, 6, d)] = make_candles(rows)
    return historical


def test_significant_interval_detected_and_flagged():
    today_rows = _bucket_rows(15, [100, 101, 102, 103, 104], [500] * 5, lean="buy")  # bucket 0: surge, buy-leaning, rising
    today_rows += _bucket_rows(20, [104] * 5, [100] * 5, lean="flat")  # bucket 1: normal
    today_df = make_candles(today_rows)
    historical_by_date = _flat_historical(4)  # baseline volume 100/candle -> 500/bucket

    results = compute_significant_intervals(today_df, historical_by_date)

    assert len(results) == 1
    assert results[0].multiple == pytest.approx(5.0)  # 2500 / 500
    assert results[0].dominant_side == "buy"
    assert results[0].price_direction == "up"
    assert "institutional" in results[0].institutional_note.lower()
    assert "continuation" in results[0].trend_note.lower()


def test_significant_interval_none_when_volume_normal():
    today_rows = _bucket_rows(15, [100] * 5, [100] * 5, lean="flat")
    today_df = make_candles(today_rows)
    historical_by_date = _flat_historical(4)

    assert compute_significant_intervals(today_df, historical_by_date) == []


def test_significant_interval_insufficient_baseline_days_excluded():
    today_rows = _bucket_rows(15, [100] * 5, [500] * 5, lean="flat")
    today_df = make_candles(today_rows)
    historical_by_date = _flat_historical(1)  # below MIN_BASELINE_DAYS_FOR_BUCKET

    assert compute_significant_intervals(today_df, historical_by_date) == []


def test_significant_interval_empty_today_returns_empty_list():
    assert compute_significant_intervals(make_candles([]), {}) == []


def test_trend_note_flags_divergence_when_price_and_dominance_disagree():
    # sell-leaning candles (each closes at its own low) but the bucket's
    # overall price rose -- a genuine divergence.
    today_rows = _bucket_rows(15, [100, 101, 102, 103, 104], [500] * 5, lean="sell")
    today_df = make_candles(today_rows)
    historical_by_date = _flat_historical(4)

    results = compute_significant_intervals(today_df, historical_by_date)

    assert len(results) == 1
    assert results[0].dominant_side == "sell"
    assert results[0].price_direction == "up"
    assert "divergence" in results[0].trend_note.lower()
