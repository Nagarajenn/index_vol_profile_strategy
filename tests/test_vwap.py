import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from analytics.vwap import compute_vwap
from tests.fixtures.synthetic_candles import flat_candle, make_candles


def test_vwap_single_session_matches_hand_calc():
    candles = make_candles(
        [
            flat_candle("09:15", 100, 10),
            flat_candle("09:20", 102, 20),
            flat_candle("09:25", 101, 10),
        ]
    )
    vwap = compute_vwap(candles)

    assert vwap.iloc[0] == 100.0
    assert vwap.iloc[1] == (100 * 10 + 102 * 20) / 30
    assert vwap.iloc[2] == (100 * 10 + 102 * 20 + 101 * 10) / 40


def test_vwap_resets_on_new_session():
    candles = make_candles(
        [
            flat_candle("09:15", 100, 10, date="2026-07-01"),
            flat_candle("15:25", 200, 50, date="2026-07-01"),
            flat_candle("09:15", 50, 5, date="2026-07-02"),
        ]
    )
    vwap = compute_vwap(candles)

    # Second day's first bar must not carry over day one's cumulative VWAP.
    assert vwap.iloc[2] == 50.0
