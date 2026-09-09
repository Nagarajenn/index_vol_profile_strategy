"""The frozen 14:59 decision.

Gate order matters and is fixed, so the NO-TRADE reason a day receives is
always the FIRST thing that disqualified it -- that makes five sessions of
NO-TRADE reasons readable as a distribution rather than an arbitrary pick
among several failures.

Nothing in this module reads a timestamp later than the decision cutoff:
it operates purely on the PaperMarketState handed to it, which
market_state.py built under a <=14:59 clamp. tests/test_paper_leakage.py
proves adding post-14:59 data cannot change the output.

NO TRADE is a first-class success. The agent is never obliged to trade,
and the gates below are the documented, frozen reasons it declines.
"""

from datetime import datetime

from paper_trading.config import CONFIG_VERSION, DECISION_VERSION, STRATEGY_VERSION, PaperConfig
from paper_trading.models import PaperDecision, PaperMarketState
from paper_trading.option_selection import build_paper_candidates, select_option
from paper_trading.risk import build_risk_plan
from paper_trading.trend_assessment import assess_trend

_DIRECTIONAL = {
    "STRONG_UP": "up", "UP": "up", "WEAK_UP": "up",
    "STRONG_DOWN": "down", "DOWN": "down", "WEAK_DOWN": "down",
}
_ACTIONABLE = {"STRONG_UP", "UP", "STRONG_DOWN", "DOWN"}


def _no_trade(state, trend, reason, explanation, config):
    return PaperDecision(
        symbol=state.symbol, session_date=state.session_date, decision_timestamp=state.as_of,
        decision="NO_TRADE", decision_reason=reason, trend_assessment=trend.assessment,
        confidence=trend.confidence, strategy_version=STRATEGY_VERSION,
        decision_version=DECISION_VERSION, configuration_version=CONFIG_VERSION,
        configuration_hash=config.config_hash(), state=state, trend=trend,
        no_trade_reason=reason, explanation=explanation,
    )


def decide(
    state: PaperMarketState, config: PaperConfig, option_at_1459=None, strike_step: float = 50.0,
    account_block_reason: str | None = None, kill_switch: bool = False,
) -> PaperDecision:
    trend = assess_trend(state, max_conflicting=config.max_conflicting_factors)
    why: list[str] = []

    # --- gate 0: operational blocks -----------------------------------
    if kill_switch:
        return _no_trade(state, trend, "KILL_SWITCH_ACTIVE",
                         ["Paper engine kill switch is active -- no new entries"], config)
    if account_block_reason:
        return _no_trade(state, trend, account_block_reason,
                         [f"Risk control blocked a new position: {account_block_reason}"], config)

    # --- gate 1: data sufficiency -------------------------------------
    if state.data_quality == "INSUFFICIENT":
        return _no_trade(state, trend, "INSUFFICIENT_DATA",
                         [f"Market state incomplete: missing {', '.join(state.missing_fields[:6])}"], config)
    if state.option_snapshot_age_sec is not None and state.option_snapshot_age_sec > config.max_snapshot_age_sec:
        return _no_trade(state, trend, "STALE_OPTION_DATA",
                         [f"Option snapshot is {state.option_snapshot_age_sec:.0f}s old at the 14:59 cutoff "
                          f"(limit {config.max_snapshot_age_sec}s) -- refusing to treat it as the 14:59 state"], config)

    # --- gate 2: directional evidence ---------------------------------
    why.extend(trend.supporting_factors)
    if trend.is_conflicted:
        return _no_trade(state, trend, "CONFLICTING_SIGNALS",
                         why + [f"Conflicts: {'; '.join(trend.conflicting_factors)}"], config)
    if trend.assessment not in _ACTIONABLE:
        reason = "MARKET_TOO_FLAT" if trend.assessment == "NEUTRAL" else "NO_CLEAR_DIRECTION"
        return _no_trade(state, trend, reason,
                         why + [f"Trend assessment {trend.assessment} is below the actionable bar "
                                f"(needs UP/STRONG_UP or DOWN/STRONG_DOWN)"], config)
    if trend.confidence < config.min_confidence:
        return _no_trade(state, trend, "LOW_CONFIDENCE",
                         why + [f"Confidence {trend.confidence}/100 is below the frozen minimum "
                                f"{config.min_confidence}/100"], config)
    if len(trend.supporting_factors) < config.min_supporting_factors:
        return _no_trade(state, trend, "NO_CLEAR_DIRECTION",
                         why + [f"Only {len(trend.supporting_factors)} supporting factors "
                                f"(needs {config.min_supporting_factors})"], config)

    direction = _DIRECTIONAL[trend.assessment]

    # --- gate 3: is the expected move worth expressing? ----------------
    expected_move = None
    if state.expected_move_low is not None and state.expected_move_high is not None:
        expected_move = max(abs(state.expected_move_low), abs(state.expected_move_high))
    elif state.atr_14:
        expected_move = state.atr_14 * config.min_expected_move_atr
    if not expected_move:
        return _no_trade(state, trend, "EXPECTED_MOVE_TOO_SMALL",
                         why + ["No expected-move estimate available"], config)
    if state.atr_14 and expected_move < config.min_expected_move_atr * state.atr_14:
        return _no_trade(state, trend, "EXPECTED_MOVE_TOO_SMALL",
                         why + [f"Expected move {expected_move:.0f} pts is under "
                                f"{config.min_expected_move_atr} x ATR ({state.atr_14:.0f})"], config)
    if state.transition_risk_tier in ("EXTREME",):
        return _no_trade(state, trend, "TRANSITION_RISK_TOO_HIGH",
                         why + [f"Transition risk tier {state.transition_risk_tier}"], config)

    # --- gate 4: option availability ----------------------------------
    candidates, rejection = build_paper_candidates(
        state.symbol, state.session_date, option_at_1459, strike_step, config)
    if rejection == "STALE_SNAPSHOT":
        return _no_trade(state, trend, "STALE_OPTION_DATA", why + ["Option chain snapshot is stale"], config)
    if rejection is not None:
        return _no_trade(state, trend, "INSUFFICIENT_OPTION_DATA",
                         why + [f"Option chain unusable: {rejection}"], config)

    candidate, select_reason = select_option(candidates, direction, expected_move, config)
    if candidate is None:
        return _no_trade(state, trend, select_reason, why + [f"No tradeable option: {select_reason}"], config)

    # --- gate 5: is a sensible stop and target achievable? -------------
    plan = build_risk_plan(state, candidate, direction, config)
    if not plan.feasible:
        return _no_trade(state, trend, plan.infeasible_reason,
                         why + [f"Risk plan rejected: {plan.infeasible_reason} ({plan.basis})"], config)

    why.append(candidate.selection_rationale)
    why.append(plan.basis)
    why.append(f"Reward:risk {plan.reward_risk} (minimum {config.min_reward_risk})")

    return PaperDecision(
        symbol=state.symbol, session_date=state.session_date, decision_timestamp=state.as_of,
        decision="TRADE_CALL" if direction == "up" else "TRADE_PUT",
        decision_reason=f"{trend.assessment} with {trend.confidence}/100 confidence and a feasible risk plan",
        trend_assessment=trend.assessment, confidence=trend.confidence,
        strategy_version=STRATEGY_VERSION, decision_version=DECISION_VERSION,
        configuration_version=CONFIG_VERSION, configuration_hash=config.config_hash(),
        state=state, trend=trend, candidate=candidate, risk_plan=plan, explanation=why,
    )
