import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from analytics.volume_profile import compute_volume_profile
from tests.fixtures.synthetic_candles import flat_candle, make_candles


def test_empty_candles_returns_none():
    empty = make_candles([])
    assert compute_volume_profile(empty, bin_size=1) is None


def test_poc_and_value_area_on_single_price_candles():
    # Five candles, each a single traded price (H=L=C), bin_size=1 so each
    # candle maps to exactly one bin -> hand-verifiable by construction.
    candles = make_candles(
        [
            flat_candle("09:15", 99, 2),
            flat_candle("09:20", 100, 5),
            flat_candle("09:25", 101, 20),  # highest volume -> POC
            flat_candle("09:30", 102, 10),
            flat_candle("09:35", 103, 3),
        ]
    )
    result = compute_volume_profile(candles, bin_size=1, value_area_pct=0.70)

    assert result is not None
    assert result.total_volume == 40
    assert result.poc == pytest.approx(101.5)  # bin [101,102) midpoint

    # Greedy expansion from POC (20): next best neighbor is bin 102 (10) vs
    # bin 100 (5) -> adds bin 102 first, cumulative 30/40=75% >= 70%, stop.
    assert result.val == pytest.approx(101.0)
    assert result.vah == pytest.approx(103.0)
    assert result.value_area_volume == pytest.approx(30.0)


def test_spanning_candle_conserves_volume_and_peaks_near_close():
    candles = make_candles(
        [
            {"time": "09:15", "o": 100.0, "h": 102.9, "l": 100.0, "c": 101.5, "v": 30.0},
        ]
    )
    result = compute_volume_profile(candles, bin_size=1)

    assert result is not None
    total_distributed = sum(result.bins.values())
    assert total_distributed == pytest.approx(30.0, rel=1e-6)

    # The bin containing the close (101.5 -> bin [101,102)) should get the
    # largest share since the triangular kernel peaks there.
    peak_bin = max(result.bins, key=result.bins.get)
    assert peak_bin == 101
    assert result.poc == pytest.approx(101.5)


def test_zero_volume_candles_ignored():
    candles = make_candles(
        [
            flat_candle("09:15", 100, 0),
            flat_candle("09:20", 105, 10),
        ]
    )
    result = compute_volume_profile(candles, bin_size=1)
    assert result is not None
    assert result.total_volume == 10
    assert 100 not in result.bins
