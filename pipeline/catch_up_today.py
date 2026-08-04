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


def catch_up_date(symbol: str, target_date: date, interval_min: int = LIVE_LOOP_INTERVAL_MIN) -> list[dict]:
    """Generalized catch-up: replays `target_date`'s session at `interval_min`
    granularity, writing mode="live" rows (mode="live" is what
    pipeline/run_snapshot.py's should_render_chart() and the FastAPI
    dashboard's "latest live row" query both key off of -- mode="backfill"
    rows are invisible to the live dashboard by design).

    For `target_date == date.today()` (a session already in progress),
    institutional bias is computed from a SINGLE current option-chain fetch
    reused across every checkpoint -- Dhan's option chain is live-data-only,
    so there's no way to know historical intraday OI for each past minute.
    This represents "today's price action so far, read against current OI
    positioning" rather than truly contemporaneous OI -- weakest for the
    earliest checkpoints, exact for the most recent one. The loop below
    explicitly stops once a checkpoint's cutoff passes the latest available
    candle -- `truncated` does NOT naturally become empty past that point
    (it's just every candle up to the real latest one, same as the previous
    checkpoint), so without this the loop would silently recompute and
    rewrite the same "now" snapshot for every remaining checkpoint through
    session close.

    For a past `target_date` (recovering a fully-missed day, e.g. an outage),
    there is no live option chain to fetch at all -- every checkpoint gets
    institutional_bias_label="Unavailable (historical)", same as
    pipeline/backfill.py's normal backfill mode.

    Call this once per symbol; for today's date, hand off to
    pipeline.live_loop for the rest of the session afterwards -- from that
    point on, every row gets its own fresh option-chain fetch.
    """
    meta = INSTRUMENTS[symbol]
    is_today = target_date == date.today()
    start_date = target_date - timedelta(days=10)

    candles_1min = fetch_intraday_candles(symbol, start_date, target_date, interval=1)
    day_df_full = candles_1min[candles_1min["timestamp"].dt.date == target_date].reset_index(drop=True)
    if day_df_full.empty:
        logger.warning("No candles for %s on %s -- market may not have opened / traded that day", symbol, target_date)
        return []

    prior_days = sorted(d for d in candles_1min["timestamp"].dt.date.unique() if d < target_date)
    prior_day_df = candles_1min[candles_1min["timestamp"].dt.date == prior_days[-1]] if prior_days else None

    daily = fetch_daily_candles(symbol, start_date, target_date)
    prior_daily_rows = daily[daily["timestamp"].dt.date < target_date]
    prior_day_ohlc = None
    if len(prior_daily_rows):
        row = prior_daily_rows.iloc[-1]
        prior_day_ohlc = {"high": row["high"], "low": row["low"], "close": row["close"]}

    db_writer.insert_raw_candles(candles_1min, symbol)
    db_writer.insert_daily_candles(daily, symbol)

    option_chain = None
    option_summary = None
    if is_today:
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

    latest_available = day_df_full["timestamp"].max()
    written: list[dict] = []
    for cp_time in generate_checkpoint_times(interval_min=interval_min):
        cutoff = pd.Timestamp(datetime.combine(target_date, cp_time)).tz_localize(IST)
        if cutoff > latest_available:
            # generate_checkpoint_times() is strictly ascending, so every
            # remaining checkpoint would also exceed the latest candle --
            # stop instead of recomputing the same "now" snapshot on repeat.
            break
        truncated = day_df_full[day_df_full["timestamp"] <= cutoff]
        if truncated.empty:
            continue

        card = run_snapshot(
            symbol=symbol,
            mode="live",
            day_candles_1min=truncated,
            prior_day_candles_1min=prior_day_df,
            prior_day_ohlc=prior_day_ohlc,
            # Always pass the tuple, even (None, None) on fetch failure/past
            # date -- if we don't, a missing shared fetch would fall through
            # to run_snapshot's own per-call fetch-on-mode=="live" path and
            # retry (and likely re-fail, or fetch today's chain for a past
            # date) up to ~375 times.
            option_chain_override=(option_chain, option_summary),
            persist_option_chain=False,
        )
        if card:
            written.append(card)

    logger.info("Caught up %s: %d checkpoints written for %s", symbol, len(written), target_date)
    return written


def catch_up_today(symbol: str, interval_min: int = LIVE_LOOP_INTERVAL_MIN) -> list[dict]:
    """One-time catch-up for a session already in progress -- see catch_up_date()."""
    return catch_up_date(symbol, date.today(), interval_min)
