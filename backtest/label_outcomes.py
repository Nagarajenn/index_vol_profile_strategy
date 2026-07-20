from datetime import date

import pandas as pd

from dhan_client.client import fetch_intraday_candles

DEFAULT_HORIZONS_MIN = [15, 30, 60]


def label_outcomes(df: pd.DataFrame, symbol: str, horizons_min: list[int] = DEFAULT_HORIZONS_MIN) -> pd.DataFrame:
    """For each snapshot row, look up the actual price `h` minutes later and
    label whether the snapshot's stated trend direction was subsequently
    correct. Re-fetches each distinct day's 1-min candles once (not once per
    checkpoint) to keep this cheap even across thousands of rows.
    """
    if df.empty:
        return df

    df = df.copy()
    df["date_parsed"] = pd.to_datetime(df["as_of"]).dt.date
    for h in horizons_min:
        df[f"fwd_return_{h}m"] = float("nan")
        df[f"trend_correct_{h}m"] = pd.array([None] * len(df), dtype="object")

    candle_cache: dict[date, pd.DataFrame] = {}

    for d, group in df.groupby("date_parsed"):
        if d not in candle_cache:
            candle_cache[d] = fetch_intraday_candles(symbol, d, d, interval=1).set_index("timestamp").sort_index()
        day_candles = candle_cache[d]
        if day_candles.empty:
            continue

        for idx, row in group.iterrows():
            as_of = pd.Timestamp(row["as_of"])
            predicted_dir = 1 if row["trend_score"] > 0 else (-1 if row["trend_score"] < 0 else 0)

            for h in horizons_min:
                target_time = as_of + pd.Timedelta(minutes=h)
                future = day_candles[day_candles.index >= target_time]
                if future.empty:
                    continue
                future_price = future["close"].iloc[0]
                fwd_return = (future_price - row["close"]) / row["close"]
                df.loc[idx, f"fwd_return_{h}m"] = fwd_return
                if predicted_dir != 0:
                    actual_dir = 1 if fwd_return > 0 else (-1 if fwd_return < 0 else 0)
                    df.loc[idx, f"trend_correct_{h}m"] = predicted_dir == actual_dir

    return df
