"""One-shot manual live snapshot.

Usage: venv\\Scripts\\python.exe scripts\\run_live_snapshot.py [SENSEX|NIFTY ...]
Defaults to both symbols if none given.
"""
import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.instruments import INSTRUMENTS
from decision.decision_card import format_decision_text
from pipeline.run_snapshot import run_snapshot

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("symbols", nargs="*", default=list(INSTRUMENTS.keys()))
    args = parser.parse_args()

    for symbol in args.symbols:
        card = run_snapshot(symbol, mode="live")
        if card is None:
            continue
        print(f"\n=== {symbol} ===")
        print(format_decision_text(card))
        if card.get("chart_path"):
            print(f"chart: {card['chart_path']} (trigger: {card['chart_triggered_by']})")


if __name__ == "__main__":
    main()
