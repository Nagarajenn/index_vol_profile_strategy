"""Phase 9D: forecast-vs-actual evaluation (spec Part 14). For every day
that has BOTH a frozen 14:59 forecast (cas_transition_forecasts) and a
computed 15-min actual outcome (transition_actual_outcome), computes
directional accuracy, a multi-class Brier score, and false-positive/
false-negative flags, persisted to forecast_evaluation.

Never re-touches the forecast row itself -- "do not optimize the model
to historical outcomes after seeing them" (spec Part 14) is enforced
structurally here: this script only ever READS cas_transition_forecasts,
never writes to it.

Companion to scripts/run_cas_windowed_analysis.py and
scripts/run_actual_outcome.py (both must be run first).
Re-runnable/idempotent like every other script in this project.

Usage: venv\\Scripts\\python.exe scripts\\run_forecast_evaluation.py [--symbols SENSEX NIFTY]
"""

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: F401 -- truststore bootstrap, must import before any DB/HTTPS call
from db import reader as db_reader
from db import writer as db_writer
from market_transition.verdict import evaluate_forecast_vs_actual

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def run_symbol(symbol: str) -> int:
    n = 0
    for session_date in db_reader.list_cas_forecast_dates(symbol):
        forecast = db_reader.load_frozen_forecast(symbol, session_date)
        actual = db_reader.load_actual_outcome(symbol, session_date, horizon_minutes=15)
        if forecast is None or actual is None:
            continue

        result = evaluate_forecast_vs_actual(
            forecast["verdict"], forecast["probability_up"], forecast["probability_down"],
            forecast["probability_no_material_transition"], actual["direction"],
        )
        db_writer.insert_forecast_evaluation(
            symbol, session_date, forecast["verdict"], actual["direction"],
            result["directionally_correct"], result["brier_score"], result["predicted_probability_of_actual"],
            result["is_false_positive"], result["is_false_negative"],
        )
        n += 1
    return n


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", nargs="+", default=["SENSEX", "NIFTY"])
    args = parser.parse_args()

    for symbol in args.symbols:
        n = run_symbol(symbol)
        logger.info("%s: wrote %d forecast evaluations", symbol, n)


if __name__ == "__main__":
    main()
