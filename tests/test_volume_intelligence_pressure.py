import pandas as pd
import pytest

from analytics.volume_intelligence.pressure import (
    _momentum_label,
    compute_buy_sell_dominance,
    compute_cumulative_pressure,
    compute_volume_momentum,
)
from analytics.volume_intelligence.proxy import attach_buy_sell_columns
from tests.fixtures.synthetic_candles import make_candles


def _mfm_candle(time: str, sign: int, volume: float) -> dict:
    if sign > 0:  # close at the high -> mfm = 1.0
        return {"time": time, "o": 100, "h": 110, "l": 90, "c": 110, "v": volume}
    if sign < 0:  # close at the low -> mfm = -1.0
        return {"time": time, "o": 100, "h": 110, "l": 90, "c": 90, "v": volume}
    return {"time": time, "o": 100, "h": 100, "l": 100, "c": 100, "v": volume}  # flat -> mfm = 0.0


def _enriched(signs_and_volumes: list[tuple[int, float]]) -> pd.DataFrame:
    rows = []
    for i, (sign, vol) in enumerate(signs_and_volumes):
        minute = 15 + i
        hh = 9 + minute // 60
        mm = minute % 60
        rows.append(_mfm_candle(f"{hh:02d}:{mm:02d}", sign, vol))
    return attach_buy_sell_columns(make_candles(rows))


def test_dominance_buy_dominant_with_full_streak():
    enriched = _enriched([(1, 100)] * 8)
    result = compute_buy_sell_dominance(enriched)
    assert result.dominant_side == "buy"
    assert result.dominance_ratio == pytest.approx(1.0)
    assert result.consecutive_dominant_minutes == 8


def test_dominance_sell_dominant_with_full_streak():
    enriched = _enriched([(-1, 100)] * 8)
    result = compute_buy_sell_dominance(enriched)
    assert result.dominant_side == "sell"
    assert result.dominance_ratio == pytest.approx(0.0)
    assert result.consecutive_dominant_minutes == 8


def test_dominance_balanced_when_evenly_split():
    enriched = _enriched([(-1, 100)] * 4 + [(1, 100)] * 4)
    result = compute_buy_sell_dominance(enriched)
    assert result.dominant_side == "balanced"
    assert result.dominance_ratio == pytest.approx(0.5)
    assert result.consecutive_dominant_minutes == 0


def test_dominance_streak_stops_at_first_mismatch():
    # 2 sell candles then 3 buy candles: buy=300, sell=200, ratio=0.6 -> buy dominant,
    # but the streak only counts the trailing 3 buy candles, not the leading sells.
    enriched = _enriched([(-1, 100), (-1, 100), (1, 100), (1, 100), (1, 100)])
    result = compute_buy_sell_dominance(enriched)
    assert result.dominant_side == "buy"
    assert result.consecutive_dominant_minutes == 3


def test_dominance_empty_defaults_to_balanced():
    result = compute_buy_sell_dominance(attach_buy_sell_columns(make_candles([])))
    assert result.dominant_side == "balanced"
    assert result.dominance_ratio == pytest.approx(0.5)
    assert result.window_minutes == 0


def test_cumulative_pressure_running_total():
    enriched = _enriched([(1, 100), (1, 100), (-1, 50)])
    result = compute_cumulative_pressure(enriched)
    assert result.cum_buy_volume == pytest.approx(200.0)
    assert result.cum_sell_volume == pytest.approx(50.0)
    assert result.net_pressure == pytest.approx(150.0)
    assert result.pressure_ratio == pytest.approx(200.0 / 250.0)


def test_momentum_strong_buy_on_sustained_buy_pressure():
    enriched = _enriched([(1, 100)] * 10)
    result = compute_volume_momentum(enriched)
    assert result.label == "Strong Buy Momentum"
    assert result.normalized_score == pytest.approx(1.0)
    assert result.streak_minutes == 10


def test_momentum_strong_sell_on_sustained_sell_pressure():
    enriched = _enriched([(-1, 100)] * 10)
    result = compute_volume_momentum(enriched)
    assert result.label == "Strong Sell Momentum"
    assert result.normalized_score == pytest.approx(-1.0)


def test_momentum_neutral_on_flat_candles():
    enriched = _enriched([(0, 100)] * 10)
    result = compute_volume_momentum(enriched)
    assert result.label == "Neutral"
    assert result.normalized_score == pytest.approx(0.0)
    assert result.streak_minutes == 0


def test_momentum_empty_defaults_to_neutral():
    result = compute_volume_momentum(attach_buy_sell_columns(make_candles([])))
    assert result.label == "Neutral"
    assert result.normalized_score == 0.0


def test_momentum_label_thresholds():
    assert _momentum_label(0.5, 6) == "Strong Buy Momentum"
    assert _momentum_label(0.5, 2) == "Buy Momentum"  # strong score but streak too short
    assert _momentum_label(0.2, 10) == "Buy Momentum"
    assert _momentum_label(0.05, 10) == "Neutral"
    assert _momentum_label(-0.2, 10) == "Sell Momentum"
    assert _momentum_label(-0.5, 6) == "Strong Sell Momentum"
