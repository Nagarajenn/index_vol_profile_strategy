"""Backtest the current scoring weights against saved snapshots and try a
random-search improvement. This is a scaffold: with only the 60-day
backfill (no live institutional_bias signal, one realized price path) the
result is a starting point for later tuning once more live snapshots
accumulate, not a final answer.

Usage: venv\\Scripts\\python.exe scripts\\run_tune_weights.py SENSEX
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backtest.label_outcomes import label_outcomes
from backtest.load_snapshots import load_snapshots
from backtest.tune_weights import evaluate_weights, random_search
from config.settings import PROJECT_ROOT


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("symbol")
    parser.add_argument("--horizon", type=int, default=30, help="forward-return horizon in minutes")
    parser.add_argument("--trials", type=int, default=300)
    args = parser.parse_args()

    df = load_snapshots(args.symbol)
    if df.empty:
        print(f"No snapshots found for {args.symbol} under vol_pro_snapshot_training/")
        return

    print(f"Loaded {len(df)} snapshots for {args.symbol}")
    labeled = label_outcomes(df, args.symbol)

    with open(PROJECT_ROOT / "config" / "scoring_weights.json") as f:
        base_weights = json.load(f)

    baseline_score = evaluate_weights(labeled, base_weights, args.horizon)
    print(f"Baseline calibration score ({args.horizon}m horizon): {baseline_score:.2f}")

    result = random_search(labeled, base_weights, horizon_min=args.horizon, n_trials=args.trials)
    print(f"Best found score: {result['score']:.2f}")
    print("Candidate weights:", json.dumps(result["weights"], indent=2))
    print("\n(This does NOT overwrite config/scoring_weights.json automatically.)")


if __name__ == "__main__":
    main()
