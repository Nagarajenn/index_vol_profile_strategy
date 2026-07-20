from datetime import date, datetime

import pandas as pd

from db.connection import fetch_all, fetch_one


def get_last_candle_timestamp(symbol: str) -> datetime | None:
    row = fetch_one("SELECT max(timestamp) FROM raw_candles WHERE symbol = %s", (symbol,))
    return row[0] if row and row[0] is not None else None


def get_last_chart_row(symbol: str, mode: str, session_date: date) -> dict | None:
    """Most recent row for `symbol`/`mode` on `session_date` that actually
    has a chart -- the baseline should_render_chart() compares against.
    Must be scoped to session_date: without it, the first live tick of a
    new session would compare against yesterday's stale chart row.
    """
    row = fetch_one(
        """
        SELECT as_of, trend_label, today_poc
        FROM levels_snapshots
        WHERE symbol = %s AND mode = %s AND chart_path IS NOT NULL AND as_of::date = %s
        ORDER BY as_of DESC LIMIT 1
        """,
        (symbol, mode, session_date),
    )
    if row is None:
        return None
    return {"as_of": row[0], "trend_label": row[1], "today_poc": row[2]}


_BACKTEST_COLUMNS = [
    "symbol", "as_of", "mode", "close", "trend_label", "trend_score", "confidence_score",
    "confidence_partial_data", "today_poc", "vwap_now", "support_low", "support_high",
    "resistance_low", "resistance_high", "institutional_bias_data",
    "sub_score_trend_alignment", "sub_score_vwap_position", "sub_score_structure_hh_hl",
    "sub_score_trendline_confluence", "sub_score_sr_proximity", "sub_score_breakout_confirmation",
    "sub_score_institutional_bias", "chart_path",
]


def load_levels_for_backtest(symbol: str, start_date: date | None = None, end_date: date | None = None) -> pd.DataFrame:
    """Replaces the old JSON-folder walk in backtest/load_snapshots.py with
    a query. Reconstructs a `confidence_sub_scores` dict column (dropping
    NaN keys) so it's a drop-in for backtest/tune_weights.py, which expects
    one dict of sub-scores per row.
    """
    conditions = ["symbol = %s"]
    params: list = [symbol]
    if start_date:
        conditions.append("as_of::date >= %s")
        params.append(start_date)
    if end_date:
        conditions.append("as_of::date <= %s")
        params.append(end_date)

    sql = f"SELECT {', '.join(_BACKTEST_COLUMNS)} FROM levels_snapshots WHERE {' AND '.join(conditions)} ORDER BY as_of"
    rows = fetch_all(sql, params)
    df = pd.DataFrame(rows, columns=_BACKTEST_COLUMNS)
    if df.empty:
        return df

    sub_cols = [c for c in _BACKTEST_COLUMNS if c.startswith("sub_score_")]
    df["confidence_sub_scores"] = df[sub_cols].apply(
        lambda r: {c.replace("sub_score_", ""): v for c, v in r.items() if pd.notna(v)}, axis=1
    )
    df = df.drop(columns=sub_cols)
    return df
