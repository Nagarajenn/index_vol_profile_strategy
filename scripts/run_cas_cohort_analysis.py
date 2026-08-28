"""Phase 7C: historical cohorts + pre-3pm warning-indicator statistics.
Groups CAS-era days into 7 named cohorts (derived from Phase 7A's
transition_type x magnitude_tier) and, for each cohort, compares its
pre-3pm (14:55-14:59) state against the rest of the sample.

Companion to scripts/run_cas_intelligence.py (Phase 7A) and
scripts/run_cas_windowed_analysis.py (Phase 7B) -- both must already have
run for the symbol; this script only reads their persisted output, never
recomputes from raw candles. Re-runnable/idempotent like every other
script in this project.

Usage: venv\\Scripts\\python.exe scripts\\run_cas_cohort_analysis.py [--symbols SENSEX NIFTY]
"""

import argparse
import sys
import time as time_module
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: F401 -- truststore bootstrap, must import before any DB/HTTPS call
from config.instruments import INSTRUMENTS
from db import reader as db_reader
from db import writer as db_writer
from market_transition.cas_cohorts import run_cohort_analysis
from market_transition.cas_transition import CasDailyTransition
from market_transition.cas_windows import PreTransitionWindow


def _load_cas_rows(symbol: str) -> list[CasDailyTransition]:
    rows = db_reader.load_cas_daily_transitions(symbol, limit=10_000)
    return [CasDailyTransition(**{k: v for k, v in row.items() if k != "computed_at"}) for row in rows]


def _load_final_windows(symbol: str) -> dict:
    raw = db_reader.load_final_pretransition_windows(symbol)
    return {d: PreTransitionWindow(**row) for d, row in raw.items()}


def run_symbol(symbol: str) -> tuple[int, int]:
    cas_rows = _load_cas_rows(symbol)
    final_windows_by_date = _load_final_windows(symbol)

    feature_stats, categorical_stats = run_cohort_analysis(cas_rows, final_windows_by_date)
    for stat in feature_stats:
        db_writer.insert_cas_cohort_feature_stat(symbol, stat)
    for breakdown in categorical_stats:
        db_writer.insert_cas_cohort_categorical(symbol, breakdown)

    return len(feature_stats), len(categorical_stats)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", nargs="*", default=list(INSTRUMENTS.keys()))
    args = parser.parse_args()

    for symbol in args.symbols:
        t0 = time_module.monotonic()
        n_features, n_categorical = run_symbol(symbol)
        print(f"{symbol}: wrote {n_features} cohort feature stats, {n_categorical} categorical breakdowns in {time_module.monotonic() - t0:.1f}s")


if __name__ == "__main__":
    main()
