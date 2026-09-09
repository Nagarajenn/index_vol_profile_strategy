"""Dynamic, underlying-aware stop-loss and target.

The stop is NOT "premium minus N%". It is derived from where the
UNDERLYING thesis is invalidated -- the nearest real structural level
against the trade (support for a call, resistance for a put), floored by
an ATR-scaled noise buffer so a stop is never placed inside normal
1-minute chop -- and only THEN translated into option-premium terms
through delta.

Everything here uses <=14:59 information only. The plan produced is
frozen at entry; post-entry management may tighten it but never widen it
(enforced in position_manager.tighten_stop).

Documented limitation: the points->premium translation is a linear delta
approximation. Over a 15-19 minute hold on a near-ATM option that is a
reasonable first-order estimate, but it ignores gamma and any IV change,
so realised option moves will not match it exactly. The realised P&L in
the journal always comes from actual bid/ask quotes, never from this
approximation.
"""

from paper_trading.config import PaperConfig
from paper_trading.models import PaperMarketState, PaperOptionCandidate, RiskPlan


def _nearest_level_below(spot: float, levels: list[float | None]) -> float | None:
    below = [lv for lv in levels if lv is not None and lv < spot]
    return max(below) if below else None


def _nearest_level_above(spot: float, levels: list[float | None]) -> float | None:
    above = [lv for lv in levels if lv is not None and lv > spot]
    return min(above) if above else None


def _expected_move(state: PaperMarketState, direction: str) -> float | None:
    """Magnitude of the expected underlying move IN THE TRADED DIRECTION.

    The transition forecast publishes a signed range (e.g. -200/+39): the
    downside leg is the relevant one for a put and the upside leg for a
    call. Taking max(|low|,|high|) for both -- as an earlier draft did --
    silently handed an up-trade the downside expectation, overstating it.
    Falls back to ATR when the forecast has no read for the day, which is
    disclosed in RiskPlan.basis."""
    if state.expected_move_low is not None and state.expected_move_high is not None:
        leg = state.expected_move_high if direction == "up" else state.expected_move_low
        magnitude = abs(leg)
        if magnitude > 0:
            return magnitude
    return state.atr_14


