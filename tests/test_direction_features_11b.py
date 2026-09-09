"""Milestone 11B tests: trajectory calculations, boundary timestamps, the
14:59 cutoff, no post-15:00 feature access, Training-only threshold
fitting, candidate vote logic, deterministic output, missing-data
behavior, and symbol-specific reporting.
"""

from datetime import date

import pytest

from market_transition.direction_features_11b import (
    ALL_VOTE_CANDIDATES,
    CANDIDATE_IV_SKEW,
    CANDIDATE_PCR_CHANGE,
    CANDIDATE_POSITION_CLASSIFICATION,
    combined_prediction,
    divergence_analysis,
    evaluate_candidate,
    expiry_regime_analysis,
    fit_underlying_thresholds,
    trajectory_late_reversal,
    trajectory_max_excursion,
    trajectory_min_excursion,
    trajectory_monotonicity,
    trajectory_slope,
    trajectory_start_to_end_change,
    trajectory_values,
    underlying_vote,
)
from market_transition.direction_dataset import DECISION_CUTOFF, TRAJECTORY_MINUTES, build_pre_cutoff_features


# ------------------------------------------------------------ trajectory math

def test_trajectory_values_reads_the_10_minute_columns_in_order():
    row = {f"traj_{cp.strftime('%H%M')}_pcr_oi": i for i, cp in enumerate(TRAJECTORY_MINUTES)}
    values = trajectory_values(row, "pcr_oi")
    assert values == list(range(10))


def test_trajectory_slope_is_positive_for_a_rising_series():
    values = [float(i) for i in range(10)]
    assert trajectory_slope(values) == pytest.approx(1.0)


def test_trajectory_slope_is_negative_for_a_falling_series():
    values = [float(10 - i) for i in range(10)]
    assert trajectory_slope(values) == pytest.approx(-1.0)


def test_trajectory_slope_none_when_fewer_than_5_points_present():
    values = [1.0, None, None, 2.0, None, None, None, None, None, None]
    assert trajectory_slope(values) is None


def test_trajectory_slope_ignores_none_gaps_but_keeps_true_index_positions():
    # a slope computed on the present points' own indices, not renumbered
    values = [0.0, None, 2.0, None, 4.0, None, 6.0, None, 8.0, None]
    assert trajectory_slope(values) == pytest.approx(1.0)


def test_trajectory_start_to_end_change():
    values = [10.0] + [None] * 8 + [15.0]
    assert trajectory_start_to_end_change(values) == pytest.approx(5.0)


def test_trajectory_monotonicity_perfectly_monotonic_series():
    values = [float(i) for i in range(10)]
    assert trajectory_monotonicity(values) == pytest.approx(1.0)


def test_trajectory_monotonicity_choppy_series():
    # 9 consecutive steps, alternating +1/-1: 5 up-steps, 4 down-steps -> 5/9
    values = [0.0, 1.0, 0.0, 1.0, 0.0, 1.0, 0.0, 1.0, 0.0, 1.0]
    assert trajectory_monotonicity(values) == pytest.approx(5 / 9)


def test_trajectory_max_and_min_excursion_relative_to_first_value():
    values = [10.0, 12.0, 8.0, 15.0, 9.0, 11.0, 10.0, 10.0, 10.0, 10.0]
    assert trajectory_max_excursion(values) == pytest.approx(5.0)   # 15 - 10
    assert trajectory_min_excursion(values) == pytest.approx(-2.0)  # 8 - 10


def test_trajectory_late_reversal_detects_opposite_signed_halves():
    # rising for the first 7, then falling hard in the last 3
    values = [0, 1, 2, 3, 4, 5, 6, 4, 2, 0]
    assert trajectory_late_reversal(values) is True


def test_trajectory_late_reversal_false_for_a_consistent_trend():
    values = [float(i) for i in range(10)]
    assert trajectory_late_reversal(values) is False


# ------------------------------------------------------------------ combiner

def test_combined_prediction_majority_of_four_votes():
    control_votes = {"a": "up", "b": "up", "c": "down"}
    assert combined_prediction(control_votes, "up") == "up"
    assert combined_prediction(control_votes, "down") is None  # 2-2 tie -> abstain


def test_combined_prediction_ignores_missing_candidate_vote():
    control_votes = {"a": "up", "b": "up", "c": "down"}
    assert combined_prediction(control_votes, None) == "up"  # falls back to control's own 2-1 majority


# ---------------------------------------------------------- candidate fitting

def _training_row(**overrides):
    base = {
        "opt_1459_iv_skew": -1.0, "opt_1459_pcr_oi": 1.0, "opt_1450_pcr_oi": 1.0,
        "opt_1459_call_oi_buildup": 0.0, "opt_1459_put_oi_buildup": 0.0,
        "opt_1459_call_unwinding": 0.0, "opt_1459_put_unwinding": 0.0,
        "opt_1459_position_classification": "NEUTRAL",
    }
    base.update(overrides)
    return base


