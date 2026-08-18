"""Forward-outcome labeling engine -- the strict "future data only" half of
the feature store. Every value here is computed from
`today_candles.iloc[t_index + 1:]` alone, additionally bounded to the SAME
calendar day as `t_index`'s own row; nothing at-or-before t_index, and
nothing from a different trading day, is ever read for a return/MFE/MAE/
label computation. This is the mirror image of quant_features.cutoff's
"never look past T" guard -- this module enforces "never look at or before
T, and never past this same session's close" -- and, like cutoff.py, does
so mechanically inside the module itself rather than trusting the caller to
have pre-sliced the input correctly, so a caller mistake (e.g. passing
multi-day candles) can't silently leak a next-day price into a horizon.

Labels are volatility-adjusted: a forward move only counts as "Up"/"Down"
once it clears LABEL_ATR_THRESHOLD multiples of `atr_at_t` (computed
as-of T by price_features.py, passed in here) -- a fixed percentage
threshold would call a 0.3% move "big" on a quiet day and "small" on a
volatile one; normalizing by ATR keeps the threshold meaningful across
regimes. LABEL_ATR_THRESHOLD is a documented starting default, tunable
later -- the same "heuristic, not a fitted model" stance used throughout
VIE/MTI.
"""

from datetime import datetime, timedelta

import pandas as pd

from .models import DirectionLabel, ForwardOutcomeRow

FORWARD_RETURN_HORIZONS_MINUTES = [1, 3, 5, 10, 15, 30]
MFE_MAE_HORIZONS_MINUTES = [1, 5, 15, 30]
LABEL_HORIZONS_MINUTES = [5, 15, 30]
LABEL_ATR_THRESHOLD = 0.5


def _forward_window(today_candles: pd.DataFrame, t_index: int, horizon_minutes: int) -> pd.DataFrame:
    """Rows strictly after t_index (never <=), bounded to the same calendar
    day as the entry row and to the requested horizon -- never crosses a
    session boundary even if `today_candles` happens to contain more than
    one day's rows.

    Returns an EMPTY frame if the session didn't actually extend far enough
    to reach `horizon_minutes` -- a horizon must be genuinely reached to be
    used, never approximated from whatever partial data happens to exist
    (the same "leave it NULL, don't fill from what's available" discipline
    applied to crossing a session boundary, applied here to falling short
    of the requested horizon within the session)."""
    entry_time = today_candles["timestamp"].iloc[t_index]
    session_date = entry_time.date()
    target_time = entry_time + timedelta(minutes=horizon_minutes)

    future = today_candles.iloc[t_index + 1 :]
    if future.empty:
        return future
    future = future[future["timestamp"].dt.date == session_date]
    if future.empty or future["timestamp"].iloc[-1] < target_time:
        return future.iloc[0:0]
    return future[future["timestamp"] <= target_time]


def _label(entry_close: float, horizon_close: float, atr_at_t: float | None) -> DirectionLabel | None:
    if atr_at_t is None or atr_at_t <= 0:
        return None
    move_in_atr = (horizon_close - entry_close) / atr_at_t
    if move_in_atr >= LABEL_ATR_THRESHOLD:
        return "Up"
    if move_in_atr <= -LABEL_ATR_THRESHOLD:
        return "Down"
    return "Flat"


def compute_forward_outcome_row(
    symbol: str,
    timestamp: datetime,
    feature_version: str,
    today_candles: pd.DataFrame,
    t_index: int,
    atr_at_t: float | None,
) -> ForwardOutcomeRow:
    """`today_candles` is expected to be exactly one trading day's 1-min
    candles ascending by timestamp, but `_forward_window`'s same-day filter
    makes this a defense-in-depth guarantee, not a trust assumption.
    `t_index` is the integer position of the row at `timestamp` within it."""
    entry_close = float(today_candles["close"].iloc[t_index])

    fwd_returns: dict[int, float | None] = {}
    truncated = False
    for h in FORWARD_RETURN_HORIZONS_MINUTES:
        window = _forward_window(today_candles, t_index, h)
        if window.empty:
            fwd_returns[h] = None
            truncated = True
            continue
        horizon_close = float(window["close"].iloc[-1])
        fwd_returns[h] = (horizon_close - entry_close) / entry_close

    mfe_mae: dict[int, tuple[float | None, float | None]] = {}
    for h in MFE_MAE_HORIZONS_MINUTES:
        window = _forward_window(today_candles, t_index, h)
        if window.empty:
            mfe_mae[h] = (None, None)
            continue
        mfe = (float(window["high"].max()) - entry_close) / entry_close
        mae = (float(window["low"].min()) - entry_close) / entry_close
        mfe_mae[h] = (mfe, mae)

    labels: dict[int, DirectionLabel | None] = {}
    for h in LABEL_HORIZONS_MINUTES:
        window = _forward_window(today_candles, t_index, h)
        labels[h] = None if window.empty else _label(entry_close, float(window["close"].iloc[-1]), atr_at_t)

    return ForwardOutcomeRow(
        symbol=symbol,
        timestamp=timestamp,
        feature_version=feature_version,
        atr_at_t=atr_at_t,
        fwd_return_1m=fwd_returns[1],
        fwd_return_3m=fwd_returns[3],
        fwd_return_5m=fwd_returns[5],
        fwd_return_10m=fwd_returns[10],
        fwd_return_15m=fwd_returns[15],
        fwd_return_30m=fwd_returns[30],
        mfe_1m=mfe_mae[1][0],
        mae_1m=mfe_mae[1][1],
        mfe_5m=mfe_mae[5][0],
        mae_5m=mfe_mae[5][1],
        mfe_15m=mfe_mae[15][0],
        mae_15m=mfe_mae[15][1],
        mfe_30m=mfe_mae[30][0],
        mae_30m=mfe_mae[30][1],
        label_5m=labels[5],
        label_15m=labels[15],
        label_30m=labels[30],
        horizon_truncated_by_session_close=truncated,
    )
