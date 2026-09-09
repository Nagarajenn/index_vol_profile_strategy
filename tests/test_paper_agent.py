"""Agent state-machine and lifecycle tests (no DB required)."""

from datetime import date, datetime, timedelta

import pytest

from paper_trading.account import PaperAccount
from paper_trading.agent import close_position, current_state, decision_time, force_exit_deadline, open_position
from paper_trading.broker import PaperBroker
from paper_trading.config import DEFAULT_CONFIG as CFG
from paper_trading.models import PaperDecision, PaperMarketState, PaperOptionCandidate, PaperPosition, RiskPlan, TrendVerdict

SESSION = date(2026, 9, 8)


def _dt(h, m):
    return datetime(2026, 9, 8, h, m)


def test_decision_time_is_1459():
    assert decision_time(CFG).strftime("%H:%M:%S") == "14:59:00"


@pytest.mark.parametrize("moment,expected", [
    (_dt(8, 30), "PRE_MARKET"),
    (_dt(10, 0), "MARKET_MONITORING"),
    (_dt(14, 45), "PRE_14_59_ANALYSIS"),
    (_dt(14, 59), "DECISION_FREEZE"),
])
def test_state_machine_progresses_through_the_session(moment, expected):
    assert current_state(moment, CFG, has_open_position=False, has_decision=False) == expected


def test_an_open_position_always_reports_position_management():
    """No matter the clock, an open position means management -- so a
    force-exit is never skipped because the agent thought it was idle."""
    for moment in (_dt(9, 0), _dt(14, 59), _dt(15, 10)):
        assert current_state(moment, CFG, has_open_position=True, has_decision=True) == "POSITION_MANAGEMENT"


def test_once_decided_the_agent_moves_to_review_not_back_to_analysis():
    assert current_state(_dt(15, 5), CFG, has_open_position=False, has_decision=True) == "DAILY_REVIEW"


def _decision(ask=150.0, stop=134.0, target=211.0, quantity=40) -> PaperDecision:
    state = PaperMarketState(symbol="NIFTY", session_date=SESSION, as_of=_dt(14, 59), spot=24600.0)
    candidate = PaperOptionCandidate(
        symbol="NIFTY", option_type="CE", strike=24600.0, expiry=date(2026, 9, 11), atm_offset=0,
        moneyness=0.0, ltp=ask - 0.5, bid=ask - 1, ask=ask, spread=1.0, spread_pct=0.67,
        volume=1000, oi=1000, oi_change=0, iv=14.0, delta=0.55, gamma=0.001, theta=-8.0, vega=5.0,
    )
    plan = RiskPlan(
        underlying_invalidation=24570.0, underlying_target=24710.0, underlying_stop_distance=30.0,
        underlying_target_distance=110.0, stop_price=stop, target_price=target,
        stop_pct=10.0, target_pct=40.0, reward_risk=3.6, risk_amount=ask - stop,
    )
    return PaperDecision(
        symbol="NIFTY", session_date=SESSION, decision_timestamp=_dt(14, 59), decision="TRADE_CALL",
        decision_reason="test", trend_assessment="UP", confidence=60,
        strategy_version="v", decision_version="v", configuration_version="v",
        configuration_hash=CFG.config_hash(), state=state,
        trend=TrendVerdict(assessment="UP", score=2.0, confidence=60),
        candidate=candidate, risk_plan=plan, quantity=quantity, capital_allocated=ask * quantity,
    )


def test_open_position_fills_at_ask_and_copies_the_frozen_plan():
    d = _decision()
    p = open_position(d, _dt(14, 59), PaperBroker())
    assert p.entry_price == d.candidate.ask       # ASK, never LTP/mid
    assert p.initial_stop == d.risk_plan.stop_price
    assert p.initial_target == d.risk_plan.target_price
    assert p.current_stop == p.initial_stop
    assert p.is_open is True


def test_force_exit_deadline_is_19_minutes_after_entry():
    p = open_position(_decision(), _dt(14, 59), PaperBroker())
    assert force_exit_deadline(p, CFG) == p.entry_timestamp + timedelta(minutes=19)


def test_close_position_records_pnl_direction_and_updates_the_account():
    account = PaperAccount(CFG)
    p = open_position(_decision(ask=150.0, quantity=40), _dt(15, 0), PaperBroker())
    p.spot_at_entry = 24600.0
    closed = close_position(p, _dt(15, 8), bid=170.0, ask=171.0, ltp=170.5,
                            reason="TARGET_HIT", broker=PaperBroker(), account=account, spot=24700.0)
    assert closed.exit_price == 170.0                    # BID
    assert closed.net_pnl == pytest.approx((170.0 - 150.0) * 40)
    assert closed.direction_correct is True              # CE with the underlying up
    assert closed.is_open is False
    assert account.current_capital == CFG.starting_capital + closed.net_pnl
    assert account.trades_today(SESSION) == 1


def test_direction_correct_is_false_when_the_underlying_went_the_other_way():
    account = PaperAccount(CFG)
    p = open_position(_decision(), _dt(15, 0), PaperBroker())
    p.spot_at_entry = 24600.0
    closed = close_position(p, _dt(15, 8), bid=120.0, ask=121.0, ltp=120.5,
                            reason="STOP_HIT", broker=PaperBroker(), account=account, spot=24500.0)
    assert closed.direction_correct is False
    assert closed.net_pnl < 0


def test_a_losing_trade_reduces_capital_and_counts_toward_the_daily_loss_limit():
    account = PaperAccount(CFG)
    p = open_position(_decision(ask=150.0, quantity=40), _dt(15, 0), PaperBroker())
    close_position(p, _dt(15, 10), bid=110.0, ask=111.0, ltp=110.5,
                   reason="STOP_HIT", broker=PaperBroker(), account=account, spot=24500.0)
    assert account.current_capital < CFG.starting_capital
    assert account.daily_pnl(SESSION) < 0
