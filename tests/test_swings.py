import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from analytics.swings import detect_swings


def _candles_from_prices(prices: list[float]) -> pd.DataFrame:
    times = pd.date_range("2026-07-01 09:15", periods=len(prices), freq="5min", tz="Asia/Kolkata")
    return pd.DataFrame(
        {
            "timestamp": times,
            "open": prices,
            "high": prices,
            "low": prices,
            "close": prices,
            "volume": [100.0] * len(prices),
        }
    )


def test_detect_swings_finds_confirmed_pivots():
    # zigzag: rise to a peak (idx2=105), fall to a trough (idx6=97), rise to a peak (idx10=108)
    prices = [100, 102, 105, 103, 101, 99, 97, 99, 102, 105, 108, 106, 104]
    candles = _candles_from_prices(prices)

    swings = detect_swings(candles, lookback=2)
    confirmed = {(s.kind, round(s.price, 2)) for s in swings if s.confirmed}

    assert ("high", 105.0) in confirmed
    assert ("low", 97.0) in confirmed
    assert ("high", 108.0) in confirmed
    # A flat run (e.g. idx3/idx4 descending monotonically) shouldn't be flagged.
    assert ("high", 103.0) not in confirmed


def test_recent_bars_are_unconfirmed():
    # A local low right at the end of the series has no bars after it yet.
    prices = [100, 99, 98, 97, 96]
    candles = _candles_from_prices(prices)

    swings = detect_swings(candles, lookback=2)
    last_bar_swings = [s for s in swings if s.timestamp == candles["timestamp"].iloc[-1]]

    assert last_bar_swings, "expected the trailing bar to be flagged as a provisional swing"
    assert all(not s.confirmed for s in last_bar_swings)
