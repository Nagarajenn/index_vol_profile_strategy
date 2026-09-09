"""Milestone 11C: Option Opportunity Engine orchestrator.

RESEARCH ONLY. Read-only against Postgres (raw_candles, option_chain_raw).
Writes nothing to the database. No Dhan order-placement API is imported
or called anywhere in this module or anything it calls.

Reuses, unmodified: db.reader (candle/option-chain accessors),
market_transition.direction_baseline (the FROZEN Milestone 11A control --
predict_row, never re-fit here), option_chain.snapshot_features
(extract_atm_window). New orchestration only.

Usage: venv\\Scripts\\python.exe scripts\\run_milestone11c.py
"""

import json
import pickle
import sys
from dataclasses import asdict
from functools import partial
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: F401 -- truststore bootstrap
import pandas as pd

from config.instruments import INSTRUMENTS
from config.settings import CACHE_DIR
from db import reader as db_reader
from market_transition.direction_baseline import predict_row
from market_transition.option_features_11c import (
    build_candidate_universe,
    build_post_cutoff_option_trajectory,
    compute_realized_option_outcome,
    compute_underlying_outcome,
)
from market_transition.option_opportunity_11c import (
    fit_expected_move_points,
    select_atm_baseline,
    select_candidate,
    select_nearest_itm_baseline,
    select_nearest_otm_baseline,
)
from market_transition.option_evaluator_11c import evaluate_baseline, evaluate_engine

DATASET_PATH = CACHE_DIR / "milestone11a_direction_dataset_v1.pkl"
OUT_VERSION = "milestone11c_option_opportunity_v1"


def _confidence_tier(votes: dict) -> str:
    up = sum(1 for v in votes.values() if v == "up")
    down = sum(1 for v in votes.values() if v == "down")
    return f"{max(up, down)}-{min(up, down)}"


def _moneyness_bucket(offset: int) -> str:
    if offset == 0:
        return "ATM"
    return f"{'OTM' if offset > 0 else 'ITM'}_{abs(offset)}"


class _CachedOptionLookup:
    """Memoizes db.reader.get_option_chain_raw_near by exact time string
    for one symbol-day, so building 4 candidates' post-cutoff trajectories
    (selected + 3 baselines) costs 16 DB queries total, not 64."""

    def __init__(self, symbol, session_date):
        self.symbol, self.session_date = symbol, session_date
        self._cache: dict[str, dict | None] = {}

    def __call__(self, at_or_before: str):
        if at_or_before not in self._cache:
            self._cache[at_or_before] = db_reader.get_option_chain_raw_near(self.symbol, self.session_date, at_or_before=at_or_before)
        return self._cache[at_or_before]


def _outcome_for(candidate, lookup) -> dict | None:
    if candidate is None or candidate.ask is None or not candidate.ask:
        return None
    trajectory = build_post_cutoff_option_trajectory(candidate.strike, candidate.option_type, lookup)
    return compute_realized_option_outcome(candidate.ask, trajectory)


def build_records(df: pd.DataFrame, control_thresholds: dict, expected_move_by_symbol: dict) -> list[dict]:
    records = []
    for row in df[df["baseline_usable"]].to_dict("records"):
        symbol, session_date, tier = row["symbol"], row["session_date"], row["tier"]
        step = INSTRUMENTS[symbol]["round_number_step"]

        pred = predict_row(row, control_thresholds)
        direction_state = pred["prediction"]
        confidence_tier = _confidence_tier(pred["votes"]) if pred["votes"] else None

        candles = db_reader.load_raw_candles(symbol, start_date=session_date, end_date=session_date)
        if candles.empty:
            continue
        candles["timestamp"] = pd.to_datetime(candles["timestamp"]).dt.tz_convert("Asia/Kolkata")
        candles["time"] = candles["timestamp"].dt.time
        underlying_outcome = compute_underlying_outcome(candles)

        option_at_1459 = db_reader.get_option_chain_raw_near(symbol, session_date, at_or_before="14:59:00")
        candidates, rejection = build_candidate_universe(symbol, session_date, option_at_1459, strike_step=step)

        selection = select_candidate(candidates, rejection, direction_state, expected_move_by_symbol.get(symbol))
        atm_bl = select_atm_baseline(candidates, direction_state)
        otm_bl = select_nearest_otm_baseline(candidates, direction_state)
        itm_bl = select_nearest_itm_baseline(candidates, direction_state)

        lookup = _CachedOptionLookup(symbol, session_date)
        selected_outcome = _outcome_for(selection.selected, lookup) if selection.selected else None
        atm_outcome = _outcome_for(atm_bl, lookup)
        otm_outcome = _outcome_for(otm_bl, lookup)
        itm_outcome = _outcome_for(itm_bl, lookup)

        record = {
            "symbol": symbol, "session_date": session_date, "tier": tier,
            "direction_state": direction_state, "confidence_tier": confidence_tier,
            "expiry_type": row.get("expiry_type"),
            "underlying_direction": underlying_outcome["direction"],
            "underlying_final_move": underlying_outcome["final_move"],
            "candidate_universe_size": len(candidates),
            "universe_rejection_reason": rejection,
            "selection_reason": selection.reason,
            "selected_option_type": selection.selected.option_type if selection.selected else None,
            "selected_strike": selection.selected.strike if selection.selected else None,
            "selected_moneyness_bucket": _moneyness_bucket(selection.selected.atm_offset) if selection.selected else None,
            "selected_spread_pct": selection.selected.spread_pct if selection.selected else None,
            "selected_score": selection.scored.score if selection.scored else None,
            "outcome": selected_outcome,
            "baseline_atm": atm_outcome,
            "baseline_nearest_otm": otm_outcome,
            "baseline_nearest_itm": itm_outcome,
        }
        records.append(record)
    return records


def main():
    with open(DATASET_PATH, "rb") as f:
        saved = pickle.load(f)
    df = saved["rows"]
    control_thresholds = saved["thresholds"]

    training_rows = df[(df["tier"] == "training") & (df["baseline_usable"])].to_dict("records")
    expected_move_by_symbol = {
        symbol: fit_expected_move_points(training_rows, symbol) for symbol in INSTRUMENTS
    }

    records = build_records(df, control_thresholds, expected_move_by_symbol)

    by_tier = {t: [r for r in records if r["tier"] == t] for t in ("training", "validation", "test")}
    engine_results = {t: evaluate_engine(rs) for t, rs in by_tier.items()}
    baseline_results = {
        t: {
            "atm": evaluate_baseline(rs, "baseline_atm"),
            "nearest_otm": evaluate_baseline(rs, "baseline_nearest_otm"),
            "nearest_itm": evaluate_baseline(rs, "baseline_nearest_itm"),
        }
        for t, rs in by_tier.items()
    }

    report = {
        "dataset_version": OUT_VERSION,
        "source_dataset": saved.get("feature_version"),
        "expected_move_points_by_symbol": expected_move_by_symbol,
        "spread_pct_max_gate": 5.0,
        "n_days_by_tier": {t: len(rs) for t, rs in by_tier.items()},
        "engine": engine_results,
        "baselines": baseline_results,
    }

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    report_path = CACHE_DIR / f"{OUT_VERSION}_report.json"
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2, default=str)

    records_path = CACHE_DIR / f"{OUT_VERSION}_records.json"
    with open(records_path, "w") as f:
        json.dump(records, f, indent=2, default=str)

    print(json.dumps(report, indent=2, default=str))
    print(f"\nReport saved to {report_path}")
    print(f"Per-symbol-day records saved to {records_path}")


if __name__ == "__main__":
    main()
