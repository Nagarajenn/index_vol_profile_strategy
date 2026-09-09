"""Milestone 11A: builds the research dataset (Milestone 10.5 Task 3),
applies the frozen chronological split, fits the frozen Model B baseline's
thresholds on Training ONLY, and reports the out-of-sample Validation and
(locked) Test results.

RESEARCH ONLY. Reads raw_candles / option_chain_raw / transition_actual_outcome;
writes nothing to the database. The only output is a versioned pickle
under data/cache/ (gitignored, regenerable) plus a printed report -- no
production table, schema, API, or UI is touched.

Usage: venv\\Scripts\\python.exe scripts\\run_milestone11a.py
"""

import json
import logging
import pickle
import sys
from dataclasses import asdict
from functools import partial
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: F401 -- truststore bootstrap, must import before any DB/HTTPS call
import pandas as pd

from config.instruments import INSTRUMENTS
from config.settings import CACHE_DIR
from db import reader as db_reader
from market_transition.direction_baseline import (
    BASELINE_FEATURES,
    TEST_RANGE,
    TRAINING_RANGE,
    VALIDATION_RANGE,
    assign_tier,
    evaluate,
    fit_thresholds,
)
from market_transition.direction_dataset import (
    build_pre_cutoff_features,
    build_post_cutoff_outcomes,
    is_baseline_usable,
    merge_pre_post,
)
from market_transition.expiry_calendar import build_expiry_calendar

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

SYMBOLS = ["NIFTY", "SENSEX"]
DATASET_VERSION = "milestone11a_direction_dataset_v1"
FEATURE_VERSION = "v1"


def _option_lookup_fn(symbol, session_date):
    return partial(db_reader.get_option_chain_raw_near, symbol, session_date)


def build_dataset_rows(symbol: str) -> list[dict]:
    """One row per trading day this symbol has ANY underlying candle data
    for, spanning the full stored range -- not just the option-usable
    subset. Rows without usable option data still get a full underlying
    half; `is_baseline_usable()` decides per-row whether the (options-only)
    baseline can be scored on it. Nothing here filters by tier -- tier
    assignment happens after the dataset is built, on session_date alone."""
    bin_size = INSTRUMENTS[symbol]["volume_profile_bin_size"]
    candles = db_reader.load_raw_candles(symbol)
    if candles.empty:
        logger.warning("%s: no raw_candles at all", symbol)
        return []
    candles["timestamp"] = pd.to_datetime(candles["timestamp"]).dt.tz_convert("Asia/Kolkata")
    candles["date"] = candles["timestamp"].dt.date
    candles["time"] = candles["timestamp"].dt.time

    trading_dates = sorted(candles["date"].unique())
    expiry_calendar = build_expiry_calendar(symbol, trading_dates[0], trading_dates[-1])

    rows = []
    for session_date in trading_dates:
        day_candles = candles[candles["date"] == session_date].reset_index(drop=True)
        option_lookup_fn = _option_lookup_fn(symbol, session_date)

        pre = build_pre_cutoff_features(symbol, session_date, day_candles, option_lookup_fn, bin_size, expiry_calendar)
        if pre is None:
            continue
        actual_by_horizon = db_reader.load_actual_outcome_all_horizons(symbol, session_date)
        post = build_post_cutoff_outcomes(actual_by_horizon)
        row = merge_pre_post(pre, post)
        row["feature_version"] = FEATURE_VERSION
        row["tier"] = assign_tier(session_date)
        row["baseline_usable"] = is_baseline_usable(row)
        rows.append(row)
    return rows


