import pytest

from analytics.volume_intelligence.models import VolumeSpike
from analytics.volume_intelligence.patterns import compute_absorption, compute_exhaustion
from analytics.volume_intelligence.proxy import attach_buy_sell_columns
from tests.fixtures.synthetic_candles import make_candles


def test_absorption_detected_with_spike_and_small_range():
    rows = [{"time": f"09:{15+i:02d}", "o": 100, "h": 105, "l": 95, "c": 100, "v": 100} for i in range(10)]
    rows.append({"time": "09:25", "o": 100, "h": 102, "l": 97, "c": 101, "v": 500})
    enriched = attach_buy_sell_columns(make_candles(rows))
    spike = VolumeSpike(is_spike=True, multiple=5.0, baseline_source="historical_20d", baseline_volume=100.0)

    result = compute_absorption(enriched, spike)

    assert result.detected is True
    assert result.range_ratio == pytest.approx(0.5)  # current range 5 vs prior avg range 10


def test_absorption_not_detected_when_range_not_compressed():
    rows = [{"time": f"09:{15+i:02d}", "o": 100, "h": 105, "l": 95, "c": 100, "v": 100} for i in range(10)]
    rows.append({"time": "09:25", "o": 100, "h": 110, "l": 90, "c": 100, "v": 500})  # range=20, ratio=2.0 -> not compressed
    enriched = attach_buy_sell_columns(make_candles(rows))
    spike = VolumeSpike(is_spike=True, multiple=5.0, baseline_source="historical_20d", baseline_volume=100.0)

    result = compute_absorption(enriched, spike)

    assert result.detected is False


def test_absorption_insufficient_history_returns_not_detected():
    rows = [{"time": "09:15", "o": 100, "h": 102, "l": 98, "c": 100, "v": 100}]
    enriched = attach_buy_sell_columns(make_candles(rows))
    spike = VolumeSpike(is_spike=False, multiple=None, baseline_source=None, baseline_volume=None)

    result = compute_absorption(enriched, spike)

    assert result.detected is False
    assert result.side_hint == "undetermined"


def test_exhaustion_detected_on_climactic_upmove_with_rejection():
    rows = []
    price = 100
    for i in range(9):
        price += 5
        rows.append({"time": f"09:{15+i:02d}", "o": price - 5, "h": price + 1, "l": price - 5, "c": price, "v": 100})
    rows.append({"time": "09:24", "o": price, "h": price + 20, "l": price, "c": price + 2, "v": 2000})  # climax + rejection wick
    enriched = attach_buy_sell_columns(make_candles(rows))
    spike = VolumeSpike(is_spike=True, multiple=20.0, baseline_source="historical_20d", baseline_volume=100.0)

    result = compute_exhaustion(enriched, spike)

    assert result.detected is True
    assert result.direction == "up"


def test_exhaustion_not_detected_without_volume_climax():
    rows = []
    price = 100
    for i in range(9):
        price += 5
        rows.append({"time": f"09:{15+i:02d}", "o": price - 5, "h": price + 1, "l": price - 5, "c": price, "v": 2000})
    rows.append({"time": "09:24", "o": price, "h": price + 20, "l": price, "c": price + 2, "v": 100})  # not a volume peak
    enriched = attach_buy_sell_columns(make_candles(rows))
    spike = VolumeSpike(is_spike=False, multiple=0.05, baseline_source="historical_20d", baseline_volume=2000.0)

    result = compute_exhaustion(enriched, spike)

    assert result.detected is False


def test_exhaustion_insufficient_history_returns_not_detected():
    rows = [{"time": "09:15", "o": 100, "h": 102, "l": 98, "c": 100, "v": 100}]
    enriched = attach_buy_sell_columns(make_candles(rows))
    spike = VolumeSpike(is_spike=False, multiple=None, baseline_source=None, baseline_volume=None)

    result = compute_exhaustion(enriched, spike)

    assert result.detected is False
    assert result.direction is None
