import pandas as pd
import pytest

from analytics.volume_intelligence.character import classify_volume_character, compute_volume_trend
from analytics.volume_intelligence.models import AbsorptionSignal, BuySellDominance, ExhaustionSignal, VolumeTrend
from analytics.volume_intelligence.proxy import attach_buy_sell_columns
from tests.fixtures.synthetic_candles import make_candles


def _volumes_trend(first_half_volume: float, second_half_volume: float) -> pd.DataFrame:
    rows = []
    for i in range(20):
        v = first_half_volume if i < 10 else second_half_volume
        rows.append({"time": f"09:{15+i:02d}", "o": 100, "h": 100, "l": 100, "c": 100, "v": v})
    return make_candles(rows)


def _candles_with_prices(prices: list[float], volume: float = 100) -> pd.DataFrame:
    rows = [{"time": f"09:{15+i:02d}", "o": p, "h": p, "l": p, "c": p, "v": volume} for i, p in enumerate(prices)]
    return attach_buy_sell_columns(make_candles(rows))


_NO_ABSORPTION = AbsorptionSignal(detected=False, range_ratio=None, volume_multiple=None, side_hint="undetermined")
_NO_EXHAUSTION = ExhaustionSignal(detected=False, direction=None, move_over_window=None, volume_multiple=None, wick_ratio=None)


def test_volume_trend_strong_increasing():
    result = compute_volume_trend(_volumes_trend(100, 140))
    assert result.pct_change == pytest.approx(40.0)
    assert result.label == "Strong Increasing"


def test_volume_trend_increasing():
    result = compute_volume_trend(_volumes_trend(100, 115))
    assert result.label == "Increasing"


def test_volume_trend_stable():
    result = compute_volume_trend(_volumes_trend(100, 105))
    assert result.label == "Stable"


def test_volume_trend_decreasing():
    result = compute_volume_trend(_volumes_trend(100, 85))
    assert result.label == "Decreasing"


def test_volume_trend_strong_decreasing():
    result = compute_volume_trend(_volumes_trend(100, 60))
    assert result.pct_change == pytest.approx(-40.0)
    assert result.label == "Strong Decreasing"


def test_volume_trend_insufficient_data_returns_none():
    short = _volumes_trend(100, 140).head(5)
    result = compute_volume_trend(short)
    assert result is None


def test_character_climactic_on_exhaustion():
    enriched = _candles_with_prices([100] * 20)
    exhaustion = ExhaustionSignal(detected=True, direction="up", move_over_window=50.0, volume_multiple=10.0, wick_ratio=0.5)
    dominance = BuySellDominance(window_minutes=8, buy_volume=0, sell_volume=0, dominance_ratio=0.5, dominant_side="balanced", consecutive_dominant_minutes=0)
    result = classify_volume_character(enriched, None, dominance, _NO_ABSORPTION, exhaustion)
    assert result.label == "Climactic"


def test_character_climactic_on_absorption():
    enriched = _candles_with_prices([100] * 20)
    absorption = AbsorptionSignal(detected=True, range_ratio=0.3, volume_multiple=4.0, side_hint="buy_absorption")
    dominance = BuySellDominance(window_minutes=8, buy_volume=0, sell_volume=0, dominance_ratio=0.5, dominant_side="balanced", consecutive_dominant_minutes=0)
    result = classify_volume_character(enriched, None, dominance, absorption, _NO_EXHAUSTION)
    assert result.label == "Climactic"


def test_character_accumulation():
    enriched = _candles_with_prices([100] * 20)  # flat price
    trend = VolumeTrend(window_minutes=20, pct_change=15.0, label="Increasing")
    dominance = BuySellDominance(window_minutes=8, buy_volume=800, sell_volume=200, dominance_ratio=0.8, dominant_side="buy", consecutive_dominant_minutes=6)
    result = classify_volume_character(enriched, trend, dominance, _NO_ABSORPTION, _NO_EXHAUSTION)
    assert result.label == "Accumulation"


def test_character_distribution():
    enriched = _candles_with_prices([100] * 20)  # flat price
    trend = VolumeTrend(window_minutes=20, pct_change=15.0, label="Increasing")
    dominance = BuySellDominance(window_minutes=8, buy_volume=200, sell_volume=800, dominance_ratio=0.2, dominant_side="sell", consecutive_dominant_minutes=6)
    result = classify_volume_character(enriched, trend, dominance, _NO_ABSORPTION, _NO_EXHAUSTION)
    assert result.label == "Distribution"


def test_character_markup():
    prices = [100 + i * 0.5 for i in range(20)]  # meaningfully up (~9.5%)
    enriched = _candles_with_prices(prices)
    trend = VolumeTrend(window_minutes=20, pct_change=5.0, label="Stable")
    dominance = BuySellDominance(window_minutes=8, buy_volume=800, sell_volume=200, dominance_ratio=0.8, dominant_side="buy", consecutive_dominant_minutes=6)
    result = classify_volume_character(enriched, trend, dominance, _NO_ABSORPTION, _NO_EXHAUSTION)
    assert result.label == "Markup"


def test_character_markdown():
    prices = [100 - i * 0.5 for i in range(20)]  # meaningfully down (~-9.5%)
    enriched = _candles_with_prices(prices)
    trend = VolumeTrend(window_minutes=20, pct_change=5.0, label="Stable")
    dominance = BuySellDominance(window_minutes=8, buy_volume=200, sell_volume=800, dominance_ratio=0.2, dominant_side="sell", consecutive_dominant_minutes=6)
    result = classify_volume_character(enriched, trend, dominance, _NO_ABSORPTION, _NO_EXHAUSTION)
    assert result.label == "Markdown"


def test_character_quiet_consolidation_fallback():
    enriched = _candles_with_prices([100] * 20)  # flat price
    trend = VolumeTrend(window_minutes=20, pct_change=0.0, label="Stable")
    dominance = BuySellDominance(window_minutes=8, buy_volume=500, sell_volume=500, dominance_ratio=0.5, dominant_side="balanced", consecutive_dominant_minutes=0)
    result = classify_volume_character(enriched, trend, dominance, _NO_ABSORPTION, _NO_EXHAUSTION)
    assert result.label == "Quiet-Consolidation"
