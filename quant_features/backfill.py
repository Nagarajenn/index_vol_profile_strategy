"""Batch (historical) backfill for the Quant Feature Store. Reads already-
collected data straight from Postgres (raw_candles/option_chain_raw/
classified_events) -- this does NOT call the Dhan API itself, unlike
pipeline/backfill.py, since the price/option/news history this milestone
needs to backfill already exists from the existing pipeline's own live
collection.

`run_market_and_outcome_backfill` computes and writes quant_market_features
AND quant_forward_outcomes in the same per-minute pass -- for backfill mode
specifically, ALL of a trading day's future candles already exist in the
data pulled up front, so there's no reason to defer labeling to a later
run the way live incremental mode must (see quant_features/labeling.py's
own "future data only" guarantee, which makes this safe regardless of
loop order). `run_option_features_backfill` is a separate function since
option_chain_raw has its own, much sparser and shorter-history cadence,
not the market-feature minute grid.
"""

import logging
from datetime import date, datetime, timedelta

import pandas as pd

from config.instruments import INSTRUMENTS
from config.settings import BACKFILL_LOOKBACK_DAYS, IST
from db import reader as db_reader
from db import writer as db_writer
from market_transition.expiry_calendar import build_expiry_calendar
from option_chain.summary import summarize_option_chain

from . import engine
from .cutoff import group_by_date, historical_by_date_before, truncate_candles
from .price_features import compute_price_volatility_features
from .versioning import FEATURE_VERSION

logger = logging.getLogger(__name__)

EXPIRY_CALENDAR_PAST_BUFFER_DAYS = 40
EXPIRY_CALENDAR_FUTURE_BUFFER_DAYS = 40
NEWS_LOOKUP_PAST_BUFFER_DAYS = 1
LABEL_RECENT_DAYS_DEFAULT = 1


def _prior_day_context(by_date: dict[date, pd.DataFrame], session_date: date) -> tuple[pd.DataFrame | None, dict | None]:
    prior_dates = sorted(d for d in by_date if d < session_date)
    if not prior_dates:
        return None, None
    prior_df = by_date[prior_dates[-1]]
    ohlc = {"high": float(prior_df["high"].max()), "low": float(prior_df["low"].min()), "close": float(prior_df["close"].iloc[-1])}
    return prior_df, ohlc


def run_market_and_outcome_backfill(
    symbol: str,
    start_date: date,
    end_date: date,
    feature_version: str = FEATURE_VERSION,
    lookback_days: int = BACKFILL_LOOKBACK_DAYS,
) -> int:
    """Writes one quant_market_features row and one quant_forward_outcomes
    row per 1-min candle in [start_date, end_date] for `symbol`. Returns the
    number of minutes processed."""
    instrument_meta = INSTRUMENTS[symbol]
    fetch_start = start_date - timedelta(days=int(lookback_days * 1.6) + 5)

    candles = db_reader.load_raw_candles(symbol, fetch_start, end_date)
    if candles.empty:
        logger.warning("No raw_candles found for %s in [%s, %s]", symbol, fetch_start, end_date)
        return 0
    by_date = group_by_date(candles)

    trading_days = sorted(d for d in by_date if start_date <= d <= end_date)
    if not trading_days:
        logger.warning("No trading days with data for %s in [%s, %s]", symbol, start_date, end_date)
        return 0

    expiry_calendar = build_expiry_calendar(
        symbol,
        trading_days[0] - timedelta(days=EXPIRY_CALENDAR_PAST_BUFFER_DAYS),
        trading_days[-1] + timedelta(days=EXPIRY_CALENDAR_FUTURE_BUFFER_DAYS),
    )

    news_start = datetime.combine(trading_days[0] - timedelta(days=NEWS_LOOKUP_PAST_BUFFER_DAYS), datetime.min.time(), tzinfo=IST)
    news_end = datetime.combine(trading_days[-1] + timedelta(days=1), datetime.min.time(), tzinfo=IST)
    all_events = db_reader.load_classified_events(news_start, news_end)
    events_by_date: dict[date, list] = {}
    for e in all_events:
        events_by_date.setdefault(e.classified_at.date(), []).append(e)

    opt_rows = db_reader.load_option_chain_raw(symbol, trading_days[0], trading_days[-1])
    opt_idx = -1  # last index with fetched_at <= current timestamp

    run_id = db_writer.start_quant_feature_run("batch_backfill", feature_version, symbol, start_date, end_date, datetime.now(IST))
    written = 0
    try:
        for day in trading_days:
            day_df = by_date[day]
            prior_day_df, prior_day_ohlc = _prior_day_context(by_date, day)
            prior_day_close = prior_day_ohlc["close"] if prior_day_ohlc else None
            historical = historical_by_date_before(by_date, day)
            day_events = events_by_date.get(day, [])

            for t_index in range(len(day_df)):
                ts = day_df["timestamp"].iloc[t_index]
                today_candles = truncate_candles(day_df, ts)

                while opt_idx + 1 < len(opt_rows) and opt_rows[opt_idx + 1]["fetched_at"] <= ts:
                    opt_idx += 1
                current_opt_row = opt_rows[opt_idx] if opt_idx >= 0 and opt_rows[opt_idx]["fetched_at"] <= ts else None
                option_summary = (
                    summarize_option_chain(current_opt_row["raw_payload"], instrument_meta["option_chain_atm_window"])
                    if current_opt_row is not None
                    else None
                )

                market_row = engine.compute_market_features_row(
                    symbol,
                    today_candles,
                    historical,
                    instrument_meta,
                    prior_day_candles_1min=prior_day_df,
                    prior_day_ohlc=prior_day_ohlc,
                    prior_day_close=prior_day_close,
                    option_summary=option_summary,
                    expiry_calendar=expiry_calendar,
                    news_events=day_events,
                    feature_version=feature_version,
                )
                db_writer.insert_quant_market_features_row(market_row)

                outcome_row = engine.compute_forward_outcomes_row(
                    symbol, market_row.timestamp, day_df, t_index, market_row.price.atr_14, feature_version=feature_version
                )
                db_writer.insert_quant_forward_outcomes_row(outcome_row)

                written += 1

            logger.info("quant_features backfill: %s %s done (%d/%d trading days)", symbol, day, trading_days.index(day) + 1, len(trading_days))
    except Exception as exc:
        db_writer.finish_quant_feature_run(run_id, written, "failed", datetime.now(IST), error_message=str(exc))
        raise
    else:
        db_writer.finish_quant_feature_run(run_id, written, "completed", datetime.now(IST))

    return written


