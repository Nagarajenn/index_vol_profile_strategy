import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import pytest

from analytics.breakout_boxes import detect_breakout_boxes


def _candles(rows: list[dict]) -> pd.DataFrame:
    times = pd.date_range("2026-07-01 09:15", periods=len(rows), freq="5min", tz="Asia/Kolkata")
    df = pd.DataFrame(rows)
    df.insert(0, "timestamp", times)
    return df


def test_consolidation_then_confirmed_upside_breakout():
    tight = {"open": 100, "high": 101, "low": 99, "close": 100, "volume": 50}
    rows = [dict(tight) for _ in range(7)]  # 7 tight bars: idx 0-6
    rows.append({"open": 100, "high": 110, "low": 100, "close": 109, "volume": 500})  # idx 7: breakout
    candles = _candles(rows)

    boxes = detect_breakout_boxes(candles, window=4, compression_threshold=2.0, volume_mult=1.5)

    assert len(boxes) == 1
    box = boxes[0]
    assert box.p_low == pytest.approx(99)
    assert box.p_high == pytest.approx(101)
    assert box.status == "confirmed_up"
    assert box.t_end == candles["timestamp"].iloc[7]


def test_consolidation_with_no_breakout_stays_forming():
    tight = {"open": 100, "high": 101, "low": 99, "close": 100, "volume": 50}
    rows = [dict(tight) for _ in range(6)]
    candles = _candles(rows)

    boxes = detect_breakout_boxes(candles, window=4, compression_threshold=2.0, volume_mult=1.5)

    assert len(boxes) == 1
    assert boxes[0].status == "forming"


def test_no_boxes_when_series_shorter_than_window():
    tight = {"open": 100, "high": 101, "low": 99, "close": 100, "volume": 50}
    candles = _candles([dict(tight) for _ in range(3)])

    boxes = detect_breakout_boxes(candles, window=4)
    assert boxes == []
