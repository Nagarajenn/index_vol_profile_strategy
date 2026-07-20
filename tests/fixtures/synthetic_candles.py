import pandas as pd


def make_candles(rows: list[dict], tz_date: str = "2026-07-01") -> pd.DataFrame:
    """Build a minimal OHLCV DataFrame from rows of {time, o, h, l, c, v}.

    `time` is an "HH:MM" string on `tz_date` (Asia/Kolkata). If a row carries
    its own `date` key, that overrides `tz_date` for that row (for
    multi-session tests).
    """
    columns = ["timestamp", "open", "high", "low", "close", "volume"]
    if not rows:
        return pd.DataFrame(columns=columns)

    records = []
    for r in rows:
        d = r.get("date", tz_date)
        ts = pd.Timestamp(f"{d} {r['time']}", tz="Asia/Kolkata")
        records.append(
            {
                "timestamp": ts,
                "open": r["o"],
                "high": r["h"],
                "low": r["l"],
                "close": r["c"],
                "volume": r["v"],
            }
        )
    return pd.DataFrame(records, columns=columns).sort_values("timestamp").reset_index(drop=True)


def flat_candle(time: str, price: float, volume: float, date: str | None = None) -> dict:
    """A candle where O=H=L=C=price (a single traded price for the bar)."""
    row = {"time": time, "o": price, "h": price, "l": price, "c": price, "v": volume}
    if date:
        row["date"] = date
    return row
