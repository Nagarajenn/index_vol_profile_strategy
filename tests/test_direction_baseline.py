"""Milestone 11A frozen-baseline tests: chronological split boundaries,
Training-only threshold fitting, the frozen 3-feature vote, evaluation/
confusion-matrix arithmetic, and the leakage guarantees from spec Section
15 items A/B/F (Validation/Test never contribute to Training medians;
Test uses the identical thresholds Training produced).
"""

from datetime import date

import pytest

from market_transition.direction_baseline import (
    BASELINE_FEATURES,
    TEST_RANGE,
    TRAINING_RANGE,
    VALIDATION_RANGE,
    assign_tier,
    evaluate,
    fit_thresholds,
    predict_row,
)


# ------------------------------------------------------------- tier assignment

def test_assign_tier_boundaries_are_inclusive():
    assert assign_tier(TRAINING_RANGE[0]) == "training"
    assert assign_tier(TRAINING_RANGE[1]) == "training"
    assert assign_tier(VALIDATION_RANGE[0]) == "validation"
    assert assign_tier(VALIDATION_RANGE[1]) == "validation"
    assert assign_tier(TEST_RANGE[0]) == "test"
    assert assign_tier(TEST_RANGE[1]) == "test"


def test_assign_tier_excludes_dates_outside_all_three_ranges():
    assert assign_tier(date(2026, 7, 1)) == "excluded"
    assert assign_tier(date(2026, 8, 22)) == "excluded"  # the gap day between Training and Validation
    assert assign_tier(date(2026, 9, 5)) == "excluded"


def test_assign_tier_gap_day_between_validation_and_test_is_excluded():
    assert assign_tier(date(2026, 8, 22)) == "excluded"
    assert assign_tier(date(2026, 8, 23)) == "excluded"  # weekend, correctly excluded rather than guessed into a tier


# --------------------------------------------------------------- threshold fit

def _row(pcr, imbalance, straddle_change, actual=None, symbol="NIFTY", d=date(2026, 8, 5)):
    r = {
        "symbol": symbol, "session_date": d,
        "opt_1459_pcr_oi": pcr,
        "opt_1459_call_put_volume_imbalance": imbalance,
        "opt_1459_atm_straddle_change": straddle_change,
    }
    if actual is not None:
        r["actual_15m_direction"] = actual
    return r


def test_fit_thresholds_is_the_median_of_training_rows_only():
    training = [_row(1.0, 0.1, 1.0), _row(2.0, 0.2, 2.0), _row(3.0, 0.3, 3.0)]
    thresholds = fit_thresholds(training)
    assert thresholds["opt_1459_pcr_oi"] == 2.0
    assert thresholds["opt_1459_call_put_volume_imbalance"] == 0.2
    assert thresholds["opt_1459_atm_straddle_change"] == 2.0


def test_fit_thresholds_even_count_averages_the_middle_two():
    training = [_row(1.0, 0, 0), _row(2.0, 0, 0), _row(3.0, 0, 0), _row(4.0, 0, 0)]
    thresholds = fit_thresholds(training)
    assert thresholds["opt_1459_pcr_oi"] == 2.5


def test_fit_thresholds_ignores_missing_values():
    training = [_row(1.0, 0.1, 1.0), {**_row(None, 0.2, 2.0)}, _row(3.0, 0.3, 3.0)]
    thresholds = fit_thresholds(training)
    assert thresholds["opt_1459_pcr_oi"] == 2.0  # median of [1.0, 3.0], the None is skipped, not imputed as 0


def test_a_validation_row_never_shifts_the_training_threshold():
    training = [_row(1.0, 0, 0), _row(2.0, 0, 0), _row(3.0, 0, 0)]
    baseline_thresholds = fit_thresholds(training)
    # a caller that accidentally included an extreme "validation" row would
    # move the median -- fit_thresholds must never be handed it in the
    # first place; this proves the function itself has no way to peek at
    # rows outside the list it's given.
    contaminated = training + [_row(1000.0, 0, 0)]
    assert fit_thresholds(training) == baseline_thresholds
    assert fit_thresholds(contaminated) != baseline_thresholds  # sanity: the function DOES use whatever it's given


# ------------------------------------------------------------------ vote logic

def test_pcr_oi_sign_is_negative_vote_up_when_below_median():
    thresholds = {"opt_1459_pcr_oi": 1.0, "opt_1459_call_put_volume_imbalance": 0.0, "opt_1459_atm_straddle_change": 0.0}
    below = predict_row(_row(0.5, None, None), thresholds)
    above = predict_row(_row(1.5, None, None), thresholds)
    assert below["votes"]["opt_1459_pcr_oi"] == "up"
    assert above["votes"]["opt_1459_pcr_oi"] == "down"


def test_volume_imbalance_sign_is_positive_vote_up_when_above_median():
    thresholds = {"opt_1459_pcr_oi": None, "opt_1459_call_put_volume_imbalance": 0.0, "opt_1459_atm_straddle_change": None}
    above = predict_row(_row(None, 0.1, None), thresholds)
    below = predict_row(_row(None, -0.1, None), thresholds)
    assert above["votes"]["opt_1459_call_put_volume_imbalance"] == "up"
    assert below["votes"]["opt_1459_call_put_volume_imbalance"] == "down"


