"""Milestone 11D behavioural tests: account, sizing, risk gates, decision
freeze, execution realism, dynamic SL/target, and position management.
"""

from datetime import date, datetime, timedelta

import pytest

from paper_trading.account import ClosedTrade, PaperAccount
from paper_trading.broker import PaperBroker, compute_pnl
from paper_trading.config import DEFAULT_CONFIG, PaperConfig
from paper_trading.models import PaperMarketState, PaperOptionCandidate, PaperPosition
from paper_trading.position_manager import evaluate_minute, tighten_stop
from paper_trading.risk import build_risk_plan

SESSION = date(2026, 9, 8)
CFG = DEFAULT_CONFIG


# ------------------------------------------------------------- 1. capital

def test_starting_capital_is_15000():
    assert CFG.starting_capital == 15_000.0
    assert PaperAccount(CFG).current_capital == 15_000.0


def test_position_size_is_deterministic_and_capped_by_premium_at_risk():
    account = PaperAccount(CFG)
    size = account.position_size(premium=100.0)
    assert size == int(CFG.max_capital_per_trade // 100.0)
    assert account.position_size(premium=100.0) == size  # deterministic


def test_position_size_never_increases_after_a_loss():
    account = PaperAccount(CFG)
    before = account.position_size(100.0)
    account.record_close(SESSION, "NIFTY", -500.0)
    after = account.position_size(100.0)
    assert after <= before, "size must never grow after a loss (no martingale, no averaging down)"


def test_position_size_zero_for_invalid_premium():
    account = PaperAccount(CFG)
    assert account.position_size(0) == 0
    assert account.position_size(None) == 0


# --------------------------------------------------------- 2. risk limits

def test_max_concurrent_positions_blocks_a_second_position():
    account = PaperAccount(CFG)
    allowed, reason = account.can_trade(SESSION, "NIFTY", open_positions=1)
    assert not allowed and reason == "RISK_LIMIT"


def test_max_trades_per_day_enforced():
    account = PaperAccount(CFG)
    account.record_close(SESSION, "NIFTY", 10.0)
    account.record_close(SESSION, "SENSEX", 10.0)
    allowed, reason = account.can_trade(SESSION, "NIFTY", 0)
    assert not allowed and reason == "RISK_LIMIT"


def test_one_trade_per_symbol_per_day():
    account = PaperAccount(CFG)
    account.record_close(SESSION, "NIFTY", 10.0)
    assert account.can_trade(SESSION, "NIFTY", 0)[0] is False
    assert account.can_trade(SESSION, "SENSEX", 0)[0] is True


def test_daily_loss_limit_blocks_further_trading():
    account = PaperAccount(CFG)
    account.record_close(SESSION, "NIFTY", -CFG.max_daily_loss)
    allowed, reason = account.can_trade(SESSION, "SENSEX", 0)
    assert not allowed and reason == "RISK_LIMIT"


def test_account_drawdown_limit_blocks_trading():
    account = PaperAccount(CFG)
    account.closed_trades = [ClosedTrade(SESSION, "NIFTY", -CFG.max_account_drawdown)]
    assert account.can_trade(date(2026, 9, 9), "NIFTY", 0)[0] is False


def test_daily_counters_reset_but_balance_carries_across_sessions():
    account = PaperAccount(CFG)
    account.record_close(SESSION, "NIFTY", -300.0)
    next_day = date(2026, 9, 9)
    assert account.daily_pnl(next_day) == 0.0          # daily counter reset
    assert account.trades_today(next_day) == 0
    assert account.current_capital == 14_700.0          # balance carries
    assert account.realized_pnl == -300.0


# ------------------------------------------------------- 3. execution model

def test_entry_fills_at_ask_not_ltp_or_midpoint():
    fill = PaperBroker().buy(datetime.now(), bid=99.0, ask=101.0, ltp=100.0, quantity=50)
    assert fill.price == 101.0


def test_exit_fills_at_bid_not_ltp_or_midpoint():
    fill = PaperBroker().sell(datetime.now(), bid=110.0, ask=112.0, ltp=111.0, quantity=50)
    assert fill.price == 110.0


def test_missing_ask_cannot_produce_an_entry():
    with pytest.raises(ValueError):
        PaperBroker().buy(datetime.now(), bid=99.0, ask=None, ltp=100.0, quantity=50)


def test_missing_bid_at_exit_uses_explicit_fallback_and_flags_a_data_exception():
    fill = PaperBroker().sell(datetime.now(), bid=None, ask=None, ltp=None, quantity=50, fallback_price=85.0)
    assert fill.price == 85.0
    assert fill.data_exception == "NO_BID_AT_EXIT_USED_CALLER_FALLBACK"


def test_missing_bid_without_fallback_raises_rather_than_inventing_a_price():
    with pytest.raises(ValueError):
        PaperBroker().sell(datetime.now(), bid=None, ask=None, ltp=None, quantity=50)


def test_pnl_is_labelled_pre_cost_and_invents_no_costs():
    pnl = compute_pnl(entry_price=100.0, exit_price=110.0, quantity=50)
    assert pnl["gross_pnl"] == 500.0
    assert pnl["net_pnl"] == 500.0
    assert pnl["costs"] is None
    assert pnl["basis"] == "PRE_COST"


# --------------------------------------------------- 4. dynamic SL / target

def _state(**kw) -> PaperMarketState:
    s = PaperMarketState(
        symbol="NIFTY", session_date=SESSION, as_of=datetime(2026, 9, 8, 14, 59),
        spot=24600.0, vwap=24570.0, poc=24560.0, vah=24650.0, val=24500.0,
        support_low=24400.0, support_high=24450.0, resistance_low=24800.0,
        resistance_high=24850.0, atr_14=120.0,
        expected_move_low=-60.0, expected_move_high=110.0,
    )
    for k, v in kw.items():
        setattr(s, k, v)
    return s


def _candidate(delta=0.5, ask=100.0, bid=99.0) -> PaperOptionCandidate:
    spread = ask - bid
    return PaperOptionCandidate(
        symbol="NIFTY", option_type="CE", strike=24600.0, expiry=date(2026, 9, 11),
        atm_offset=0, moneyness=0.0, ltp=ask, bid=bid, ask=ask, spread=spread,
        spread_pct=spread / ask * 100, volume=1000, oi=1000, oi_change=0, iv=14.0,
        delta=delta, gamma=0.001, theta=-8.0, vega=5.0,
    )


def test_stop_is_derived_from_the_underlying_not_a_flat_premium_percentage():
    plan = build_risk_plan(_state(), _candidate(), "up", CFG)
    assert plan.underlying_invalidation is not None
    assert plan.underlying_stop_distance is not None
    assert "underlying invalidation" in plan.basis or "ATR noise floor" in plan.basis


def test_stop_distance_is_floored_by_atr_so_it_sits_beyond_noise():
    """A support level 5 points away must not produce a 5-point stop."""
    plan = build_risk_plan(_state(support_high=24595.0, vwap=24594.0, poc=24593.0, val=24592.0),
                           _candidate(), "up", CFG)
    assert plan.underlying_stop_distance >= CFG.min_stop_distance_atr * 120.0


def test_two_different_market_states_produce_different_plans():
    """Dynamic means dynamic: the SL/target must not be one fixed
    percentage applied to every trade. Note the stop is STRUCTURE-first
    (ATR only floors and caps it), so two states sharing the same nearby
    invalidation level legitimately share a stop -- what must differ is
    the plan as a whole."""
    calm = build_risk_plan(_state(atr_14=60.0, expected_move_high=40.0), _candidate(), "up", CFG)
    volatile = build_risk_plan(_state(atr_14=200.0, expected_move_high=250.0), _candidate(), "up", CFG)
    assert calm.target_price != volatile.target_price
    assert calm.reward_risk != volatile.reward_risk


def test_atr_drives_the_stop_when_no_structural_level_is_nearby():
    """With every structural level far away, the stop falls back to the
    ATR band -- so a wider-ATR day gets a genuinely wider stop."""
    far = dict(support_high=20000.0, vwap=20000.0, poc=20000.0, val=20000.0)
    calm = build_risk_plan(_state(atr_14=60.0, **far), _candidate(), "up", CFG)
    volatile = build_risk_plan(_state(atr_14=200.0, **far), _candidate(), "up", CFG)
    assert volatile.underlying_stop_distance > calm.underlying_stop_distance
    assert volatile.stop_price < calm.stop_price


def test_expected_move_is_direction_aware():
    """A signed forecast range must not hand an up-trade the downside leg."""
    up = build_risk_plan(_state(), _candidate(delta=0.5), "up", CFG)
    down = build_risk_plan(_state(), _candidate(delta=-0.5), "down", CFG)
    assert up.underlying_target_distance != down.underlying_target_distance


def test_price_pinned_against_structure_is_a_no_trade_not_a_tiny_target():
    plan = build_risk_plan(_state(resistance_low=24605.0), _candidate(), "up", CFG)
    assert plan.feasible is False
    assert plan.infeasible_reason == "PRICE_AT_MAJOR_RESISTANCE"


def test_reward_risk_below_the_minimum_is_rejected():
    plan = build_risk_plan(_state(expected_move_high=5.0, resistance_low=24999.0), _candidate(), "up", CFG)
    if plan.reward_risk is not None:
        assert plan.feasible is False or plan.reward_risk >= CFG.min_reward_risk


def test_missing_inputs_produce_an_infeasible_plan_rather_than_a_guess():
    plan = build_risk_plan(_state(atr_14=None), _candidate(), "up", CFG)
    assert plan.feasible is False
    assert plan.infeasible_reason == "INSUFFICIENT_DATA"


# ------------------------------------------------- 5. position management

def _position(entry=100.0, stop=85.0, target=130.0, entry_time=None) -> PaperPosition:
    entry_time = entry_time or datetime(2026, 9, 8, 15, 0)
    return PaperPosition(
        symbol="NIFTY", session_date=SESSION, option_type="CE", strike=24600.0,
        expiry=date(2026, 9, 11), quantity=50, entry_timestamp=entry_time,
        entry_bid=entry - 1, entry_ask=entry, entry_ltp=entry, entry_spread=1.0,
        entry_spread_pct=1.0, entry_price=entry, capital_allocated=entry * 50,
        initial_stop=stop, initial_target=target, current_stop=stop,
        current_target=target, spot_at_entry=24600.0,
    )


def test_stop_may_tighten_but_never_widen():
    p = _position()
    assert tighten_stop(p, 95.0, "trail") is True
    assert p.current_stop == 95.0
    assert tighten_stop(p, 80.0, "widen attempt") is False, "widening must be refused"
    assert p.current_stop == 95.0
    assert tighten_stop(p, 95.0, "same") is False
    assert p.current_stop == 95.0


def test_forced_time_exit_at_19_minutes_no_exceptions():
    p = _position()
    at = p.entry_timestamp + timedelta(minutes=CFG.max_holding_minutes)
    # Deliberately give it a great quote: it must STILL force-exit.
    reason, event = evaluate_minute(p, at, underlying_price=24700.0, bid=125.0, ask=126.0,
                                    atr_14=120.0, adverse_minutes=0, config=CFG)
    assert reason == "TIME_EXIT"
    assert event.minutes_in_trade >= CFG.max_holding_minutes


def test_minimum_holding_time_prevents_an_instant_exit():
    p = _position()
    at = p.entry_timestamp  # 0 minutes in
    reason, event = evaluate_minute(p, at, underlying_price=24500.0, bid=50.0, ask=51.0,
                                    atr_14=120.0, adverse_minutes=0, config=CFG)
    assert reason is None, "must not exit before the minimum holding time"
    assert "minimum holding time" in event.note


def test_target_hit_exits_on_the_bid():
    p = _position()
    at = p.entry_timestamp + timedelta(minutes=5)
    reason, _ = evaluate_minute(p, at, underlying_price=24700.0, bid=131.0, ask=133.0,
                                atr_14=120.0, adverse_minutes=0, config=CFG)
    assert reason == "TARGET_HIT"


def test_stop_hit_exits_on_the_bid():
    p = _position()
    at = p.entry_timestamp + timedelta(minutes=5)
    reason, _ = evaluate_minute(p, at, underlying_price=24500.0, bid=84.0, ask=86.0,
                                atr_14=120.0, adverse_minutes=0, config=CFG)
    assert reason == "STOP_HIT"


def test_momentum_failure_exits_after_consecutive_adverse_minutes():
    p = _position()
    at = p.entry_timestamp + timedelta(minutes=5)
    reason, event = evaluate_minute(p, at, underlying_price=24590.0, bid=95.0, ask=96.0,
                                    atr_14=120.0, adverse_minutes=CFG.momentum_failure_minutes, config=CFG)
    assert reason == "MOMENTUM_FAILURE"
    assert event.momentum == "FAILED"


def test_direction_reversal_exits_on_a_large_adverse_underlying_move():
    p = _position()
    at = p.entry_timestamp + timedelta(minutes=6)
    adverse_spot = 24600.0 - (CFG.reversal_atr_multiple * 120.0) - 1
    reason, _ = evaluate_minute(p, at, underlying_price=adverse_spot, bid=95.0, ask=96.0,
                                atr_14=120.0, adverse_minutes=1, config=CFG)
    assert reason == "DIRECTION_REVERSAL"


def test_liquidity_failure_exits_when_the_quote_deteriorates():
    p = _position()
    at = p.entry_timestamp + timedelta(minutes=6)
    reason, _ = evaluate_minute(p, at, underlying_price=24610.0, bid=90.0, ask=100.0,
                                atr_14=120.0, adverse_minutes=0, config=CFG)
    assert reason == "OPTION_LIQUIDITY_FAILURE"


def test_trailing_only_engages_after_most_of_the_target_is_captured():
    p = _position(entry=100.0, target=130.0)  # 30 pts of target
    at = p.entry_timestamp + timedelta(minutes=4)
    # +10 captured out of 30 -- below the 75% activation, no trail yet
    evaluate_minute(p, at, underlying_price=24650.0, bid=110.0, ask=111.0,
                    atr_14=120.0, adverse_minutes=0, config=CFG)
    assert p.current_stop == p.initial_stop

    # +25 captured out of 30 -- above activation, stop tightens
    at2 = p.entry_timestamp + timedelta(minutes=5)
    evaluate_minute(p, at2, underlying_price=24680.0, bid=125.0, ask=126.0,
                    atr_14=120.0, adverse_minutes=0, config=CFG)
    assert p.current_stop > p.initial_stop


def test_management_events_are_appended_not_replaced():
    p = _position()
    for i in range(1, 4):
        evaluate_minute(p, p.entry_timestamp + timedelta(minutes=i), underlying_price=24610.0,
                        bid=105.0, ask=106.0, atr_14=120.0, adverse_minutes=0, config=CFG)
    assert len(p.events) == 3
    assert [e.minutes_in_trade for e in p.events] == [1, 2, 3]
