"""Auto-repeating live snapshot loop for market hours (09:15-15:30 IST, every 1 min).

Usage: venv\\Scripts\\python.exe scripts\\run_live_loop.py [SENSEX NIFTY ...] [--single-session]

Without --single-session, runs until interrupted (Ctrl+C), sleeping through
nights/weekends/holidays in the same process. With --single-session, exits as
soon as today's session ends (or immediately on a non-trading day) -- this is
the mode the "SensexNifty-LiveLoop" Windows Task Scheduler task uses, since it
starts a fresh process every trading morning.
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
    parser.add_argument(
        "--single-session",
        action="store_true",
        help="Exit once today's session ends (or immediately on a non-trading day) "
        "instead of sleeping through the night to the next open. Use this for a "
        "scheduler (e.g. Windows Task Scheduler) that starts a fresh process each "
        "trading morning.",
    )
    args = parser.parse_args()
    logging.info("Starting live loop for %s (Ctrl+C to stop)", args.symbols)
    run_live_loop(args.symbols, run_single_session=args.single_session)


if __name__ == "__main__":
    main()
