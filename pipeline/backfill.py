import logging
from datetime import date, datetime, time, timedelta

import pandas as pd

from config.settings import (
    BACKFILL_CHART_CHECKPOINTS,
    BACKFILL_CHECKPOINT_INTERVAL_MIN,
    BACKFILL_LOOKBACK_DAYS,
    IST,
    SESSION_CLOSE,
    SESSION_OPEN,
)
from db import writer as db_writer
from dhan_client.client import fetch_daily_candles, fetch_intraday_candles
from pipeline.run_snapshot import run_snapshot

logger = logging.getLogger(__name__)


def generate_checkpoint_times(
    session_open: str = SESSION_OPEN,
    session_close: str = SESSION_CLOSE,
    interval_min: int = BACKFILL_CHECKPOINT_INTERVAL_MIN,
) -> list[time]:
    fmt = "%H:%M"
    start = datetime.strptime(session_open, fmt)
    end = datetime.strptime(session_close, fmt)
    times = []
    cur = start
    while cur <= end:
        times.append(cur.time())
        cur += timedelta(minutes=interval_min)
    return times


def backfill_symbol(
    symbol: str,
    lookback_days: int = BACKFILL_LOOKBACK_DAYS,
    chart_checkpoints: list[str] = BACKFILL_CHART_CHECKPOINTS,
    end_date: date | None = None,
) -> list[dict]:
    """Dense 60-day backfill: fetch each symbol's 1-min history once, persist
    it to Postgres once (not per-checkpoint -- run_snapshot() only persists
    raw candles when it does its own live-mode fetching), then write a
    levels_snapshots row for every `BACKFILL_CHECKPOINT_INTERVAL_MIN`-spaced
    checkpoint across every trading day found, computed locally with no
    further API calls. Chart PNGs are only rendered at `chart_checkpoints`
    to keep runtime/storage sane (numeric levels are still saved for every
    checkpoint regardless). Option chain / institutional bias is always
    "unavailable_backfill" here since Dhan's option chain is live-only.
    """
    end_date = end_date or date.today()
    # pad extra calendar days so we still net `lookback_days` *trading* days
    # after weekends/holidays are excluded, then keep the most recent slice.
    start_date = end_date - timedelta(days=int(lookback_days * 1.6) + 5)

    candles_1min = fetch_intraday_candles(symbol, start_date, end_date, interval=1)
    if candles_1min.empty:
        logger.warning("No data returned for %s backfill window", symbol)
        return []

    trading_days = sorted(candles_1min["timestamp"].dt.date.unique())
    trading_days = trading_days[-lookback_days:]

    daily = fetch_daily_candles(symbol, start_date, end_date)

    db_writer.insert_raw_candles(candles_1min, symbol)
    db_writer.insert_daily_candles(daily, symbol)

    checkpoint_times = generate_checkpoint_times()

    written: list[dict] = []
    for i, day in enumerate(trading_days):
        day_df_full = candles_1min[candles_1min["timestamp"].dt.date == day].reset_index(drop=True)

        prior_day = trading_days[i - 1] if i > 0 else None
        prior_day_df = candles_1min[candles_1min["timestamp"].dt.date == prior_day] if prior_day else None

        prior_daily_rows = daily[daily["timestamp"].dt.date < day]
        prior_day_ohlc = None
        if len(prior_daily_rows):
            row = prior_daily_rows.iloc[-1]
            prior_day_ohlc = {"high": row["high"], "low": row["low"], "close": row["close"]}

        for cp_time in checkpoint_times:
            cutoff = pd.Timestamp(datetime.combine(day, cp_time)).tz_localize(IST)
            truncated = day_df_full[day_df_full["timestamp"] <= cutoff]
            if truncated.empty:
                continue

            force_chart = cp_time.strftime("%H:%M") in chart_checkpoints
            card = run_snapshot(
                symbol=symbol,
                mode="backfill",
                day_candles_1min=truncated,
                prior_day_candles_1min=prior_day_df,
                prior_day_ohlc=prior_day_ohlc,
                force_chart=force_chart,
            )
            if card:
                written.append(card)

        logger.info("Backfilled %s %s (%d/%d trading days)", symbol, day, i + 1, len(trading_days))

    return written
