from dataclasses import dataclass

import pandas as pd

from analytics.swings import SwingPoint
from config.instruments import EMA_TREND_PERIOD

VWAP_DEADBAND_PCT = 0.0005
EMA_SLOPE_DEADBAND_PCT = 0.0005
EMA_SLOPE_LOOKBACK_BARS = 5

LABELS = {
    -3: "Strong Bearish",
    -2: "Strong Bearish",
    -1: "Bearish",
    0: "Neutral",
    1: "Bullish",
    2: "Strong Bullish",
    3: "Strong Bullish",
}


@dataclass
class TrendResult:
    label: str
    score: int  # -3..3
    price_vs_vwap: int
    ema_slope: int
    structure: int


def _structure_score(swings: list[SwingPoint]) -> int:
    highs = [s.price for s in swings if s.kind == "high" and s.confirmed]
    lows = [s.price for s in swings if s.kind == "low" and s.confirmed]
    if len(highs) < 2 or len(lows) < 2:
        return 0
    higher_high, higher_low = highs[-1] > highs[-2], lows[-1] > lows[-2]
    lower_high, lower_low = highs[-1] < highs[-2], lows[-1] < lows[-2]
    if higher_high and higher_low:
        return 1
    if lower_high and lower_low:
        return -1
    return 0


def classify_trend(
    candles: pd.DataFrame,
    vwap_now: float,
    swings: list[SwingPoint],
    ema_period: int = EMA_TREND_PERIOD,
) -> TrendResult:
    close = candles["close"].iloc[-1]

    price_vs_vwap = 0
    if vwap_now:
        diff_pct = (close - vwap_now) / vwap_now
        if diff_pct > VWAP_DEADBAND_PCT:
            price_vs_vwap = 1
        elif diff_pct < -VWAP_DEADBAND_PCT:
            price_vs_vwap = -1

    ema = candles["close"].ewm(span=ema_period, adjust=False).mean()
    ema_slope = 0
    if len(ema) > EMA_SLOPE_LOOKBACK_BARS:
        slope_pct = (ema.iloc[-1] - ema.iloc[-1 - EMA_SLOPE_LOOKBACK_BARS]) / ema.iloc[-1 - EMA_SLOPE_LOOKBACK_BARS]
        if slope_pct > EMA_SLOPE_DEADBAND_PCT:
            ema_slope = 1
        elif slope_pct < -EMA_SLOPE_DEADBAND_PCT:
            ema_slope = -1

    structure = _structure_score(swings)

    score = price_vs_vwap + ema_slope + structure
    return TrendResult(label=LABELS[score], score=score, price_vs_vwap=price_vs_vwap, ema_slope=ema_slope, structure=structure)
