import pandas as pd


def compute_vwap(candles: pd.DataFrame) -> pd.Series:
    """Session-resetting intraday VWAP from OHLCV candles.

    `candles` must be sorted by timestamp and have tz-aware `timestamp`,
    `high`, `low`, `close`, `volume` columns. Returns a Series aligned to
    `candles.index` with the cumulative VWAP as of each candle's close,
    resetting at each new session (calendar date in Asia/Kolkata).
    """
    typical_price = (candles["high"] + candles["low"] + candles["close"]) / 3
    session_date = candles["timestamp"].dt.date

    tpv = typical_price * candles["volume"]
    cum_tpv = tpv.groupby(session_date).cumsum()
    cum_vol = candles["volume"].groupby(session_date).cumsum()

    return cum_tpv / cum_vol
