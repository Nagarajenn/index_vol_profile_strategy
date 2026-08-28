"""Phase 7B: dual-resolution pre/post-3pm transition detail. For every
post-CAS trading day, computes and persists:
  - 6 five-minute pre-transition windows (14:30-14:59) -- cas_pretransition_windows
  - 16 native 1-minute post-transition rows (15:00-15:15) -- cas_post_transition_minutes
  - 7 leakage-safe forecast checkpoints (14:30/35/40/45/50/55/59) -- cas_transition_forecasts

Companion to scripts/run_cas_intelligence.py (which must be run first --
this script reuses its already-computed mti_cas_daily_transitions rows for
the forecast's magnitude-tier vote). Re-runnable/idempotent like every
other script in this project.

Usage: venv\\Scripts\\python.exe scripts\\run_cas_windowed_analysis.py [--symbols SENSEX NIFTY]
"""

import argparse
import logging
import sys
import time as time_module
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: F401 -- truststore bootstrap, must import before any DB/HTTPS call
from config.instruments import INSTRUMENTS
from config.settings import IST
from db import reader as db_reader
from db import writer as db_writer
from market_transition.cas_forecast import FORECAST_CHECKPOINTS, build_transition_forecast
from market_transition.cas_transition import CAS_EFFECTIVE_DATE, extract_cas_transition_record
from market_transition.cas_windows import build_post_transition_minutes, build_pre_transition_windows
from market_transition.research import extract_all_records
from market_transition.statistics import run_correlation_study

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# The forecast's magnitude-tier vote needs enough history to be worth
# anything at all -- a large historical fetch is cheap (one query, done
# once per symbol), matching run_cas_intelligence.py's own pattern.
CAS_HISTORY_LIMIT = 10_000


def _split_by_date(candles):
    if candles.empty:
        return {}
    return {d: g.reset_index(drop=True) for d, g in candles.groupby(candles["timestamp"].dt.date)}


def run_symbol(symbol: str) -> tuple[int, int, int]:
    bin_size = INSTRUMENTS[symbol]["volume_profile_bin_size"]
    candles = db_reader.load_raw_candles(symbol)
    by_date = _split_by_date(candles)

    old_records = extract_all_records(symbol, candles, bin_size, extract_fn=extract_cas_transition_record)
    old_by_date = {r.session_date: r for r in old_records}
    # find_analogs()'s weighted-factor machinery (market_transition/scoring.py)
    # needs real correlation results to have anything to weight by -- reuses
    # the SAME 13-factor original-methodology study the CAS engine already
    # runs one of, computed once per symbol here (not per checkpoint/day).
    correlations = run_correlation_study(old_records)
    # Phase 7A's own persisted output -- the forecast's magnitude-tier vote
    # reads transition_type/magnitude_tier straight from it, closing the
    # loop between the two phases instead of fitting a second model.
    cas_history = db_reader.load_cas_daily_transitions(symbol, limit=CAS_HISTORY_LIMIT)

    n_windows = n_minutes = n_forecasts = 0
    for session_date, day_candles in sorted(by_date.items()):
        if session_date < CAS_EFFECTIVE_DATE:
            continue

        prior_dates = sorted(d for d in by_date if d < session_date)
        prior_day_candles = by_date[prior_dates[-1]] if prior_dates else None
        window_start = max(0, len(prior_dates) - 20)
        historical_by_date = {d: by_date[d] for d in prior_dates[window_start:]}

        old = old_by_date.get(session_date)
        expiry_type = old.features.expiry_type if old else None

        # Whole day's classified events fetched once, filtered in-memory
        # per checkpoint by cas_windows._news_risk_near -- avoids a DB
        # round-trip per checkpoint for a field most checkpoints won't have
        # a nearby event for anyway.
        events = db_reader.list_classified_events_between(
            datetime.combine(session_date, datetime.min.time(), tzinfo=IST) - timedelta(hours=1),
            datetime.combine(session_date, datetime.min.time(), tzinfo=IST) + timedelta(hours=16),
        )

        def option_lookup(at_time, _symbol=symbol, _session_date=session_date):
            return db_reader.get_option_summary_near(_symbol, _session_date, at_or_before=at_time.strftime("%H:%M:%S"))

        pre_windows = build_pre_transition_windows(day_candles, historical_by_date, option_lookup, events, bin_size, session_date)
        for w in pre_windows:
            db_writer.insert_cas_pretransition_window(symbol, session_date, w)
            n_windows += 1

        post_minutes = build_post_transition_minutes(
            day_candles, historical_by_date, option_lookup, pre_windows[-1] if pre_windows else None, bin_size, session_date
        )
        for m in post_minutes:
            db_writer.insert_cas_post_transition_minute(symbol, session_date, m)
            n_minutes += 1

        for checkpoint in FORECAST_CHECKPOINTS:
            forecast = build_transition_forecast(
                checkpoint, symbol, session_date, day_candles, prior_day_candles, historical_by_date,
                old_records, cas_history, correlations, bin_size, expiry_type,
            )
            if forecast:
                db_writer.insert_cas_transition_forecast(symbol, session_date, forecast)
                n_forecasts += 1

    return n_windows, n_minutes, n_forecasts


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", nargs="*", default=list(INSTRUMENTS.keys()))
    args = parser.parse_args()

    for symbol in args.symbols:
        t0 = time_module.monotonic()
        n_windows, n_minutes, n_forecasts = run_symbol(symbol)
        print(
            f"{symbol}: wrote {n_windows} pre-transition windows, {n_minutes} post-transition minutes, "
            f"{n_forecasts} forecasts in {time_module.monotonic() - t0:.1f}s"
        )


if __name__ == "__main__":
    main()
