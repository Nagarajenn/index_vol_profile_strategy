"""The paper agent state machine.

    PRE_MARKET -> MARKET_MONITORING -> PRE_14_59_ANALYSIS -> DECISION_FREEZE
      -> NO_TRADE | TRADE_APPROVED -> PAPER_ENTRY -> POSITION_MANAGEMENT
      -> PAPER_EXIT -> TRADE_COMPLETE -> DAILY_REVIEW

Only PAPER_ENTRY may open a position and only through PaperBroker; no
other state can execute anything. NIFTY and SENSEX are evaluated
independently -- one may trade while the other does not.

The agent is stateless between ticks: everything it needs is re-read from
the database, so a mid-session restart resumes correctly rather than
losing an open paper position.
"""

import logging
from datetime import date, datetime, time, timedelta

from db import reader as db_reader
from paper_trading.account import PaperAccount
from paper_trading.broker import PaperBroker, compute_pnl
from paper_trading.config import DEFAULT_CONFIG, PaperConfig
from paper_trading.decision import decide
from paper_trading.market_state import build_market_state, strike_step
from paper_trading.models import PaperPosition
from paper_trading.position_manager import evaluate_minute
from paper_trading.safety import assert_paper_mode

logger = logging.getLogger(__name__)

MONITOR_START = time(9, 15)
ANALYSIS_START = time(14, 30)


def decision_time(config: PaperConfig) -> time:
    hh, mm, ss = (int(x) for x in config.decision_time.split(":"))
    return time(hh, mm, ss)


def current_state(now: datetime, config: PaperConfig, has_open_position: bool, has_decision: bool) -> str:
    t = now.time()
    if has_open_position:
        return "POSITION_MANAGEMENT"
    if t < MONITOR_START:
        return "PRE_MARKET"
    if t < ANALYSIS_START:
        return "MARKET_MONITORING"
    if t < decision_time(config):
        return "PRE_14_59_ANALYSIS"
    if not has_decision:
        return "DECISION_FREEZE"
    return "DAILY_REVIEW"


def make_decision(symbol: str, session_date: date, now: datetime, account: PaperAccount,
                  config: PaperConfig = DEFAULT_CONFIG, open_positions: int = 0,
                  kill_switch: bool = False):
    """Builds the frozen 14:59 decision for one symbol. Pure with respect
    to the market: it reads data clamped at the cutoff and writes nothing."""
    assert_paper_mode()
    cutoff = decision_time(config)
    state = build_market_state(symbol, session_date, cutoff, now)
    allowed, block = account.can_trade(session_date, symbol, open_positions)
    raw_chain = db_reader.get_option_chain_raw_near(symbol, session_date, at_or_before=cutoff.strftime("%H:%M:%S"))
    decision = decide(
        state, config, option_at_1459=raw_chain, strike_step=strike_step(symbol),
        account_block_reason=None if allowed else block, kill_switch=kill_switch,
    )
    if decision.decision != "NO_TRADE" and decision.candidate is not None:
        quantity = account.position_size(decision.candidate.ask)
        if quantity <= 0:
            return decide(state, config, option_at_1459=raw_chain, strike_step=strike_step(symbol),
                          account_block_reason="RISK_LIMIT", kill_switch=kill_switch)
        decision.quantity = quantity
        decision.capital_allocated = round(quantity * decision.candidate.ask, 2)
    return decision


def open_position(decision, now: datetime, broker: PaperBroker) -> PaperPosition:
    """PAPER_ENTRY. Fills at ASK via the simulator -- the only place in the
    agent that creates a position."""
    assert_paper_mode()
    c, plan = decision.candidate, decision.risk_plan
    fill = broker.buy(now, bid=c.bid, ask=c.ask, ltp=c.ltp, quantity=decision.quantity)
    return PaperPosition(
        symbol=decision.symbol, session_date=decision.session_date, option_type=c.option_type,
        strike=c.strike, expiry=c.expiry, quantity=decision.quantity, entry_timestamp=now,
        entry_bid=c.bid, entry_ask=c.ask, entry_ltp=c.ltp, entry_spread=c.spread,
        entry_spread_pct=c.spread_pct, entry_price=fill.price,
        capital_allocated=decision.capital_allocated,
        initial_stop=plan.stop_price, initial_target=plan.target_price,
        current_stop=plan.stop_price, current_target=plan.target_price,
        spot_at_entry=decision.state.spot,
    )


def close_position(position: PaperPosition, now: datetime, bid, ask, ltp, reason: str,
                   broker: PaperBroker, account: PaperAccount, spot: float | None = None) -> PaperPosition:
    """PAPER_EXIT. Fills at BID. A missing BID at the forced time exit is
    recorded as a data exception with the last known stop as the explicit
    fallback -- never an invented price."""
    assert_paper_mode()
    fallback = position.current_stop if bid is None else None
    fill = broker.sell(now, bid=bid, ask=ask, ltp=ltp, quantity=position.quantity, fallback_price=fallback)
    pnl = compute_pnl(position.entry_price, fill.price, position.quantity)

    position.is_open = False
    position.exit_timestamp = now
    position.exit_bid, position.exit_ask, position.exit_price = bid, ask, fill.price
    position.exit_reason = reason
    position.gross_pnl, position.costs = pnl["gross_pnl"], pnl["costs"]
    position.net_pnl, position.return_pct = pnl["net_pnl"], pnl["return_pct"]
    if fill.data_exception:
        position.data_quality = "DEGRADED"

    bids = [e.option_bid for e in position.events if e.option_bid is not None]
    if bids and position.entry_price:
        position.mfe_pct = round((max(bids) - position.entry_price) / position.entry_price * 100, 2)
        position.mae_pct = round((min(bids) - position.entry_price) / position.entry_price * 100, 2)
    if spot is not None and position.spot_at_entry is not None:
        position.underlying_move = round(spot - position.spot_at_entry, 2)
        favourable = position.underlying_move if position.option_type == "CE" else -position.underlying_move
        position.direction_correct = favourable > 0

    account.record_close(position.session_date, position.symbol, position.net_pnl)
    return position


def manage_position(position: PaperPosition, now: datetime, underlying_price, bid, ask, ltp,
                    atr_14, adverse_minutes: int, broker: PaperBroker, account: PaperAccount,
                    config: PaperConfig = DEFAULT_CONFIG) -> PaperPosition:
    """POSITION_MANAGEMENT: one minute. May use post-14:59 data -- but only
    to manage a position the frozen decision already approved."""
    exit_reason, _event = evaluate_minute(
        position, now, underlying_price, bid, ask, atr_14, adverse_minutes, config)
    if exit_reason:
        return close_position(position, now, bid, ask, ltp, exit_reason, broker, account, spot=underlying_price)
    return position


def force_exit_deadline(position: PaperPosition, config: PaperConfig = DEFAULT_CONFIG) -> datetime:
    return position.entry_timestamp + timedelta(minutes=config.max_holding_minutes)