def per_day_audit_table(rows: list[dict], thresholds: dict) -> pd.DataFrame:
    from market_transition.direction_baseline import predict_row

    audit = []
    for row in rows:
        if row["tier"] not in ("validation", "test") or not row["baseline_usable"]:
            continue
        result = predict_row(row, thresholds)
        audit.append({
            "symbol": row["symbol"], "session_date": row["session_date"], "tier": row["tier"],
            "pcr_oi": row.get("opt_1459_pcr_oi"), "pcr_oi_threshold": thresholds.get("opt_1459_pcr_oi"),
            "pcr_vote": result["votes"].get("opt_1459_pcr_oi"),
            "call_put_volume_imbalance": row.get("opt_1459_call_put_volume_imbalance"),
            "volume_imbalance_threshold": thresholds.get("opt_1459_call_put_volume_imbalance"),
            "volume_vote": result["votes"].get("opt_1459_call_put_volume_imbalance"),
            "atm_straddle_change": row.get("opt_1459_atm_straddle_change"),
            "straddle_threshold": thresholds.get("opt_1459_atm_straddle_change"),
            "straddle_vote": result["votes"].get("opt_1459_atm_straddle_change"),
            "final_prediction": result["prediction"],
            "actual_direction": row.get("actual_15m_direction"),
            "correct": (result["prediction"] == row.get("actual_15m_direction")) if result["prediction"] else None,
        })
    return pd.DataFrame(audit)


def main():
    all_rows: list[dict] = []
    for symbol in SYMBOLS:
        symbol_rows = build_dataset_rows(symbol)
        logger.info("%s: %d symbol-days built", symbol, len(symbol_rows))
        all_rows.extend(symbol_rows)

    df = pd.DataFrame(all_rows)

    tier_counts = df["tier"].value_counts().to_dict()
    usable_by_tier = df[df["baseline_usable"]]["tier"].value_counts().to_dict()
    excluded = df[~df["baseline_usable"]][["symbol", "session_date", "tier"]].to_dict("records")

    training_rows = df[(df["tier"] == "training") & (df["baseline_usable"])].to_dict("records")
    thresholds = fit_thresholds(training_rows)

    validation_rows = df[(df["tier"] == "validation") & (df["baseline_usable"])].to_dict("records")
    test_rows = df[(df["tier"] == "test") & (df["baseline_usable"])].to_dict("records")

    validation_result = evaluate(validation_rows, thresholds)
    test_result = evaluate(test_rows, thresholds)

    audit_df = per_day_audit_table(df.to_dict("records"), thresholds)

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    dataset_path = CACHE_DIR / f"{DATASET_VERSION}.pkl"
    with open(dataset_path, "wb") as f:
        pickle.dump({"rows": df, "thresholds": thresholds, "feature_version": FEATURE_VERSION}, f)

    report = {
        "dataset_version": DATASET_VERSION,
        "feature_version": FEATURE_VERSION,
        "symbols": SYMBOLS,
        "date_range": [str(df["session_date"].min()), str(df["session_date"].max())] if len(df) else None,
        "training_dates": [str(d) for d in TRAINING_RANGE],
        "validation_dates": [str(d) for d in VALIDATION_RANGE],
        "test_dates": [str(d) for d in TEST_RANGE],
        "total_symbol_days": len(df),
        "tier_counts": tier_counts,
        "baseline_usable_by_tier": usable_by_tier,
        "training_n": len(training_rows),
        "validation_n": len(validation_rows),
        "test_n": len(test_rows),
        "training_thresholds": thresholds,
        "baseline_features": [{"feature": f, "sign": s} for f, s in BASELINE_FEATURES],
        "validation": {k: v for k, v in validation_result.items() if k != "rows"},
        "test": {k: v for k, v in test_result.items() if k != "rows"},
        "excluded_symbol_days": [
            {"symbol": r["symbol"], "session_date": str(r["session_date"]), "tier": r["tier"]} for r in excluded
        ],
    }

    report_path = CACHE_DIR / f"{DATASET_VERSION}_report.json"
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2, default=str)

    audit_path = CACHE_DIR / f"{DATASET_VERSION}_audit.csv"
    audit_df.to_csv(audit_path, index=False)

    print(json.dumps(report, indent=2, default=str))
    print(f"\nDataset saved to {dataset_path}")
    print(f"Report saved to {report_path}")
    print(f"Per-day audit table saved to {audit_path}")


if __name__ == "__main__":
    main()
