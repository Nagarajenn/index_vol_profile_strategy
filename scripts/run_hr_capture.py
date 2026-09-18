"""HR-1 High-Resolution Option Intelligence Capture -- standalone process.

DATA CAPTURE ONLY. Independent of pipeline/live_loop.py and 11d-paper-v1:
own process, own WebSocket, own DB connection, hr_* tables only, no REST
calls, no order functionality. Exits immediately on non-trading days;
persists only 14:55:00 <= receive_ts < 15:30:00; hard-stops at 15:35.

Usage:
    venv\\Scripts\\python.exe scripts\\run_hr_capture.py                     # live session (Task Scheduler)
    venv\\Scripts\\python.exe scripts\\run_hr_capture.py --dry-run           # no DB writes, no recording
    venv\\Scripts\\python.exe scripts\\run_hr_capture.py --connectivity-test 45 --universe-date 2026-09-11 --as-of 15:29
"""

import argparse
import json
import logging
import sys
from datetime import date, datetime, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import IST
from hr_capture.config import DEFAULT_HR_CONFIG, LOG_DIR
from hr_capture.runner import connectivity_test, run_capture


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="capture without DB writes or recording")
    parser.add_argument("--connectivity-test", type=float, metavar="SECONDS",
                        help="connect + subscribe for N seconds, count packets, write nothing")
    parser.add_argument("--universe-date", type=date.fromisoformat, help="(connectivity test) date of option_chain_raw to use")
    parser.add_argument("--as-of", type=time.fromisoformat, help="(connectivity test) time of option_chain_raw to use")
    args = parser.parse_args()

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=[logging.StreamHandler(),
                  logging.FileHandler(LOG_DIR / f"hr_capture_{datetime.now(IST):%Y%m%d}.log", encoding="utf-8")],
    )

    if args.connectivity_test:
        universe_date = args.universe_date or datetime.now(IST).date()
        as_of = datetime.combine(universe_date, args.as_of or datetime.now(IST).time(), tzinfo=IST)
        result = connectivity_test(DEFAULT_HR_CONFIG, args.connectivity_test, universe_date, as_of)
        print(json.dumps(result, indent=2, default=str))
        return 0 if result["feed_status"] not in ("FAILED_AUTH", "FAILED_CONNECTION") else 1

    status = run_capture(DEFAULT_HR_CONFIG, dry_run=args.dry_run)
    return 0 if status in ("COMPLETED", "COMPLETED_WITH_GAPS", "NOT_TRADING_DAY", "WINDOW_PASSED") else 1


if __name__ == "__main__":
    raise SystemExit(main())