def test_iv_skew_candidate_threshold_fit_from_training_only():
    training = [_training_row(**{"opt_1459_iv_skew": v}) for v in (-3.0, -2.0, -1.0)]
    params = CANDIDATE_IV_SKEW.fit_fn(training)
    assert params["threshold"] == -2.0


def test_iv_skew_candidate_votes_up_when_below_median_sign_negative():
    threshold = -2.0
    assert CANDIDATE_IV_SKEW.vote_fn(-3.0, {"threshold": threshold}) == "up"
    assert CANDIDATE_IV_SKEW.vote_fn(-1.0, {"threshold": threshold}) == "down"


def test_pcr_change_candidate_value_is_1459_minus_1450():
    row = _training_row(**{"opt_1459_pcr_oi": 1.5, "opt_1450_pcr_oi": 1.0})
    assert CANDIDATE_PCR_CHANGE.value_fn(row) == pytest.approx(0.5)


def test_pcr_change_candidate_none_when_either_side_missing():
    row = _training_row(**{"opt_1459_pcr_oi": None, "opt_1450_pcr_oi": 1.0})
    assert CANDIDATE_PCR_CHANGE.value_fn(row) is None


def test_position_classification_candidate_bullish_bearish_abstain():
    assert CANDIDATE_POSITION_CLASSIFICATION.vote_fn("BULLISH", {}) == "up"
    assert CANDIDATE_POSITION_CLASSIFICATION.vote_fn("BEARISH", {}) == "down"
    assert CANDIDATE_POSITION_CLASSIFICATION.vote_fn("NEUTRAL", {}) is None
    assert CANDIDATE_POSITION_CLASSIFICATION.vote_fn("MIXED", {}) is None
    assert CANDIDATE_POSITION_CLASSIFICATION.vote_fn("RAPIDLY_CHANGING", {}) is None


# -------------------------------------------------------------- evaluate_candidate

def _control_thresholds():
    return {"opt_1459_pcr_oi": 1.0, "opt_1459_call_put_volume_imbalance": 0.0, "opt_1459_atm_straddle_change": 0.0}


def _scoreable_row(symbol, actual, iv_skew, pcr=0.5, imbalance=0.5, straddle_change=5.0):
    return {
        "symbol": symbol, "session_date": date(2026, 8, 24), "tier": "validation",
        "opt_1459_pcr_oi": pcr, "opt_1459_call_put_volume_imbalance": imbalance,
        "opt_1459_atm_straddle_change": straddle_change, "opt_1459_iv_skew": iv_skew,
        "actual_15m_direction": actual,
    }


def test_evaluate_candidate_reports_control_and_candidate_accuracy_side_by_side():
    thresholds = _control_thresholds()
    # control (pcr=0.5<1.0 up, imbalance=0.5>0 up, straddle=5>0 up) -> control predicts up
    rows = [
        _scoreable_row("NIFTY", actual="up", iv_skew=-3.0),    # candidate also votes up (below median) -> both correct
        _scoreable_row("SENSEX", actual="down", iv_skew=-3.0),  # candidate votes up, actual down -> both wrong
    ]
    params = {"threshold": -2.0}
    result = evaluate_candidate(rows, thresholds, CANDIDATE_IV_SKEW, params)
    assert result["control_n"] == 2
    assert result["n"] == 2
    assert result["control_accuracy"] == pytest.approx(0.5)
    assert result["accuracy"] == pytest.approx(0.5)


def test_evaluate_candidate_symbol_breakdown():
    thresholds = _control_thresholds()
    rows = [
        _scoreable_row("NIFTY", actual="up", iv_skew=-3.0),
        _scoreable_row("NIFTY", actual="up", iv_skew=-3.0),
        _scoreable_row("SENSEX", actual="down", iv_skew=-3.0),
    ]
    params = {"threshold": -2.0}
    result = evaluate_candidate(rows, thresholds, CANDIDATE_IV_SKEW, params)
    assert result["by_symbol"]["NIFTY"]["n"] == 2
    assert result["by_symbol"]["SENSEX"]["n"] == 1


def test_evaluate_candidate_skips_rows_missing_actual_or_control_vote():
    thresholds = _control_thresholds()
    rows = [{"symbol": "NIFTY", "session_date": date(2026, 8, 24), "tier": "validation"}]  # nothing populated
    result = evaluate_candidate(rows, thresholds, CANDIDATE_IV_SKEW, {"threshold": -2.0})
    assert result["n"] == 0
    assert result["control_n"] == 0


# ---------------------------------------------------------- divergence/expiry

def test_underlying_vote_uses_frozen_training_only_thresholds():
    training = [
        {"under_1459_dist_from_vwap": v, "under_1459_mom_5min": v, "under_1459_mom_15min": v, "under_1459_poc_migration_15min": v}
        for v in (-1.0, 0.0, 1.0)
    ]
    thresholds = fit_underlying_thresholds(training)
    assert thresholds["under_1459_dist_from_vwap"] == 0.0
    row_above = {"under_1459_dist_from_vwap": 5.0, "under_1459_mom_5min": 5.0, "under_1459_mom_15min": 5.0, "under_1459_poc_migration_15min": 5.0}
    assert underlying_vote(row_above, thresholds) == "up"


