"""Quant Feature Store batch backfill.

Usage:
  venv\\Scripts\\python.exe scripts\\run_quant_feature_backfill.py --start 2026-08-01 --end 2026-08-10   (small test run first)
  venv\\Scripts\\python.exe scripts\\run_quant_feature_backfill.py --start 2026-04-09 --end 2026-08-17    (full range)
  venv\\Scripts\\python.exe scripts\\run_quant_feature_backfill.py --start 2026-04-09 --end 2026-08-17 --symbols SENSEX
  venv\\Scripts\\python.exe scripts\\run_quant_feature_backfill.py --start 2026-04-09 --end 2026-08-17 --skip-options
"""

import argparse
import sys
import time
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.instruments import INSTRUMENTS
from quant_features.backfill import run_market_and_outcome_backfill, run_option_features_backfill
from quant_features.versioning import FEATURE_VERSION


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", nargs="*", default=list(INSTRUMENTS.keys()))
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    parser.add_argument("--feature-version", default=FEATURE_VERSION)
    parser.add_argument("--skip-options", action="store_true", help="skip the quant_option_features pass")
    args = parser.parse_args()

    for symbol in args.symbols:
        t0 = time.monotonic()
        written = run_market_and_outcome_backfill(symbol, args.start, args.end, feature_version=args.feature_version)
        elapsed = time.monotonic() - t0
        print(f"{symbol}: wrote {written} market-feature/forward-outcome rows in {elapsed:.1f}s")

        if not args.skip_options:
            t0 = time.monotonic()
            opt_written = run_option_features_backfill(symbol, args.start, args.end, feature_version=args.feature_version)
            elapsed = time.monotonic() - t0
            print(f"{symbol}: wrote {opt_written} option-feature rows in {elapsed:.1f}s")


if __name__ == "__main__":
    main()
