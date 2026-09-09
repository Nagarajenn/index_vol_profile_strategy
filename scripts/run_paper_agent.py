"""Milestone 11D paper trading agent -- one tick.

PAPER MODE. Simulated only. This script cannot place a real order: it
never imports a broker client, and its only execution path is
paper_trading.broker.PaperBroker (an arithmetic simulator).

Called every minute by pipeline/live_loop.py after run_snapshot has
persisted that minute's candles and option chain, so it works purely off
data already in Postgres and makes no external API calls of its own.

Usage (manual):
    venv/Scripts/python.exe scripts/run_paper_agent.py [--symbols NIFTY SENSEX]
    venv/Scripts/python.exe scripts/run_paper_agent.py --kill-switch on
"""

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: F401 -- truststore bootstrap, must precede any DB call
from config.settings import IST
from paper_trading import journal
from paper_trading.config import DEFAULT_CONFIG
from paper_trading.tick import run_tick

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", nargs="+", default=list(DEFAULT_CONFIG.symbols))
    parser.add_argument("--kill-switch", choices=["on", "off"],
                        help="Stop/allow NEW paper entries. Never deletes records; an open "
                             "position is still managed to a safe exit under the configured rules.")
    args = parser.parse_args()

    now = datetime.now(IST)
    if args.kill_switch:
        active = args.kill_switch == "on"
        journal.set_agent_state(now.date(), "RISK_BLOCKED" if active else "MARKET_MONITORING",
                                DEFAULT_CONFIG.config_hash(), heartbeat=now, kill_switch=active)
        print(f"Paper engine kill switch {'ACTIVATED' if active else 'released'}. No records were deleted.")
        return

    for symbol in args.symbols:
        try:
            result = run_tick(symbol, now, DEFAULT_CONFIG)
            logger.info("%s %s: %s", symbol, result["state"], result["summary"])
        except Exception:
            logger.exception("Paper agent tick failed for %s", symbol)


if __name__ == "__main__":
    main()
