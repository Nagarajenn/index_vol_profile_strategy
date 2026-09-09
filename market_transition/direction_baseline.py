"""Milestone 11A frozen baseline -- the exact Milestone 10 Model B
(options-only) 3-feature median-split majority vote, corrected for the
one leakage bug Milestone 10.5 identified: thresholds must be fit from
Training-tier data only, never from the full sample.

This module is deliberately inert with respect to everything Milestone
10.5 listed as "not yet" (IV skew, trajectory, divergence, k-NN, ML,
strike selection, opportunity scoring) -- BASELINE_FEATURES below is the
whole model, and nothing in this file may be extended without a new,
separately-reviewed milestone.
"""

from datetime import date
from typing import Literal

Vote = Literal["up", "down"]

# Exact chronological split from Milestone 10.5 / this milestone's brief.
# Inclusive on both ends. Any session_date outside all three ranges is
# "excluded" -- not silently folded into the nearest tier.
TRAINING_RANGE = (date(2026, 8, 3), date(2026, 8, 21))
VALIDATION_RANGE = (date(2026, 8, 24), date(2026, 8, 31))
TEST_RANGE = (date(2026, 9, 1), date(2026, 9, 4))

Tier = Literal["training", "validation", "test", "excluded"]


def assign_tier(session_date: date) -> Tier:
    if TRAINING_RANGE[0] <= session_date <= TRAINING_RANGE[1]:
        return "training"
    if VALIDATION_RANGE[0] <= session_date <= VALIDATION_RANGE[1]:
        return "validation"
    if TEST_RANGE[0] <= session_date <= TEST_RANGE[1]:
        return "test"
    return "excluded"


# (feature column, vote sign). Sign +1: vote UP when value > median.
# Sign -1: vote UP when value < median. Column names match
# market_transition.direction_dataset's `opt_1459_*` flattening of the
# 14:59 checkpoint -- the exact Milestone 10 Model B features, frozen.
BASELINE_FEATURES: tuple[tuple[str, int], ...] = (
    ("opt_1459_pcr_oi", -1),
    ("opt_1459_call_put_volume_imbalance", 1),
    ("opt_1459_atm_straddle_change", 1),
)


def fit_thresholds(training_rows: list[dict]) -> dict[str, float]:
    """Median of each baseline feature over `training_rows` ONLY. Callers
    must pass exactly the Training-tier, baseline-usable rows -- this
    function does not filter by tier or usability itself, so it cannot
    silently include a Validation/Test row if the caller passes one by
    mistake (that's covered by a dedicated leakage test instead of a
    runtime guard, per this module's mandate to be simple and inspectable)."""
    thresholds = {}
    for feature, _ in BASELINE_FEATURES:
        values = sorted(r[feature] for r in training_rows if r.get(feature) is not None)
        if not values:
            continue
        n = len(values)
        mid = n // 2
        thresholds[feature] = values[mid] if n % 2 else (values[mid - 1] + values[mid]) / 2
    return thresholds


def predict_row(row: dict, thresholds: dict[str, float]) -> dict:
    """Per-feature vote plus the final majority prediction. `thresholds`
    must come from fit_thresholds(training_rows) -- this function applies
    them, it never recomputes them from `row` or any other rows, so a
    Validation/Test row can never influence its own threshold."""
    votes: dict[str, Vote] = {}
    for feature, sign in BASELINE_FEATURES:
        value = row.get(feature)
        threshold = thresholds.get(feature)
        if value is None or threshold is None:
            continue
        above = value > threshold
        up = above if sign > 0 else not above
        votes[feature] = "up" if up else "down"

    up_votes = sum(1 for v in votes.values() if v == "up")
    down_votes = sum(1 for v in votes.values() if v == "down")
    prediction: Vote | None = None
    if up_votes or down_votes:
        prediction = "up" if up_votes > down_votes else "down"

    return {
        "votes": votes,
        "up_votes": up_votes,
        "down_votes": down_votes,
        "prediction": prediction,
    }


def evaluate(rows: list[dict], thresholds: dict[str, float], actual_field: str = "actual_15m_direction") -> dict:
    """Scores every row in `rows` against `thresholds` (fit elsewhere, on
    Training only) and the row's own `actual_field`. Rows with a missing
    or non-directional (e.g. "flat") actual outcome, or an unscoreable
    prediction (a required baseline feature missing), are excluded from
    accuracy and reported separately -- never dropped silently."""
    scored = []
    skipped_missing_actual = 0
    skipped_no_prediction = 0

    for row in rows:
        actual = row.get(actual_field)
        if actual not in ("up", "down"):
            skipped_missing_actual += 1
            continue
        result = predict_row(row, thresholds)
        if result["prediction"] is None:
            skipped_no_prediction += 1
            continue
        scored.append({
            "symbol": row.get("symbol"), "session_date": row.get("session_date"),
            "prediction": result["prediction"], "actual": actual,
            "correct": result["prediction"] == actual, "votes": result["votes"],
        })

    n = len(scored)
    correct = sum(1 for s in scored if s["correct"])
    actual_up = sum(1 for s in scored if s["actual"] == "up")
    actual_down = sum(1 for s in scored if s["actual"] == "down")
    predicted_up = sum(1 for s in scored if s["prediction"] == "up")
    predicted_down = sum(1 for s in scored if s["prediction"] == "down")

    tp_up = sum(1 for s in scored if s["prediction"] == "up" and s["actual"] == "up")
    tp_down = sum(1 for s in scored if s["prediction"] == "down" and s["actual"] == "down")
    fp_up = sum(1 for s in scored if s["prediction"] == "up" and s["actual"] == "down")
    fp_down = sum(1 for s in scored if s["prediction"] == "down" and s["actual"] == "up")

    up_precision = (tp_up / predicted_up) if predicted_up else None
    down_precision = (tp_down / predicted_down) if predicted_down else None
    majority_class_accuracy = (max(actual_up, actual_down) / n) if n else None

    return {
        "n": n,
        "correct": correct,
        "incorrect": n - correct,
        "accuracy": (correct / n) if n else None,
        "actual_up": actual_up,
        "actual_down": actual_down,
        "predicted_up": predicted_up,
        "predicted_down": predicted_down,
        "up_precision": up_precision,
        "down_precision": down_precision,
        "confusion_matrix": {
            "predicted_up_actual_up": tp_up, "predicted_up_actual_down": fp_up,
            "predicted_down_actual_up": fp_down, "predicted_down_actual_down": tp_down,
        },
        "majority_class_accuracy": majority_class_accuracy,
        "skipped_missing_actual": skipped_missing_actual,
        "skipped_no_prediction": skipped_no_prediction,
        "rows": scored,
    }
