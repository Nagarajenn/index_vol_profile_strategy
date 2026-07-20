"""Auto-repeating live snapshot loop for market hours (09:15-15:30 IST, every 5 min).

Usage: venv\\Scripts\\python.exe scripts\\run_live_loop.py [SENSEX NIFTY ...]

Runs until interrupted (Ctrl+C). Start it manually each trading day (or wire
it into your own scheduler, e.g. Windows Task Scheduler, if you want it to
start automatically -- that's a persistent system change, so ask first if
you'd like help setting that up).
"""
import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.instruments import INSTRUMENTS
from pipeline.live_loop import run_live_loop

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("symbols", nargs="*", default=list(INSTRUMENTS.keys()))
    args = parser.parse_args()
    logging.info("Starting live loop for %s (Ctrl+C to stop)", args.symbols)
    run_live_loop(args.symbols)


if __name__ == "__main__":
    main()
