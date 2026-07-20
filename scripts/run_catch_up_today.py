"""One-time catch-up for a session already in progress: replays today from
market open to now (mode="live", 1-min granularity by default), then you
start scripts/run_live_loop.py to carry on for the rest of the session.

Usage: venv\\Scripts\\python.exe scripts\\run_catch_up_today.py [SENSEX] [NIFTY]
"""
import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.instruments import INSTRUMENTS
from pipeline.catch_up_today import catch_up_today

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("symbols", nargs="*", default=list(INSTRUMENTS.keys()))
    args = parser.parse_args()

    for symbol in args.symbols:
        written = catch_up_today(symbol)
        print(f"{symbol}: wrote {len(written)} live checkpoints")
        if written:
            last = written[-1]
            print(f"  latest: confidence={last.get('confidence')} trend={last.get('trend')} chart={last.get('chart_path')}")


if __name__ == "__main__":
    main()