def test_divergence_analysis_classifies_agree_and_disagree_days():
    thresholds = _control_thresholds()
    underlying_thresholds = {"under_1459_dist_from_vwap": 0.0, "under_1459_mom_5min": 0.0, "under_1459_mom_15min": 0.0, "under_1459_poc_migration_15min": 0.0}
    agree_row = {
        **_scoreable_row("NIFTY", actual="up", iv_skew=-3.0),
        "under_1459_dist_from_vwap": 5.0, "under_1459_mom_5min": 5.0, "under_1459_mom_15min": 5.0, "under_1459_poc_migration_15min": 5.0,
    }
    disagree_row = {
        **_scoreable_row("SENSEX", actual="down", iv_skew=-3.0),
        "under_1459_dist_from_vwap": -5.0, "under_1459_mom_5min": -5.0, "under_1459_mom_15min": -5.0, "under_1459_poc_migration_15min": -5.0,
    }
    result = divergence_analysis([agree_row, disagree_row], thresholds, underlying_thresholds)
    assert result["agree"]["n"] == 1
    assert result["disagree"]["n"] == 1


def test_expiry_regime_reports_insufficient_data_below_threshold():
    thresholds = _control_thresholds()
    rows = [{**_scoreable_row("NIFTY", actual="up", iv_skew=-3.0), "expiry_type": "monthly"}]
    result = expiry_regime_analysis(rows, thresholds, min_n_per_class=2)
    assert result["status"] == "INSUFFICIENT_DATA"
    assert result["counts"]["monthly"] == 1
    assert result["counts"]["weekly"] == 0


# -------------------------------------------------------------- registry sanity

def test_all_candidates_are_registered_and_named_uniquely():
    names = [c.name for c in ALL_VOTE_CANDIDATES]
    assert len(names) == len(set(names))
    assert len(names) == 11


# ------------------------------------------------------- leakage (Section 23)

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


def _leak_checking_option_lookup(at_or_before: str):
    assert at_or_before <= DECISION_CUTOFF.strftime("%H:%M:%S"), f"leakage: requested {at_or_before}"
    if at_or_before < "09:15:00":
        return None
    return {"fetched_at": None, "expiry": date(2026, 8, 13), "spot": 100.0, "raw_payload": _payload()}


def _underlying_candles():
    from tests.fixtures.synthetic_candles import make_candles
    rows, price = [], 100.0
    for hh, mm_range in [(9, range(15, 60)), (10, range(60)), (11, range(60)), (12, range(60)), (13, range(60)), (14, range(60))]:
        for mm in mm_range:
            price += 0.05
            rows.append({"time": f"{hh:02d}:{mm:02d}", "o": price, "h": price + 0.3, "l": price - 0.3, "c": price, "v": 100 + mm})
    return make_candles(rows, tz_date="2026-08-10")


def test_trajectory_derived_candidates_never_read_past_1459():
    """End-to-end: build a real pre-cutoff row via direction_dataset (whose
    option_lookup_fn raises on any request past 14:59:00), then confirm
    every trajectory-derived candidate value computes successfully from
    it -- proving the whole pipeline, not just the pure math functions in
    isolation, never touches post-cutoff data."""
    row = build_pre_cutoff_features("NIFTY", date(2026, 8, 10), _underlying_candles(), _leak_checking_option_lookup, bin_size=1.0)
    assert row is not None
    for candidate in ALL_VOTE_CANDIDATES:
        # value_fn must not raise and must be computable purely from the
        # pre-cutoff row -- no additional data source is ever consulted.
        candidate.value_fn(row)


def test_trajectory_values_bit_identical_regardless_of_row_extra_keys():
    """A stray extra key on the row (simulating some future post-cutoff
    column existing on the same dict) must never change a trajectory
    value -- trajectory_values only ever reads its own traj_* keys."""
    row = {f"traj_{cp.strftime('%H%M')}_pcr_oi": float(i) for i, cp in enumerate(TRAJECTORY_MINUTES)}
    baseline = trajectory_values(row, "pcr_oi")
    row_with_extra = dict(row, actual_15m_direction="up", actual_15m_point_move=999.0)
    assert trajectory_values(row_with_extra, "pcr_oi") == baseline


def test_deterministic_output_same_inputs_same_result():
    thresholds = _control_thresholds()
    rows = [_scoreable_row("NIFTY", actual="up", iv_skew=-3.0), _scoreable_row("SENSEX", actual="down", iv_skew=-1.0)]
    params = {"threshold": -2.0}
    r1 = evaluate_candidate(rows, thresholds, CANDIDATE_IV_SKEW, params)
    r2 = evaluate_candidate(rows, thresholds, CANDIDATE_IV_SKEW, params)
    assert {k: v for k, v in r1.items() if k != "audit"} == {k: v for k, v in r2.items() if k != "audit"}
