"""Milestone 11C tests: opportunity scoring, NO-TRADE gates, deterministic
ranking, baseline selectors, and the Training-only expected-move fit.
"""

from datetime import date

import pytest

from market_transition.option_features_11c import CandidateOption
from market_transition.option_opportunity_11c import (
    SPREAD_PCT_MAX,
    compute_opportunity_score,
    estimate_theta_cost_15min,
    fit_expected_move_points,
    select_atm_baseline,
    select_candidate,
    select_nearest_itm_baseline,
    select_nearest_otm_baseline,
)


def _candidate(strike=100.0, option_type="CE", offset=0, delta=0.5, theta=-10.0, ask=10.0, bid=9.5, quality="GOOD", moneyness=0.0):
    spread = (ask - bid) if (ask is not None and bid is not None) else None
    spread_pct = (spread / ask * 100) if (spread is not None and ask) else None
    return CandidateOption(
        symbol="NIFTY", session_date=date(2026, 8, 10), expiry=date(2026, 8, 13),
        strike=strike, option_type=option_type, atm_offset=offset, moneyness=moneyness,
        underlying_price=100.0, timestamp=None, ltp=ask, bid=bid, ask=ask, spread=spread, spread_pct=spread_pct,
        volume=1000, oi=1000, oi_change=0, iv=15.0, delta=delta, gamma=0.001, theta=theta, vega=5.0,
        data_quality=quality,
    )


# --------------------------------------------------------------- theta/score

def test_estimate_theta_cost_scales_linearly_to_15_minutes():
    cost = estimate_theta_cost_15min(theta=-375.0)  # -375/day -> -1/min * 15min = -15... check formula
    assert cost == pytest.approx(375.0 * 15 / 375)


def test_estimate_theta_cost_none_when_theta_missing():
    assert estimate_theta_cost_15min(None) is None


def test_compute_opportunity_score_basic_formula():
    c = _candidate(delta=0.5, theta=0.0, ask=10.0, bid=9.9)  # spread=0.1
    scored = compute_opportunity_score(c, expected_move_points=100.0)
    assert scored.eligible
    assert scored.expected_benefit == pytest.approx(50.0)  # 0.5*100
    assert scored.score == pytest.approx(50.0 - 0.1)  # minus spread, theta=0


def test_compute_opportunity_score_rejects_missing_quote():
    c = _candidate(ask=None, bid=None, quality="MISSING_QUOTE")
    scored = compute_opportunity_score(c, expected_move_points=100.0)
    assert not scored.eligible
    assert scored.rejection_reason == "MISSING_QUOTE"


def test_compute_opportunity_score_rejects_wide_spread():
    c = _candidate(ask=10.0, bid=10.0 * (1 - (SPREAD_PCT_MAX + 1) / 100))
    scored = compute_opportunity_score(c, expected_move_points=100.0)
    assert not scored.eligible
    assert scored.rejection_reason == "SPREAD_TOO_WIDE"


def test_compute_opportunity_score_rejects_missing_delta_or_expected_move():
    c = _candidate(delta=None)
    assert not compute_opportunity_score(c, expected_move_points=100.0).eligible
    c2 = _candidate(delta=0.5)
    assert not compute_opportunity_score(c2, expected_move_points=None).eligible


# ------------------------------------------------------------- expected move fit

def test_fit_expected_move_points_is_training_only_median_abs_move():
    training_rows = [
        {"symbol": "NIFTY", "actual_15m_point_move": 10.0},
        {"symbol": "NIFTY", "actual_15m_point_move": -20.0},
        {"symbol": "NIFTY", "actual_15m_point_move": 30.0},
        {"symbol": "SENSEX", "actual_15m_point_move": 999.0},  # different symbol, must not leak in
    ]
    assert fit_expected_move_points(training_rows, "NIFTY") == pytest.approx(20.0)  # median(|10|,|20|,|30|)


def test_fit_expected_move_points_none_when_no_data():
    assert fit_expected_move_points([], "NIFTY") is None


# ------------------------------------------------------------------- selection / NO TRADE

def test_select_candidate_no_trade_when_no_clear_edge():
    result = select_candidate([_candidate()], universe_rejection_reason=None, direction_state=None, expected_move_points=100.0)
    assert result.selected is None
    assert result.reason == "NO_TRADE_NO_CLEAR_EDGE"


