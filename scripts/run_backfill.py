"""60-day dense backfill for training/backtesting.

Usage:
  venv\\Scripts\\python.exe scripts\\run_backfill.py --days 5          (small test run first)
  venv\\Scripts\\python.exe scripts\\run_backfill.py                  (full 60-day backfill)
  venv\\Scripts\\python.exe scripts\\run_backfill.py --symbols SENSEX
"""
import argparse
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.instruments import INSTRUMENTS
from config.settings import BACKFILL_LOOKBACK_DAYS
from pipeline.backfill import backfill_symbol

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", nargs="*", default=list(INSTRUMENTS.keys()))
    parser.add_argument("--days", type=int, default=BACKFILL_LOOKBACK_DAYS)
    args = parser.parse_args()

    for symbol in args.symbols:
        t0 = time.monotonic()
        written = backfill_symbol(symbol, lookback_days=args.days)
        elapsed = time.monotonic() - t0
        print(f"{symbol}: wrote {len(written)} snapshots in {elapsed:.1f}s")


if __name__ == "__main__":
    main()