def label_recent_days(
    symbol: str,
    days_back: int = LABEL_RECENT_DAYS_DEFAULT,
    feature_version: str = FEATURE_VERSION,
) -> int:
    """The lagging pass live incremental mode needs: a row written live at
    (say) 10:00am can't be labeled with its 30m-forward outcome until 10:30am
    has actually happened, so labeling for live-written rows runs here,
    separately and later, rather than inside run_snapshot.py itself. Re-runs
    (and re-upserts) labels for the last `days_back` calendar days' worth of
    raw_candles -- idempotent and safe to call repeatedly, same discipline as
    pipeline/catch_up_today.py. `atr_at_t` is recomputed fresh per row
    (a cheap, pure function of that row's own candles) rather than read back
    from quant_market_features, so this has no dependency on that table
    already being populated for the day.
    """
    end_date = date.today()
    start_date = end_date - timedelta(days=days_back)

    candles = db_reader.load_raw_candles(symbol, start_date, end_date)
    if candles.empty:
        return 0
    by_date = group_by_date(candles)

    written = 0
    for day, day_df in by_date.items():
        for t_index in range(len(day_df)):
            ts = day_df["timestamp"].iloc[t_index]
            today_candles = truncate_candles(day_df, ts)
            atr_at_t = compute_price_volatility_features(today_candles, prior_day_close=None).atr_14
            outcome_row = engine.compute_forward_outcomes_row(symbol, ts, day_df, t_index, atr_at_t, feature_version=feature_version)
            db_writer.insert_quant_forward_outcomes_row(outcome_row)
            written += 1

    logger.info("quant_features label_recent_days: %s wrote %d forward-outcome rows across %d day(s)", symbol, written, len(by_date))
    return written


def run_option_features_backfill(
    symbol: str,
    start_date: date,
    end_date: date,
    feature_version: str = FEATURE_VERSION,
) -> int:
    """Writes one quant_option_features row per existing option_chain_raw
    snapshot in range -- its own cadence, not the market-feature minute
    grid (see module docstring)."""
    instrument_meta = INSTRUMENTS[symbol]
    rows = db_reader.load_option_chain_raw(symbol, start_date, end_date)
    if not rows:
        logger.warning("No option_chain_raw snapshots for %s in [%s, %s]", symbol, start_date, end_date)
        return 0

    run_id = db_writer.start_quant_feature_run("batch_backfill", feature_version, symbol, start_date, end_date, datetime.now(IST))
    written = 0
    prev_row = None
    try:
        for row in rows:
            previous_chain = prev_row["raw_payload"] if prev_row is not None and prev_row["expiry"] == row["expiry"] else None
            feature_row = engine.compute_option_features_row(
                symbol,
                row["fetched_at"],
                row["raw_payload"],
                previous_chain,
                instrument_meta["option_chain_atm_window"],
                feature_version=feature_version,
            )
            db_writer.insert_quant_option_features_row(feature_row)
            written += 1
            prev_row = row
    except Exception as exc:
        db_writer.finish_quant_feature_run(run_id, written, "failed", datetime.now(IST), error_message=str(exc))
        raise
    else:
        db_writer.finish_quant_feature_run(run_id, written, "completed", datetime.now(IST))

    return written
