"""Live-incremental hook for the Quant Feature Store -- called once per
symbol per minute from pipeline/run_snapshot.py's mode="live" path (and,
transitively, from pipeline/catch_up_today.py, which also calls
run_snapshot with mode="live"). Writes quant_market_features every tick;
quant_option_features only when a fresh option-chain fetch actually
happened this tick. Forward-outcome labels are NOT written here -- a live
row can't be labeled until enough future minutes have actually elapsed, see
quant_features.backfill.label_recent_days for that lagging pass.

Reads historical context (raw_candles, prior option_chain_raw snapshot,
recent classified_events) straight from Postgres rather than the Dhan API
-- this only ever needs data the pipeline has already collected and
persisted itself.
"""

import logging
from datetime import timedelta

from config.instruments import INSTRUMENTS
from config.settings import BACKFILL_LOOKBACK_DAYS
from db import reader as db_reader
from db import writer as db_writer
from market_transition.expiry_calendar import build_expiry_calendar

from . import engine
from .cutoff import group_by_date, historical_by_date_before
from .news_features import NEWS_WINDOW_MINUTES
from .versioning import FEATURE_VERSION

logger = logging.getLogger(__name__)

EXPIRY_CALENDAR_PAST_BUFFER_DAYS = 40
EXPIRY_CALENDAR_FUTURE_BUFFER_DAYS = 40


def write_live_quant_features(
    symbol: str,
    day_candles_1min,
    prior_day_candles_1min=None,
    prior_day_ohlc: dict | None = None,
    option_chain: dict | None = None,
    option_summary=None,
    feature_version: str = FEATURE_VERSION,
) -> None:
    if day_candles_1min is None or day_candles_1min.empty:
        return

    instrument_meta = INSTRUMENTS[symbol]
    session_date = day_candles_1min["timestamp"].iloc[-1].date()

    lookback_start = session_date - timedelta(days=int(BACKFILL_LOOKBACK_DAYS * 1.6) + 5)
    hist_candles = db_reader.load_raw_candles(symbol, lookback_start, session_date)
    historical = historical_by_date_before(group_by_date(hist_candles), session_date)

    expiry_calendar = build_expiry_calendar(
        symbol,
        session_date - timedelta(days=EXPIRY_CALENDAR_PAST_BUFFER_DAYS),
        session_date + timedelta(days=EXPIRY_CALENDAR_FUTURE_BUFFER_DAYS),
    )

    as_of_now = day_candles_1min["timestamp"].iloc[-1].to_pydatetime()
    news_events = db_reader.load_classified_events(as_of_now - timedelta(minutes=NEWS_WINDOW_MINUTES), as_of_now)

    market_row = engine.compute_market_features_row(
        symbol,
        day_candles_1min,
        historical,
        instrument_meta,
        prior_day_candles_1min=prior_day_candles_1min,
        prior_day_ohlc=prior_day_ohlc,
        prior_day_close=prior_day_ohlc["close"] if prior_day_ohlc else None,
        option_summary=option_summary,
        expiry_calendar=expiry_calendar,
        news_events=news_events,
        feature_version=feature_version,
    )
    db_writer.insert_quant_market_features_row(market_row)

    if option_chain is not None:
        opt_rows_today = db_reader.load_option_chain_raw(symbol, session_date, session_date)
        previous_rows = [r for r in opt_rows_today if r["fetched_at"] < market_row.timestamp]
        previous_chain = previous_rows[-1]["raw_payload"] if previous_rows else None

        option_row = engine.compute_option_features_row(
            symbol,
            market_row.timestamp,
            option_chain,
            previous_chain,
            instrument_meta["option_chain_atm_window"],
            feature_version=feature_version,
        )
        db_writer.insert_quant_option_features_row(option_row)
