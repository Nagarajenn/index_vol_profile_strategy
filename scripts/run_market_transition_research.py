"""Runs the Market Transition Intelligence research study: extracts every
trading day's 2-3pm features/outcome from raw_candles history, discovers
factor correlations across all of them, scores every day using that study,
and persists both to mti_daily_transitions / mti_factor_correlations.

Re-runnable/idempotent -- upserts, so running this again after new days of
data accumulate just refreshes the correlation study and every day's score
with it (a day's score can change over time as more history accumulates,
which is expected and desired for a research tool).

Usage: venv\\Scripts\\python.exe scripts\\run_market_transition_research.py [--symbols SENSEX NIFTY]
"""

import argparse
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: F401 -- truststore bootstrap, must import before any DB/HTTPS call
from config.instruments import INSTRUMENTS
from db import reader as db_reader
from db import writer as db_writer
from market_transition.research import run_research

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", nargs="*", default=list(INSTRUMENTS.keys()))
    args = parser.parse_args()

    for symbol in args.symbols:
        t0 = time.monotonic()
        bin_size = INSTRUMENTS[symbol]["volume_profile_bin_size"]

        candles = db_reader.load_raw_candles(symbol)
        logger.info("%s: loaded %d candles", symbol, len(candles))

        records, correlations, scores = run_research(symbol, candles, bin_size)
        logger.info("%s: extracted %d complete trading-day records", symbol, len(records))

        for c in correlations:
            db_writer.insert_mti_factor_correlation(symbol, c)

        score_by_date = {s.session_date: s for s in scores}
        for r in records:
            db_writer.insert_mti_daily_transition(r, score_by_date.get(r.session_date))

        significant = [c for c in correlations if c.confidence_label in ("Strong", "Moderate")]
        print(f"\n{symbol}: {len(records)} days analyzed, {len(correlations)} factor tests run in {time.monotonic() - t0:.1f}s")
        print(f"  {len(significant)} factor/target pairs reached Strong/Moderate confidence:")
        for c in sorted(significant, key=lambda c: (c.p_value if c.p_value is not None else 1)):
            print(f"    [{c.confidence_label}] {c.factor_name} vs {c.target} (n={c.n}, p={c.p_value:.4f}) -- {c.direction_note}")


if __name__ == "__main__":
    main()
