import pytest

from market_transition.models import ContributingFactor
from market_transition.scoring import MIN_ANALOGS
from market_transition.verdict import (
    classify_transition_risk_tier,
    compute_expected_move_range,
    compute_verdict,
    percentile_rank,
    reshape_drivers,
)


def test_insufficient_evidence_when_too_few_analogs():
    assert compute_verdict(MIN_ANALOGS - 1, 0.6, 0.2, 0.2, []) == "INSUFFICIENT_EVIDENCE"


def test_conflicted_overrides_a_clean_looking_probability_split():
    # Even a decisive-looking 70/15/15 split must not be trusted when
    # there's contradicting evidence -- per the spec's explicit priority.
    assert compute_verdict(20, 0.70, 0.15, 0.15, ["Bearish price but Put OI concentration is increasing"]) == "CONFLICTED"


def test_no_clear_edge_when_probabilities_are_too_close():
    assert compute_verdict(20, 0.36, 0.34, 0.30, []) == "NO_CLEAR_EDGE"


def test_down_verdict_on_a_decisive_clean_read():
    # signature is (n_analogs, probability_up, probability_down, probability_flat, contradictions)
    assert compute_verdict(37, 0.17, 0.68, 0.15, []) == "DOWN"


def test_up_verdict_on_a_decisive_clean_read():
    assert compute_verdict(37, 0.68, 0.17, 0.15, []) == "UP"


def test_no_material_move_verdict_on_a_decisive_clean_read():
    assert compute_verdict(37, 0.15, 0.15, 0.70, []) == "NO_MATERIAL_MOVE"


def test_expected_move_range_empty_for_no_data():
    assert compute_expected_move_range([]) == (None, None)


def test_expected_move_range_single_value():
    assert compute_expected_move_range([-100.0]) == (-100.0, -100.0)


def test_expected_move_range_is_a_low_high_pair_from_quartiles():
    moves = [-160.0, -140.0, -120.0, -110.0, -95.0, -80.0, -50.0, -30.0]
    low, high = compute_expected_move_range(moves)
    assert low is not None and high is not None
    assert low < high
    assert low >= min(moves)
    assert high <= max(moves)


def test_percentile_rank_none_for_empty_population():
    assert percentile_rank(100.0, []) is None


def test_percentile_rank_reflects_relative_position():
    population = [10.0, 20.0, 30.0, 40.0, 50.0]
    assert percentile_rank(50.0, population) == 100.0
    assert percentile_rank(10.0, population) == 20.0


def test_transition_risk_tier_none_without_atr_or_magnitude():
    assert classify_transition_risk_tier(None, 100.0) is None
    assert classify_transition_risk_tier(150.0, None) is None
    assert classify_transition_risk_tier(150.0, 0.0) is None


def test_transition_risk_tier_boundaries_match_phase_7a_thresholds():
    atr = 100.0
    assert classify_transition_risk_tier(40.0, atr) == "NORMAL"     # 0.4x ATR
    assert classify_transition_risk_tier(60.0, atr) == "MODERATE"   # 0.6x ATR
    assert classify_transition_risk_tier(150.0, atr) == "LARGE"     # 1.5x ATR
    assert classify_transition_risk_tier(250.0, atr) == "EXTREME"   # 2.5x ATR


def test_reshape_drivers_takes_top_three_by_existing_rank():
    factors = [
        ContributingFactor(factor_name="Sell volume acceleration", today_value="1.8", note="n/a", contribution=-0.9),
        ContributingFactor(factor_name="POC migration", today_value="-50", note="n/a", contribution=-0.7),
        ContributingFactor(factor_name="Call OI build-up", today_value="high", note="n/a", contribution=-0.5),
        ContributingFactor(factor_name="Fourth factor", today_value="x", note="n/a", contribution=0.1),
    ]
    primary, secondary, tertiary, contradictory = reshape_drivers(factors, ["Put OI increasing"])
    assert primary == "Sell volume acceleration"
    assert secondary == "POC migration"
    assert tertiary == "Call OI build-up"
    assert contradictory == ["Put OI increasing"]


def test_reshape_drivers_handles_fewer_than_three_factors():
    primary, secondary, tertiary, _ = reshape_drivers([], [])
    assert primary is None and secondary is None and tertiary is None
