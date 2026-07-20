from dataclasses import dataclass

import pandas as pd

from config.instruments import SWING_LOOKBACK_BARS


@dataclass
class SwingPoint:
    timestamp: pd.Timestamp
    price: float
    kind: str  # "high" or "low"
    confirmed: bool


def detect_swings(candles: pd.DataFrame, lookback: int = SWING_LOOKBACK_BARS) -> list[SwingPoint]:
    """Fractal swing high/low detection: bar i is a swing high if its high
    exceeds the highs of `lookback` bars on both sides (swing low mirrors on
    lows). The most recent `lookback` bars don't yet have enough bars after
    them to be fully confirmed — they're still returned (so a forming swing
    shows up promptly) but flagged `confirmed=False` until enough bars land.
    """
    highs = candles["high"].to_numpy()
    lows = candles["low"].to_numpy()
    timestamps = candles["timestamp"].to_numpy()
    n = len(candles)

    swings: list[SwingPoint] = []
    for i in range(lookback, n):
        left_hi = highs[i - lookback : i]
        left_lo = lows[i - lookback : i]
        right_hi = highs[i + 1 : i + 1 + lookback]
        right_lo = lows[i + 1 : i + 1 + lookback]
        confirmed = len(right_hi) == lookback

        is_swing_high = highs[i] > left_hi.max() and (len(right_hi) == 0 or highs[i] > right_hi.max())
        is_swing_low = lows[i] < left_lo.min() and (len(right_lo) == 0 or lows[i] < right_lo.min())

        if is_swing_high:
            swings.append(SwingPoint(pd.Timestamp(timestamps[i]), float(highs[i]), "high", confirmed))
        if is_swing_low:
            swings.append(SwingPoint(pd.Timestamp(timestamps[i]), float(lows[i]), "low", confirmed))

    return swings
