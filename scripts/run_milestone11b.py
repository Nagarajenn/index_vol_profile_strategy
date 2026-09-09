"""Milestone 11B: evaluates every incremental candidate feature (Section 7-13)
against the FROZEN Milestone 11A control, using the exact frozen chronological
split and the exact frozen control thresholds Milestone 11A already produced.

RESEARCH ONLY. Reuses data/cache/milestone11a_direction_dataset_v1.pkl
(regenerated once, additively, to also carry `opt_*_position_classification`
-- verified byte-identical control Validation/Test results before and after
that addition). No new DB reads. No production code touched.

Every candidate's Training-only threshold is fixed before this script looks
at Validation or Test -- both are then evaluated in one locked pass and
reported for every candidate (Section 17/27 require full Validation+Test
metrics per feature); nothing is re-tuned after any result is observed, so
this is not iterative Test-optimization.

Usage: venv\\Scripts\\python.exe scripts\\run_milestone11b.py
"""

import json
import pickle
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: F401 -- truststore bootstrap (unused here, kept for import-order consistency)
from config.settings import CACHE_DIR
from market_transition.direction_baseline import evaluate as evaluate_control
from market_transition.direction_features_11b import (
    ALL_VOTE_CANDIDATES,
    divergence_analysis,
    evaluate_candidate,
    expiry_regime_analysis,
    fit_underlying_thresholds,
)

DATASET_PATH = CACHE_DIR / "milestone11a_direction_dataset_v1.pkl"
OUT_VERSION = "milestone11b_incremental_features_v1"


def _strip_audit(d: dict) -> dict:
    return {k: v for k, v in d.items() if k != "audit"}


def main():
    with open(DATASET_PATH, "rb") as f:
        saved = pickle.load(f)
    df = saved["rows"]
    control_thresholds = saved["thresholds"]  # the EXACT frozen Milestone 11A thresholds -- never recomputed here

    training_rows = df[(df["tier"] == "training") & (df["baseline_usable"])].to_dict("records")
    validation_rows = df[(df["tier"] == "validation") & (df["baseline_usable"])].to_dict("records")
    test_rows = df[(df["tier"] == "test") & (df["baseline_usable"])].to_dict("records")

    control_validation = evaluate_control(validation_rows, control_thresholds)
    control_test = evaluate_control(test_rows, control_thresholds)

    scorecard = []
    audits = {}
    for candidate in ALL_VOTE_CANDIDATES:
        params = candidate.fit_fn(training_rows)
        validation_result = evaluate_candidate(validation_rows, control_thresholds, candidate, params)
        test_result = evaluate_candidate(test_rows, control_thresholds, candidate, params)

        survives_validation = (
            validation_result["accuracy"] is not None
            and validation_result["control_accuracy"] is not None
            and validation_result["accuracy"] > validation_result["control_accuracy"]
        )

        scorecard.append({
            "name": candidate.name,
            "description": candidate.description,
            "rationale": candidate.rationale,
            "training_params": params,
            "validation": _strip_audit(validation_result),
            "test": _strip_audit(test_result),
            "survives_validation": survives_validation,
        })
        audits[candidate.name] = validation_result["audit"] + test_result["audit"]

    underlying_thresholds = fit_underlying_thresholds(training_rows)
    divergence_rows = validation_rows + test_rows
    divergence = divergence_analysis(divergence_rows, control_thresholds, underlying_thresholds)

    expiry = expiry_regime_analysis(divergence_rows, control_thresholds)

    report = {
        "dataset_version": OUT_VERSION,
        "source_dataset": saved.get("feature_version"),
        "control_thresholds": control_thresholds,
        "training_n": len(training_rows),
        "validation_n": len(validation_rows),
        "test_n": len(test_rows),
        "control": {
            "validation": _strip_audit(control_validation),
            "test": _strip_audit(control_test),
        },
        "underlying_diagnostic_thresholds": underlying_thresholds,
        "scorecard": scorecard,
        "divergence_analysis": {
            "agree": divergence["agree"], "disagree": divergence["disagree"],
        },
        "expiry_regime_analysis": expiry,
    }

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    report_path = CACHE_DIR / f"{OUT_VERSION}_report.json"
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2, default=str)

    audit_path = CACHE_DIR / f"{OUT_VERSION}_audits.json"
    with open(audit_path, "w") as f:
        json.dump(audits, f, indent=2, default=str)

    divergence_detail_path = CACHE_DIR / f"{OUT_VERSION}_divergence_detail.json"
    with open(divergence_detail_path, "w") as f:
        json.dump(divergence["detail"], f, indent=2, default=str)

    print(json.dumps(report, indent=2, default=str))
    print(f"\nReport saved to {report_path}")
    print(f"Per-candidate audits saved to {audit_path}")
    print(f"Divergence detail saved to {divergence_detail_path}")


if __name__ == "__main__":
    main()
