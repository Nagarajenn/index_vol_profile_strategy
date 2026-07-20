import pandas as pd


def resample_to_interval(candles_1min: pd.DataFrame, minutes: int) -> pd.DataFrame:
    """Resample 1-min OHLCV candles up to a coarser interval (e.g. 5-min)."""
    if candles_1min.empty:
        return candles_1min.copy()

    indexed = candles_1min.set_index("timestamp")
    agg = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    if "open_interest" in indexed.columns:
        agg["open_interest"] = "last"

    resampled = indexed.resample(f"{minutes}min", label="left", closed="left").agg(agg)
    resampled = resampled.dropna(subset=["open"])
    return resampled.reset_index()


def resample_series_last(series: pd.Series, timestamps: pd.Series, minutes: int) -> pd.Series:
    """Downsample a per-1-min series (e.g. cumulative VWAP) to the last value
    observed within each coarser bucket, aligned the same way as
    resample_to_interval so it can be plotted against the resampled candles.
    """
    tmp = pd.DataFrame(
        {
            "timestamp": timestamps.reset_index(drop=True),
            "value": series.reset_index(drop=True),
        }
    ).set_index("timestamp")
    resampled = tmp.resample(f"{minutes}min", label="left", closed="left").last()
    return resampled["value"].dropna()
