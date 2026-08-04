"""Chaikin-style buy/sell volume proxy. No tick/bid-ask data exists in this
pipeline (Dhan's REST API only provides 1-minute OHLCV), so per-candle
buy/sell volume is estimated from where the candle closed within its own
high-low range -- the same "estimate from OHLCV shape" spirit as
analytics/volume_profile.py's triangular-kernel price-bin distribution,
which exists for the identical reason (no tick data to place volume
exactly).
"""

import numpy as np
import pandas as pd


def attach_buy_sell_columns(candles: pd.DataFrame) -> pd.DataFrame:
    """Returns a copy of `candles` with three new columns:

    mfm (money flow multiplier) = ((close-low)-(high-close)) / (high-low),
    0.0 for a flat/single-price bar (high==low -- no directional information
    to attribute, since close==low==high in that case, giving a genuine 0/0
    that is defined here as 0 rather than left as NaN).

    buy_volume  = volume * max(mfm, 0)
    sell_volume = volume * max(-mfm, 0)

    Note buy_volume + sell_volume <= volume whenever the close isn't exactly
    at the high or low of the bar -- the shortfall is non-directional volume
    for that bar. This is a disclosed property of the proxy, not a bug.
    """
    df = candles.copy()
    if df.empty:
        df["mfm"] = pd.Series(dtype=float)
        df["buy_volume"] = pd.Series(dtype=float)
        df["sell_volume"] = pd.Series(dtype=float)
        return df

    rng = df["high"] - df["low"]
    numerator = (df["close"] - df["low"]) - (df["high"] - df["close"])
    with np.errstate(invalid="ignore", divide="ignore"):
        mfm = (numerator / rng).fillna(0.0)

    df["mfm"] = mfm
    df["buy_volume"] = df["volume"] * mfm.clip(lower=0)
    df["sell_volume"] = df["volume"] * (-mfm).clip(lower=0)
    return df
