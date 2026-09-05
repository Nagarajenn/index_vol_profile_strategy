"""Phase 9D: actual outcome aggregation (spec Part 13). For every day
that has cas_post_transition_minutes rows, rolls the native 1-minute data
up into the 4 horizons (1/5/10/15 min from 15:00) and persists to
transition_actual_outcome -- separate, immutable, never mixed with the
forecast row (cas_transition_forecasts).

Companion to scripts/run_cas_windowed_analysis.py (must be run first).
Re-runnable/idempotent like every other script in this project.

Usage: venv\\Scripts\\python.exe scripts\\run_actual_outcome.py [--symbols SENSEX NIFTY]
"""

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: F401 -- truststore bootstrap, must import before any DB/HTTPS call
from db import reader as db_reader
from db import writer as db_writer
from market_transition.cas_windows import PostTransitionMinute, compute_actual_outcome_checkpoints
from pipeline.cas_live import compute_prior_day_atr_14

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

HISTORICAL_LOOKBACK_DAYS = 20


def run_symbol(symbol: str) -> int:
    candles = db_reader.load_raw_candles(symbol)
    by_date = {} if candles.empty else {d: g.reset_index(drop=True) for d, g in candles.groupby(candles["timestamp"].dt.date)}

    n_checkpoints = 0
    for session_date in db_reader.list_cas_post_transition_dates(symbol):
        rows = db_reader.load_post_transition_minutes(symbol, session_date)
        if not rows:
            continue
        minutes = [PostTransitionMinute(**row) for row in rows]

        prior_dates = sorted(d for d in by_date if d < session_date)
        window_start = max(0, len(prior_dates) - HISTORICAL_LOOKBACK_DAYS)
        historical_by_date = {d: by_date[d] for d in prior_dates[window_start:]}
        atr_14 = compute_prior_day_atr_14(historical_by_date)

        for checkpoint in compute_actual_outcome_checkpoints(minutes, atr_14=atr_14):
            db_writer.insert_transition_actual_outcome(symbol, session_date, checkpoint)
            n_checkpoints += 1

    return n_checkpoints


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", nargs="+", default=["SENSEX", "NIFTY"])
    args = parser.parse_args()

    for symbol in args.symbols:
        n = run_symbol(symbol)
        logger.info("%s: wrote %d actual-outcome checkpoints", symbol, n)


if __name__ == "__main__":
    main()