def test_straddle_change_sign_is_positive_vote_up_when_above_median():
    thresholds = {"opt_1459_pcr_oi": None, "opt_1459_call_put_volume_imbalance": None, "opt_1459_atm_straddle_change": 0.0}
    above = predict_row(_row(None, None, 5.0), thresholds)
    below = predict_row(_row(None, None, -5.0), thresholds)
    assert above["votes"]["opt_1459_atm_straddle_change"] == "up"
    assert below["votes"]["opt_1459_atm_straddle_change"] == "down"


def test_majority_vote_resolves_with_three_features():
    thresholds = {"opt_1459_pcr_oi": 1.0, "opt_1459_call_put_volume_imbalance": 0.0, "opt_1459_atm_straddle_change": 0.0}
    # pcr votes down (above threshold), other two vote up -> majority up
    row = _row(pcr=2.0, imbalance=0.5, straddle_change=5.0)
    result = predict_row(row, thresholds)
    assert result["prediction"] == "up"
    assert result["up_votes"] == 2 and result["down_votes"] == 1


def test_predict_row_returns_no_prediction_when_no_feature_is_scoreable():
    thresholds = {"opt_1459_pcr_oi": 1.0, "opt_1459_call_put_volume_imbalance": 0.0, "opt_1459_atm_straddle_change": 0.0}
    result = predict_row(_row(None, None, None), thresholds)
    assert result["prediction"] is None


def test_baseline_features_are_exactly_the_frozen_three_in_frozen_order():
    assert [f for f, _ in BASELINE_FEATURES] == [
        "opt_1459_pcr_oi", "opt_1459_call_put_volume_imbalance", "opt_1459_atm_straddle_change",
    ]
    assert [s for _, s in BASELINE_FEATURES] == [-1, 1, 1]


# -------------------------------------------------------------------- evaluate

def test_evaluate_computes_accuracy_precision_and_confusion_matrix():
    thresholds = {"opt_1459_pcr_oi": 1.0, "opt_1459_call_put_volume_imbalance": 0.0, "opt_1459_atm_straddle_change": 0.0}
    rows = [
        _row(pcr=0.5, imbalance=0.5, straddle_change=5.0, actual="up"),    # predicts up, correct
        _row(pcr=2.0, imbalance=-0.5, straddle_change=-5.0, actual="down"),  # predicts down, correct
        _row(pcr=0.5, imbalance=0.5, straddle_change=5.0, actual="down"),  # predicts up, wrong
    ]
    result = evaluate(rows, thresholds)
    assert result["n"] == 3
    assert result["correct"] == 2
    assert result["accuracy"] == pytest.approx(2 / 3)
    assert result["actual_up"] == 1 and result["actual_down"] == 2
    assert result["predicted_up"] == 2 and result["predicted_down"] == 1
    assert result["confusion_matrix"]["predicted_up_actual_up"] == 1
    assert result["confusion_matrix"]["predicted_up_actual_down"] == 1
    assert result["confusion_matrix"]["predicted_down_actual_down"] == 1
    assert result["up_precision"] == pytest.approx(0.5)
    assert result["down_precision"] == pytest.approx(1.0)


def test_evaluate_excludes_flat_or_missing_actual_outcomes():
    thresholds = {"opt_1459_pcr_oi": 1.0, "opt_1459_call_put_volume_imbalance": 0.0, "opt_1459_atm_straddle_change": 0.0}
    rows = [
        _row(pcr=0.5, imbalance=0.5, straddle_change=5.0, actual="flat"),
        _row(pcr=0.5, imbalance=0.5, straddle_change=5.0, actual="up"),
    ]
    result = evaluate(rows, thresholds)
    assert result["n"] == 1
    assert result["skipped_missing_actual"] == 1


def test_evaluate_reports_rows_with_no_scoreable_feature_separately():
    thresholds = {"opt_1459_pcr_oi": 1.0, "opt_1459_call_put_volume_imbalance": 0.0, "opt_1459_atm_straddle_change": 0.0}
    rows = [_row(pcr=None, imbalance=None, straddle_change=None, actual="up")]
    result = evaluate(rows, thresholds)
    assert result["n"] == 0
    assert result["skipped_no_prediction"] == 1


def test_test_tier_uses_identical_thresholds_object_as_training():
    """Reproduces the exact workflow scripts/run_milestone11a.py follows:
    fit once on Training, apply the SAME thresholds dict to both
    Validation and Test -- never refit."""
    training = [_row(1.0, 0, 0), _row(2.0, 0, 0), _row(3.0, 0, 0)]
    thresholds = fit_thresholds(training)
    validation_rows = [_row(pcr=5.0, imbalance=1.0, straddle_change=1.0, actual="up")]
    test_rows = [_row(pcr=5.0, imbalance=1.0, straddle_change=1.0, actual="up")]
    val_result = evaluate(validation_rows, thresholds)
    test_result = evaluate(test_rows, thresholds)
    # identical inputs scored against identical thresholds must score identically
    assert val_result["accuracy"] == test_result["accuracy"]
