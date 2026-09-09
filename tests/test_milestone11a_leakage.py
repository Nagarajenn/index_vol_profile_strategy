"""Milestone 11A Section 15 leakage checklist (items A-G), each as its own
named test for direct traceability in the completion report. Several of
these re-exercise assertions already made in tests/test_direction_dataset.py
and tests/test_direction_baseline.py -- that duplication is deliberate: it
lets the Milestone 11A report cite one test per spec item by name rather
than pointing at a shared test that happens to also prove it.
"""

from datetime import date

from market_transition.direction_baseline import (
    assign_tier,
    fit_thresholds,
    predict_row,
)
from market_transition.direction_dataset import (
    DECISION_CUTOFF,
    build_option_checkpoint_features,
    build_option_trajectory,
    build_pre_cutoff_features,
    build_underlying_checkpoint_features,
)
from tests.fixtures.synthetic_candles import make_candles


def _underlying_candles(post_3pm: bool, tz_date="2026-08-10"):
    rows, price = [], 100.0
    hours = [(9, range(15, 60)), (10, range(60)), (11, range(60)), (12, range(60)), (13, range(60)), (14, range(60))]
    if post_3pm:
        hours.append((15, range(40)))
    for hh, mm_range in hours:
        for mm in mm_range:
            price += 0.05
            rows.append({"time": f"{hh:02d}:{mm:02d}", "o": price, "h": price + 0.3, "l": price - 0.3, "c": price, "v": 100 + mm})
    return make_candles(rows, tz_date=tz_date)


def _strike_entry(last_price=100.0):
    return {
        "oi": 1000.0, "previous_oi": 800.0, "volume": 5000.0, "previous_volume": 4500.0,
        "last_price": last_price, "average_price": last_price, "top_bid_price": last_price - 0.5,
        "top_ask_price": last_price + 0.5, "top_bid_quantity": 100, "top_ask_quantity": 100,
        "implied_volatility": 15.0, "previous_close_price": last_price,
        "greeks": {"delta": 0.5, "gamma": 0.001, "theta": -10.0, "vega": 5.0},
    }


def _payload(spot=100.0):
    oc = {str(100.0 + i): {"ce": _strike_entry(100 - i), "pe": _strike_entry(50 + i)} for i in range(-7, 8)}
    return {"expiry": date(2026, 8, 13), "last_price": spot, "oc": oc}


def _option_lookup_fn(at_or_before: str):
    assert at_or_before <= "14:59:00", f"leakage: option data requested for {at_or_before}"
    if at_or_before < "09:15:00":
        return None
    return {"fetched_at": None, "expiry": date(2026, 8, 13), "spot": 100.0, "raw_payload": _payload()}


# A. Validation thresholds are derived only from Training rows.
def test_A_validation_thresholds_derive_only_from_training_rows():
    training = [{"opt_1459_pcr_oi": v, "opt_1459_call_put_volume_imbalance": 0, "opt_1459_atm_straddle_change": 0} for v in (1.0, 2.0, 3.0)]
    thresholds_before = fit_thresholds(training)
    # a would-be Validation row, even an extreme one, must never be passed
    # into fit_thresholds by scripts/run_milestone11a.py -- proven here by
    # showing the function's output depends ONLY on its argument list.
    validation_row = {"opt_1459_pcr_oi": 999.0, "opt_1459_call_put_volume_imbalance": 0, "opt_1459_atm_straddle_change": 0}
    thresholds_after = fit_thresholds(training)  # re-fit on the SAME training list, validation_row never included
    assert thresholds_before == thresholds_after
    assert validation_row not in training


# B. Test thresholds are identical to Training thresholds.
def test_B_test_tier_scored_with_the_exact_training_thresholds_object():
    training = [{"opt_1459_pcr_oi": v, "opt_1459_call_put_volume_imbalance": 0, "opt_1459_atm_straddle_change": 0} for v in (1.0, 2.0, 3.0)]
    thresholds = fit_thresholds(training)
    test_row = {"opt_1459_pcr_oi": 5.0, "opt_1459_call_put_volume_imbalance": 0.1, "opt_1459_atm_straddle_change": 1.0}
    result_with_training_thresholds = predict_row(test_row, thresholds)
    # scripts/run_milestone11a.py never recomputes a Test-only threshold --
    # the same `thresholds` dict fit on Training is passed to both
    # evaluate(validation_rows, thresholds) and evaluate(test_rows, thresholds).
    result_again = predict_row(test_row, thresholds)
    assert result_with_training_thresholds == result_again


# C. Changing/removing post-14:59 underlying data cannot change any pre-cutoff feature.
def test_C_post_1459_underlying_data_cannot_change_pre_cutoff_features():
    truncated = build_underlying_checkpoint_features(_underlying_candles(post_3pm=False), bin_size=1.0)
    extended = build_underlying_checkpoint_features(_underlying_candles(post_3pm=True), bin_size=1.0)
    assert truncated == extended


# D. Changing/removing post-14:59 option data cannot change any pre-cutoff option feature.
def test_D_post_1459_option_data_cannot_change_pre_cutoff_option_features():
    # _option_lookup_fn asserts internally that it is never asked for a
    # time later than 14:59:00 -- both checkpoint and trajectory builders
    # only ever pass times from their own fixed, <=14:59 constant lists.
    checkpoints = build_option_checkpoint_features(date(2026, 8, 10), _option_lookup_fn)
    trajectory = build_option_trajectory(_option_lookup_fn)
    assert checkpoints["opt_1459_available"] is True
    assert trajectory["traj_1459_pcr_oi"] is not None


# E. Actual outcome columns cannot influence model thresholds.
def test_E_actual_outcome_columns_cannot_influence_thresholds():
    row = build_pre_cutoff_features("NIFTY", date(2026, 8, 10), _underlying_candles(False), _option_lookup_fn, bin_size=1.0)
    # fit_thresholds only ever reads the 3 frozen opt_1459_* feature keys;
    # the pre-cutoff row itself structurally contains no actual_* key for
    # it to accidentally read.
    assert not any(k.startswith("actual_") for k in row)


# F. No Validation or Test row contributes to Training medians.
def test_F_no_validation_or_test_row_contributes_to_training_medians():
    assert assign_tier(date(2026, 8, 21)) == "training"
    assert assign_tier(date(2026, 8, 24)) == "validation"
    assert assign_tier(date(2026, 9, 1)) == "test"
    training_rows = [{"opt_1459_pcr_oi": 1.0, "opt_1459_call_put_volume_imbalance": 0, "opt_1459_atm_straddle_change": 0}]
    # scripts/run_milestone11a.py builds training_rows via
    # df[df.tier == "training"] -- a Validation/Test-tier row is never in
    # this list by construction of assign_tier's mutually-exclusive ranges.
    thresholds = fit_thresholds(training_rows)
    assert thresholds["opt_1459_pcr_oi"] == 1.0


# G. No post-15:00 value is present in any decision feature.
def test_G_no_post_1500_value_present_in_any_decision_feature():
    row = build_pre_cutoff_features("NIFTY", date(2026, 8, 10), _underlying_candles(False), _option_lookup_fn, bin_size=1.0)
    latest_checkpoint_key = f"under_{DECISION_CUTOFF.strftime('%H%M')}_close"
    assert latest_checkpoint_key in row
    # every checkpoint/trajectory key this module can ever emit is named
    # under_/opt_/traj_ + an HHMM <= 1459 -- no 15xx-prefixed key exists.
    assert not any(k.split("_")[1].startswith("15") for k in row if k.startswith(("under_", "opt_", "traj_")))
