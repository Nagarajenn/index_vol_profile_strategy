from dataclasses import dataclass

import numpy as np
import pandas as pd

from config.instruments import (
    ATR_PERIOD,
    COMPRESSION_ATR_THRESHOLD,
    CONSOLIDATION_WINDOW_BARS,
    VOLUME_BREAKOUT_MULTIPLIER,
)


@dataclass
class BreakoutBox:
    t_start: pd.Timestamp
    t_end: pd.Timestamp
    p_low: float
    p_high: float
    status: str  # "forming", "confirmed_up", "confirmed_down"
    avg_volume: float


def compute_atr(candles: pd.DataFrame, period: int = ATR_PERIOD) -> pd.Series:
    high, low, close = candles["high"], candles["low"], candles["close"]
    prev_close = close.shift(1)
    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    return tr.rolling(period, min_periods=1).mean()


def detect_breakout_boxes(
    candles: pd.DataFrame,
    window: int = CONSOLIDATION_WINDOW_BARS,
    atr_period: int = ATR_PERIOD,
    compression_threshold: float = COMPRESSION_ATR_THRESHOLD,
    volume_mult: float = VOLUME_BREAKOUT_MULTIPLIER,
) -> list[BreakoutBox]:
    """Flags rolling `window`-bar ranges compressed relative to ATR as
    consolidation boxes, then scans forward for a close beyond the box edge
    on above-average volume to confirm a breakout direction.
    """
    n = len(candles)
    if n < window:
        return []

    atr = compute_atr(candles, atr_period).to_numpy()
    highs = candles["high"].to_numpy()
    lows = candles["low"].to_numpy()
    closes = candles["close"].to_numpy()
    volumes = candles["volume"].to_numpy()
    timestamps = candles["timestamp"].to_numpy()

    is_compressed = np.zeros(n, dtype=bool)
    for i in range(window - 1, n):
        w_high = highs[i - window + 1 : i + 1].max()
        w_low = lows[i - window + 1 : i + 1].min()
        a = atr[i]
        if a and a > 0:
            is_compressed[i] = (w_high - w_low) / a <= compression_threshold

    boxes: list[BreakoutBox] = []
    i = window - 1
    while i < n:
        if not is_compressed[i]:
            i += 1
            continue

        run_start = i
        while i < n and is_compressed[i]:
            i += 1
        run_end = i - 1

        box_start_idx = run_start - window + 1
        p_low = lows[box_start_idx : run_end + 1].min()
        p_high = highs[box_start_idx : run_end + 1].max()
        avg_vol = volumes[box_start_idx : run_end + 1].mean()
        t_start = pd.Timestamp(timestamps[box_start_idx])
        t_end = pd.Timestamp(timestamps[run_end])

        status = "forming"
        for j in range(run_end + 1, n):
            if closes[j] > p_high and volumes[j] > volume_mult * avg_vol:
                status = "confirmed_up"
                t_end = pd.Timestamp(timestamps[j])
                break
            if closes[j] < p_low and volumes[j] > volume_mult * avg_vol:
                status = "confirmed_down"
                t_end = pd.Timestamp(timestamps[j])
                break

        boxes.append(
            BreakoutBox(t_start=t_start, t_end=t_end, p_low=float(p_low), p_high=float(p_high), status=status, avg_volume=float(avg_vol))
        )

    return boxes
