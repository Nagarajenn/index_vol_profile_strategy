"""Returns, realized volatility, ATR, gap-from-prior-close, and candle
body/wick ratios -- computed directly from already-truncated 1-min candles.
Reuses analytics.breakout_boxes.compute_atr rather than reimplementing True
Range.
"""

import pandas as pd

from analytics.breakout_boxes import compute_atr

from .models import PriceVolatilityFeatures

REALIZED_VOL_WINDOW_MINUTES = 20
RET_5M_LOOKBACK_BARS = 5
MIN_RETURNS_FOR_REALIZED_VOL = 5


def compute_price_volatility_features(
    today_candles: pd.DataFrame,
    prior_day_close: float | None,
    atr_period: int = 14,
) -> PriceVolatilityFeatures:
    """`today_candles` must already be truncated to the desired cutoff T
    (see quant_features.cutoff.truncate_candles) -- every value below is
    computed only from that DataFrame plus the already-closed prior day's
    close, never anything after T."""
    last = today_candles.iloc[-1]
    close = float(last["close"])
    closes = today_candles["close"]

    ret_1m = None
    if len(closes) >= 2 and closes.iloc[-2]:
        ret_1m = float((closes.iloc[-1] - closes.iloc[-2]) / closes.iloc[-2])

    ret_5m = None
    if len(closes) > RET_5M_LOOKBACK_BARS and closes.iloc[-1 - RET_5M_LOOKBACK_BARS]:
        ret_5m = float((closes.iloc[-1] - closes.iloc[-1 - RET_5M_LOOKBACK_BARS]) / closes.iloc[-1 - RET_5M_LOOKBACK_BARS])

    tail_returns = closes.pct_change().dropna().tail(REALIZED_VOL_WINDOW_MINUTES)
    realized_vol_20m = float(tail_returns.std()) if len(tail_returns) >= MIN_RETURNS_FOR_REALIZED_VOL else None

    atr_series = compute_atr(today_candles, period=atr_period)
    atr_14 = float(atr_series.iloc[-1]) if len(atr_series) else None

    gap_open_pct = None
    if prior_day_close:
        open_price = float(today_candles["open"].iloc[0])
        gap_open_pct = (open_price - prior_day_close) / prior_day_close

    body_pct = upper_wick_pct = lower_wick_pct = None
    rng = float(last["high"] - last["low"])
    if rng > 0:
        o, c, h, l = float(last["open"]), close, float(last["high"]), float(last["low"])
        body_pct = abs(c - o) / rng
        upper_wick_pct = (h - max(o, c)) / rng
        lower_wick_pct = (min(o, c) - l) / rng

    return PriceVolatilityFeatures(
        close=close,
        ret_1m=ret_1m,
        ret_5m=ret_5m,
        realized_vol_20m=realized_vol_20m,
        atr_14=atr_14,
        gap_open_pct=gap_open_pct,
        body_pct=body_pct,
        upper_wick_pct=upper_wick_pct,
        lower_wick_pct=lower_wick_pct,
    )
