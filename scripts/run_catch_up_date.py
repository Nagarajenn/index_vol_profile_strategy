"""One-time catch-up for a fully-missed past trading day (e.g. after an
outage): replays that date's session (mode="live", 1-min granularity by
default). For today's date this behaves exactly like
run_catch_up_today.py; for a past date, institutional bias is
"Unavailable (historical)" since Dhan's option chain is live-only.

Usage: venv\\Scripts\\python.exe scripts\\run_catch_up_date.py 2026-07-24 [SENSEX] [NIFTY]
"""
import argparse
import logging
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.instruments import INSTRUMENTS
from pipeline.catch_up_today import catch_up_date

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("target_date", type=date.fromisoformat, help="YYYY-MM-DD")
    parser.add_argument("symbols", nargs="*", default=list(INSTRUMENTS.keys()))
    args = parser.parse_args()

    for symbol in args.symbols:
        written = catch_up_date(symbol, args.target_date)
        print(f"{symbol}: wrote {len(written)} live checkpoints for {args.target_date}")
        if written:
            last = written[-1]
            print(f"  latest: confidence={last.get('confidence')} trend={last.get('trend')} chart={last.get('chart_path')}")


if __name__ == "__main__":
    main()