def build_risk_plan(
    state: PaperMarketState, candidate: PaperOptionCandidate, direction: str, config: PaperConfig,
) -> RiskPlan:
    empty = RiskPlan(None, None, None, None, None, None, None, None, None, None)

    if state.spot is None or not state.atr_14 or candidate.delta is None or not candidate.ask:
        empty.feasible, empty.infeasible_reason = False, "INSUFFICIENT_DATA"
        empty.basis = "Missing spot, ATR, delta or ask -- cannot derive an underlying-aware stop"
        return empty

    spot, atr, delta, ask = state.spot, state.atr_14, abs(candidate.delta), candidate.ask
    expected_move = _expected_move(state, direction)
    if not expected_move:
        empty.feasible, empty.infeasible_reason = False, "EXPECTED_MOVE_TOO_SMALL"
        empty.basis = "No expected-move estimate available from the transition forecast or ATR"
        return empty

    min_stop_dist = config.min_stop_distance_atr * atr
    max_stop_dist = config.max_stop_distance_atr * atr

    # Stop candidates deliberately include the soft levels (VWAP, POC,
    # value-area edge): those are places the THESIS breaks, which is
    # exactly what an invalidation point means.
    #
    # Target candidates deliberately EXCLUDE them and use only the real
    # S/R zone. A developing value-area edge frequently sits a handful of
    # points from spot; treating that as a barrier would cap almost every
    # target at a few points and block the agent for a misleading reason
    # (observed directly on SENSEX 2026-09-08, where VAL sat 6 pts away
    # while genuine support was 106 pts away).
    if direction == "up":
        structural = _nearest_level_below(spot, [state.support_high, state.vwap, state.poc, state.val])
        target_level = _nearest_level_above(spot, [state.resistance_low])
        basis_side, basis_side_opposing = "support", "resistance"
    else:
        structural = _nearest_level_above(spot, [state.resistance_low, state.vwap, state.poc, state.vah])
        target_level = _nearest_level_below(spot, [state.support_high])
        basis_side, basis_side_opposing = "resistance", "support"

    # --- stop: structural level, clamped into the ATR noise band --------
    if structural is not None:
        raw_stop_distance = abs(spot - structural)
        basis = f"underlying invalidation at nearest {basis_side} {structural:.0f}"
    else:
        raw_stop_distance = min_stop_dist
        basis = f"no {basis_side} level within reach -- ATR noise floor used"
    stop_distance = max(min_stop_dist, min(raw_stop_distance, max_stop_dist))
    underlying_invalidation = spot - stop_distance if direction == "up" else spot + stop_distance

    # --- target: expected move, capped only by a MEANINGFUL level -------
    # A level closer than the stop distance does not cap the target -- it
    # means price is pinned against structure with no room to work, which
    # is a NO TRADE in its own right rather than a 6-point target that
    # then fails the reward:risk gate for the wrong stated reason.
    if target_level is not None and abs(target_level - spot) < stop_distance:
        empty.feasible = False
        empty.infeasible_reason = (
            "PRICE_AT_MAJOR_RESISTANCE" if direction == "up" else "PRICE_AT_MAJOR_SUPPORT"
        )
        empty.basis = (
            f"Price {spot:.0f} is pinned against {basis_side_opposing} {target_level:.0f} "
            f"({abs(target_level - spot):.0f} pts away, inside the {stop_distance:.0f}-pt stop) "
            f"-- no room to work"
        )
        return empty

    if target_level is not None:
        raw_target_distance = min(abs(target_level - spot), expected_move)
        target_basis = f"capped by opposing level {target_level:.0f} and expected move {expected_move:.0f}"
    else:
        raw_target_distance = expected_move
        target_basis = f"expected move {expected_move:.0f} (no opposing level within reach)"
    target_distance = raw_target_distance
    underlying_target = spot + target_distance if direction == "up" else spot - target_distance

    # --- translate underlying points into option premium via delta ------
    stop_premium_move = delta * stop_distance
    target_premium_move = delta * target_distance
    stop_price = max(0.05, ask - stop_premium_move)
    target_price = ask + target_premium_move
    stop_pct = (ask - stop_price) / ask * 100
    target_pct = (target_price - ask) / ask * 100
    reward_risk = (target_price - ask) / (ask - stop_price) if ask > stop_price else None
    risk_amount = ask - stop_price

    plan = RiskPlan(
        underlying_invalidation=round(underlying_invalidation, 2),
        underlying_target=round(underlying_target, 2),
        underlying_stop_distance=round(stop_distance, 2),
        underlying_target_distance=round(target_distance, 2),
        stop_price=round(stop_price, 2),
        target_price=round(target_price, 2),
        stop_pct=round(stop_pct, 2),
        target_pct=round(target_pct, 2),
        reward_risk=round(reward_risk, 2) if reward_risk else None,
        risk_amount=round(risk_amount, 2),
        basis=f"Stop from {basis} ({stop_distance:.0f} pts); target {target_basis} "
              f"({target_distance:.0f} pts); translated at delta {delta:.2f}",
    )
    return _check_feasibility(plan, candidate, config)


def _check_feasibility(plan: RiskPlan, candidate: PaperOptionCandidate, config: PaperConfig) -> RiskPlan:
    """A plan that cannot be executed sensibly must produce NO TRADE, not
    a quietly-adjusted plan."""
    spread = candidate.spread or 0.0
    if plan.stop_pct is not None and plan.stop_pct < config.min_stop_pct_of_premium:
        plan.feasible, plan.infeasible_reason = False, "SL_TOO_TIGHT"
    elif plan.risk_amount is not None and plan.risk_amount < config.stop_spread_multiple * spread:
        plan.feasible, plan.infeasible_reason = False, "SL_TOO_TIGHT"
    elif plan.stop_pct is not None and plan.stop_pct > config.max_stop_pct_of_premium:
        # The underlying invalidation is real, but expressed through this
        # option it would risk more of the premium than the budget allows
        # -- typically a cheap, highly-geared strike against a wide stop.
        # That is its own condition, not a "target not realistic".
        plan.feasible, plan.infeasible_reason = False, "STOP_EXCEEDS_RISK_BUDGET"
    elif plan.reward_risk is None or plan.reward_risk < config.min_reward_risk:
        plan.feasible, plan.infeasible_reason = False, "EXPECTED_REWARD_INSUFFICIENT"
    return plan
