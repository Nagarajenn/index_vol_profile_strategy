from datetime import date

import pandas as pd
import pytest

from analytics.volume_intelligence.models import BaselineReading
from analytics.volume_intelligence.similarity import compute_historical_similarity
from tests.fixtures.synthetic_candles import make_candles


def _day_candles(date_str: str, closes_pattern: str, volumes: list[float]) -> pd.DataFrame:
    """closes_pattern: 'buy' -> each candle closes at the high (mfm=1),
    'sell' -> closes at the low (mfm=-1), 'flat' -> o=h=l=c."""
    rows = []
    for i, v in enumerate(volumes):
        minute = 15 + i
        hh = 9 + minute // 60
        mm = minute % 60
        time_str = f"{hh:02d}:{mm:02d}"
        if closes_pattern == "buy":
            row = {"time": time_str, "o": 100, "h": 110, "l": 90, "c": 110, "v": v, "date": date_str}
        elif closes_pattern == "sell":
            row = {"time": time_str, "o": 100, "h": 110, "l": 90, "c": 90, "v": v, "date": date_str}
        else:
            row = {"time": time_str, "o": 100, "h": 100, "l": 100, "c": 100, "v": v, "date": date_str}
        rows.append(row)
    return make_candles(rows)


def test_identical_curves_give_similarity_near_one():
    today = _day_candles("2026-08-10", "buy", [100] * 10)
    historical = {date(2026, 7, d): _day_candles(f"2026-07-{d:02d}", "buy", [100] * 10) for d in range(1, 6)}

    result = compute_historical_similarity(today, historical)

    assert result.n_days_compared == 5
    assert result.top_days[0].similarity == pytest.approx(1.0, abs=1e-6)


def test_top_days_ranked_by_distance():
    today = _day_candles("2026-08-10", "buy", [100] * 10)
    historical = {
        date(2026, 7, 1): _day_candles("2026-07-01", "buy", [100] * 10),  # closest
        date(2026, 7, 2): _day_candles("2026-07-02", "sell", [100] * 10),
        date(2026, 7, 3): _day_candles("2026-07-03", "sell", [100] * 10),
        date(2026, 7, 4): _day_candles("2026-07-04", "sell", [100] * 10),
        date(2026, 7, 5): _day_candles("2026-07-05", "sell", [100] * 10),
    }

    result = compute_historical_similarity(today, historical)

    assert result.top_days[0].session_date == date(2026, 7, 1)
    assert result.top_days[0].similarity > result.top_days[1].similarity


def test_insufficient_days_returns_empty():
    today = _day_candles("2026-08-10", "buy", [100] * 10)
    historical = {
        date(2026, 7, 1): _day_candles("2026-07-01", "buy", [100] * 10),
        date(2026, 7, 2): _day_candles("2026-07-02", "buy", [100] * 10),
    }

    result = compute_historical_similarity(today, historical)

    assert result.top_days == []
    assert result.resemblance_label is None
    assert result.n_days_compared == 2


def test_resemblance_label_majority_buy_gives_accumulation_like():
    today = _day_candles("2026-08-10", "buy", [100] * 10)
    historical = {
        date(2026, 7, 1): _day_candles("2026-07-01", "buy", [100] * 10),
        date(2026, 7, 2): _day_candles("2026-07-02", "buy", [100] * 10),
        date(2026, 7, 3): _day_candles("2026-07-03", "buy", [100] * 10),
        date(2026, 7, 4): _day_candles("2026-07-04", "sell", [100] * 10),
        date(2026, 7, 5): _day_candles("2026-07-05", "sell", [100] * 10),
    }

    result = compute_historical_similarity(today, historical)

    assert result.resemblance_label == "accumulation-like sessions"


def test_elapsed_minutes_too_small_returns_empty():
    today = _day_candles("2026-08-10", "buy", [100] * 3)  # ~2 minutes elapsed, below MIN_ELAPSED_MINUTES
    historical = {date(2026, 7, d): _day_candles(f"2026-07-{d:02d}", "buy", [100] * 10) for d in range(1, 6)}

    result = compute_historical_similarity(today, historical)

    assert result.n_days_compared == 0
    assert result.top_days == []


def test_total_volume_ratio_uses_baseline_when_provided():
    today = _day_candles("2026-08-10", "buy", [100] * 10)
    historical = {date(2026, 7, d): _day_candles(f"2026-07-{d:02d}", "buy", [100] * 10) for d in range(1, 6)}
    baseline = BaselineReading(group="last_20_days", elapsed_minutes=9, interval_avg_volume=100.0, cumulative_avg_volume=500.0, sample_days=10)

    result = compute_historical_similarity(today, historical, rvol_20d_baseline=baseline)

    assert result.top_days[0].total_volume_ratio == pytest.approx(2.0)  # 1000 cum volume / 500 baseline