def test_select_candidate_no_trade_on_universe_rejection():
    result = select_candidate([], universe_rejection_reason="STALE_SNAPSHOT", direction_state="up", expected_move_points=100.0)
    assert result.selected is None
    assert result.reason == "NO_TRADE_DATA_QUALITY_STALE_SNAPSHOT"


def test_select_candidate_no_trade_when_no_eligible_candidate():
    bad = _candidate(option_type="CE", ask=None, bid=None, quality="MISSING_QUOTE")
    result = select_candidate([bad], universe_rejection_reason=None, direction_state="up", expected_move_points=100.0)
    assert result.selected is None
    assert result.reason == "NO_TRADE_NO_ELIGIBLE_CANDIDATE"


def test_select_candidate_no_trade_when_top_score_nonpositive():
    # spread is within the liquidity gate (2%), but a large theta cost
    # plus a tiny expected benefit pushes the net score below zero.
    c = _candidate(option_type="CE", delta=0.01, theta=-300.0, ask=10.0, bid=9.8)
    result = select_candidate([c], universe_rejection_reason=None, direction_state="up", expected_move_points=1.0)
    assert result.selected is None
    assert result.reason == "NO_TRADE_EXPECTED_BENEFIT_NONPOSITIVE"


def test_select_candidate_picks_highest_scoring_matching_leg():
    ce_low = _candidate(strike=100.0, option_type="CE", offset=0, delta=0.5, ask=10.0, bid=9.9)
    ce_high = _candidate(strike=150.0, option_type="CE", offset=1, delta=0.9, ask=10.0, bid=9.9)
    pe = _candidate(strike=100.0, option_type="PE", offset=0, delta=0.5, ask=10.0, bid=9.9)
    result = select_candidate([ce_low, ce_high, pe], universe_rejection_reason=None, direction_state="up", expected_move_points=100.0)
    assert result.selected is ce_high  # higher delta -> higher score, and PE excluded (wrong leg)
    assert result.reason == "SELECTED"


def test_select_candidate_deterministic_tiebreak_by_strike():
    c1 = _candidate(strike=100.0, option_type="CE", offset=0, delta=0.5, ask=10.0, bid=9.9)
    c2 = _candidate(strike=150.0, option_type="CE", offset=1, delta=0.5, ask=10.0, bid=9.9)  # identical score
    result = select_candidate([c2, c1], universe_rejection_reason=None, direction_state="up", expected_move_points=100.0)
    assert result.selected.strike == 100.0  # lower strike wins the tie, deterministically


# ---------------------------------------------------------------------- baselines

def test_atm_baseline_selects_offset_zero_matching_leg():
    ce_atm = _candidate(strike=100.0, option_type="CE", offset=0)
    ce_otm = _candidate(strike=150.0, option_type="CE", offset=1)
    pe_atm = _candidate(strike=100.0, option_type="PE", offset=0)
    assert select_atm_baseline([ce_atm, ce_otm, pe_atm], "up") is ce_atm
    assert select_atm_baseline([ce_atm, ce_otm, pe_atm], "down") is pe_atm
    assert select_atm_baseline([ce_atm, ce_otm, pe_atm], None) is None


def test_nearest_otm_and_itm_baselines_respect_ce_pe_sign_convention():
    ce_itm = _candidate(strike=50.0, option_type="CE", offset=-1)
    ce_atm = _candidate(strike=100.0, option_type="CE", offset=0)
    ce_otm = _candidate(strike=150.0, option_type="CE", offset=1)
    pe_itm = _candidate(strike=150.0, option_type="PE", offset=1)
    pe_otm = _candidate(strike=50.0, option_type="PE", offset=-1)
    candidates = [ce_itm, ce_atm, ce_otm, pe_itm, pe_otm]
    assert select_nearest_otm_baseline(candidates, "up").strike == 150.0   # CE OTM = higher strike
    assert select_nearest_itm_baseline(candidates, "up").strike == 50.0    # CE ITM = lower strike
    assert select_nearest_otm_baseline(candidates, "down").strike == 50.0  # PE OTM = lower strike
    assert select_nearest_itm_baseline(candidates, "down").strike == 150.0  # PE ITM = higher strike
