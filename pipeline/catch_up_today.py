import logging
from datetime import date, datetime, timedelta

import pandas as pd

from config.instruments import INSTRUMENTS
from config.settings import IST, LIVE_LOOP_INTERVAL_MIN
from db import writer as db_writer
from dhan_client.client import fetch_daily_candles, fetch_intraday_candles
from option_chain.fetch import get_option_chain
from option_chain.summary import summarize_option_chain
from pipeline.backfill import generate_checkpoint_times
from pipeline.run_snapshot import run_snapshot

logger = logging.getLogger(__name__)


def catch_up_today(symbol: str, interval_min: int = LIVE_LOOP_INTERVAL_MIN) -> list[dict]:
    """One-time catch-up for a session already in progress: replays TODAY
    from market open up to now at `interval_min` granularity, writing
    mode="live" rows so the live dashboard immediately reflects today's
    session (mode="live" is what pipeline/run_snapshot.py's should_render_chart()
    and the FastAPI dashboard's "latest live row" query both key off of --
    mode="backfill" rows are invisible to the live dashboard by design).

    Institutional bias is computed from a SINGLE current option-chain fetch
    reused across every catch-up checkpoint: Dhan's option chain is
    live-data-only, so there's no way to know historical intraday OI for
    each past minute. This represents "today's price action so far, read
    against current OI positioning" rather than truly contemporaneous OI --
    an approximation that's weakest for the earliest checkpoints and exact
    for the most recent one. Each checkpoint beyond the latest available
    candle is naturally skipped (empty truncation), so this safely stops
    at "now" without needing to compute that boundary explicitly.

    Call this once per symbol, then hand off to pipeline.live_loop for
    the rest of the session -- from that point on, every row gets its own
    fresh option-chain fetch.
    """
    meta = INSTRUMENTS[symbol]
    today = date.today()
    start_date = today - timedelta(days=10)

    candles_1min = fetch_intraday_candles(symbol, start_date, today, interval=1)
    day_df_full = candles_1min[candles_1min["timestamp"].dt.date == today].reset_index(drop=True)
    if day_df_full.empty:
        logger.warning("No candles for %s today (%s) yet -- market may not have opened", symbol, today)
        return []

    prior_days = sorted(d for d in candles_1min["timestamp"].dt.date.unique() if d < today)
    prior_day_df = candles_1min[candles_1min["timestamp"].dt.date == prior_days[-1]] if prior_days else None

    daily = fetch_daily_candles(symbol, start_date, today)
    prior_daily_rows = daily[daily["timestamp"].dt.date < today]
    prior_day_ohlc = None
    if len(prior_daily_rows):
        row = prior_daily_rows.iloc[-1]
        prior_day_ohlc = {"high": row["high"], "low": row["low"], "close": row["close"]}

    db_writer.insert_raw_candles(candles_1min, symbol)
    db_writer.insert_daily_candles(daily, symbol)

    option_chain = None
    option_summary = None
    try:
        option_chain = get_option_chain(symbol)
        option_summary = summarize_option_chain(option_chain, meta["option_chain_atm_window"])
        # Persisted once here (not per-checkpoint below) -- reusing this same
        # fetch across ~375 checkpoints would otherwise insert the same
        # multi-KB JSONB payload once per checkpoint under a different
        # fetched_at, implying (falsely) that OI was freshly polled at each
        # of those past minutes.
        db_writer.insert_option_chain(
            symbol=symbol,
            expiry=option_chain["expiry"],
            fetched_at=datetime.now(IST),
            spot=option_chain.get("last_price"),
            raw_payload=option_chain,
            summary=option_summary,
        )
    except Exception as e:
        logger.warning("Option chain fetch failed for %s during catch-up: %s", symbol, e)

    written: list[dict] = []
    for cp_time in generate_checkpoint_times(interval_min=interval_min):
        cutoff = pd.Timestamp(datetime.combine(today, cp_time)).tz_localize(IST)
        truncated = day_df_full[day_df_full["timestamp"] <= cutoff]
        if truncated.empty:
            continue

        card = run_snapshot(
            symbol=symbol,
            mode="live",
            day_candles_1min=truncated,
            prior_day_candles_1min=prior_day_df,
            prior_day_ohlc=prior_day_ohlc,
            # Always pass the tuple, even (None, None) on fetch failure --
            # if we don't, a failed shared fetch would fall through to
            # run_snapshot's own per-call fetch-on-mode=="live" path and
            # retry (and likely re-fail) up to ~375 times.
            option_chain_override=(option_chain, option_summary),
            persist_option_chain=False,
        )
        if card:
            written.append(card)

    logger.info("Caught up %s: %d checkpoints written for %s", symbol, len(written), today)
    return written
