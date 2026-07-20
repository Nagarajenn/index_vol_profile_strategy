import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import pytest

from analytics.swings import SwingPoint
from analytics.trendlines import fit_trendlines


def _candles(n: int, drift: float = 1.0) -> pd.DataFrame:
    times = pd.date_range("2026-07-01 09:15", periods=n, freq="5min", tz="Asia/Kolkata")
    closes = [100 + i * drift for i in range(n)]
    return pd.DataFrame(
        {
            "timestamp": times,
            "open": closes,
            "high": [c + 2 for c in closes],
            "low": [c - 15 for c in closes],
            "close": closes,
            "volume": [100.0] * n,
        }
    )


def test_up_trendline_fits_perfectly_aligned_swing_lows():
    candles = _candles(15)
    ts = candles["timestamp"]
    # slope=1.0, intercept=93: 93+1*2=95, 93+1*6=99, 93+1*10=103
    lows = [
        SwingPoint(ts.iloc[2], 95.0, "low", True),
        SwingPoint(ts.iloc[6], 99.0, "low", True),
        SwingPoint(ts.iloc[10], 103.0, "low", True),
    ]

    trendlines = fit_trendlines(lows, candles, min_r2=0.7, tolerance_pct=0.02)
    up_lines = [t for t in trendlines if t.direction == "up"]

    assert len(up_lines) == 1
    tl = up_lines[0]
    assert tl.r2 == pytest.approx(1.0, abs=1e-6)
    assert tl.touch_count == 3
    (t0, p0), (t1, p1) = tl.points
    assert t1 == ts.iloc[-1]
    assert p1 == pytest.approx(93.0 + 1.0 * (len(candles) - 1))


def test_down_trendline_fits_perfectly_aligned_swing_highs():
    candles = _candles(15, drift=-0.1)  # gently descending closes, well clear of the fitted resistance line
    ts = candles["timestamp"]
    # descending line: slope=-1.0, intercept=115: 115-1*2=113, 115-1*6=109, 115-1*10=105
    highs = [
        SwingPoint(ts.iloc[2], 113.0, "high", True),
        SwingPoint(ts.iloc[6], 109.0, "high", True),
        SwingPoint(ts.iloc[10], 105.0, "high", True),
    ]

    trendlines = fit_trendlines(highs, candles, min_r2=0.7, tolerance_pct=0.02)
    down_lines = [t for t in trendlines if t.direction == "down"]

    assert len(down_lines) == 1
    assert down_lines[0].r2 == pytest.approx(1.0, abs=1e-6)


def test_too_few_swing_points_yields_no_trendline():
    candles = _candles(15)
    ts = candles["timestamp"]
    lows = [SwingPoint(ts.iloc[2], 95.0, "low", True)]

    trendlines = fit_trendlines(lows, candles)
    assert trendlines == []
