"""One minute of paper-agent life.

Stateless by design: every tick re-reads the account and any open
position from the journal, so a mid-session restart resumes exactly
where it left off rather than losing a position.

Ordering within a tick matters and is fixed:
    1. manage an OPEN position first (it may need to exit this minute)
    2. only then consider a NEW decision
so a force-exit is never delayed by decision work.
"""

import logging
from datetime import date, datetime, time, timedelta

import pandas as pd

from db import reader as db_reader
from option_chain.snapshot_features import extract_atm_window
from paper_trading import journal
from paper_trading.account import ClosedTrade, PaperAccount
from paper_trading.agent import close_position, current_state, decision_time, make_decision, open_position
from paper_trading.broker import PaperBroker
from paper_trading.config import DEFAULT_CONFIG, PaperConfig
from paper_trading.models import PaperPosition
from paper_trading.position_manager import evaluate_minute
from paper_trading.safety import assert_paper_mode

logger = logging.getLogger(__name__)


def load_account(config: PaperConfig) -> PaperAccount:
    account = PaperAccount(config)
    account.closed_trades = [
        ClosedTrade(t["session_date"], t["symbol"], t["net_pnl"])
        for t in journal.load_closed_trades(config.config_hash())
    ]
    return account


def _quote(symbol: str, session_date: date, at: time, strike: float, leg: str):
    """(bid, ask, ltp) for one strike/leg from the option chain snapshot
    at/before `at`. Reuses extract_atm_window unmodified."""
    row = db_reader.get_option_chain_raw_near(symbol, session_date, at_or_before=at.strftime("%H:%M:%S"))
    if not row or not row.get("raw_payload"):
        return None, None, None
    for d in extract_atm_window(row["raw_payload"], atm_window_strikes=DEFAULT_CONFIG.atm_window_strikes):
        if d.strike == strike and d.leg == leg:
            return d.bid, d.ask, d.ltp
    return None, None, None


def _spot(symbol: str, session_date: date, at: time) -> float | None:
    candles = db_reader.load_raw_candles(symbol, start_date=session_date, end_date=session_date)
    if candles.empty:
        return None
    candles["timestamp"] = pd.to_datetime(candles["timestamp"]).dt.tz_convert("Asia/Kolkata")
    upto = candles[candles["timestamp"].dt.time <= at]
    return float(upto["close"].iloc[-1]) if not upto.empty else None


def _adverse_minutes(position: PaperPosition) -> int:
    """Consecutive most-recent management minutes where the underlying sat
    against the position, counted from the recorded event history rather
    than recomputed -- the audit trail is the source of truth."""
    count = 0
    for e in reversed(position.events):
        if e.underlying_price is None or position.spot_at_entry is None:
            break
        move = e.underlying_price - position.spot_at_entry
        favourable = move if position.option_type == "CE" else -move
        if favourable <= 0:
            count += 1
        else:
            break
    return count


def _rehydrate_position(row: dict) -> PaperPosition:
    """Rebuilds an open position (and its event history) from the journal."""
    from db.connection import fetch_all
    from paper_trading.models import PositionEvent

    position = PaperPosition(
        symbol=row["symbol"], session_date=row["session_date"], option_type=row["option_type"],
        strike=float(row["strike"]), expiry=row["expiry"], quantity=int(row["quantity"]),
        entry_timestamp=row["entry_timestamp"], entry_bid=None, entry_ask=float(row["entry_price"]),
        entry_ltp=None, entry_spread=None, entry_spread_pct=None,
        entry_price=float(row["entry_price"]), capital_allocated=float(row["capital_allocated"]),
        initial_stop=float(row["initial_stop"]), initial_target=float(row["initial_target"]),
        current_stop=float(row["current_stop"]), current_target=float(row["current_target"]),
        spot_at_entry=float(row["spot_at_entry"]) if row["spot_at_entry"] is not None else None,
    )
    events = fetch_all(
        """
        SELECT event_timestamp, minutes_in_trade, event_type, underlying_price, option_bid,
               option_ask, unrealized_pnl, momentum, current_stop, current_target, note
        FROM paper_position_events WHERE position_id = %s ORDER BY event_timestamp
        """,
        (row["id"],),
    )
    position.events = [
        PositionEvent(event_timestamp=e[0], minutes_in_trade=e[1], event_type=e[2], underlying_price=e[3],
                      option_bid=e[4], option_ask=e[5], unrealized_pnl=e[6], momentum=e[7],
                      current_stop=e[8], current_target=e[9], note=e[10] or "")
        for e in events
    ]
    return position


def run_tick(symbol: str, now: datetime, config: PaperConfig = DEFAULT_CONFIG) -> dict:
    """One tick for one symbol. Returns {state, summary} for logging."""
    assert_paper_mode()
    session_date = now.date()
    config_hash = config.config_hash()
    account = load_account(config)
    kill_switch = journal.is_kill_switch_active(session_date, config_hash)

    open_row = journal.load_open_position_row(config_hash)
    open_for_symbol = open_row if (open_row and open_row["symbol"] == symbol) else None

    # ---- 1. manage an open position FIRST -----------------------------
    if open_for_symbol:
        result = _manage(open_for_symbol, symbol, session_date, now, account, config, kill_switch)
        journal.set_agent_state(session_date, result["state"], config_hash, heartbeat=now)
        journal.save_account_snapshot(account.snapshot(session_date), config_hash)
        return result

    # ---- 2. otherwise, is it decision time? ---------------------------
    cutoff = decision_time(config)
    state = current_state(now, config, has_open_position=False,
                          has_decision=_decision_exists(symbol, session_date, config_hash))
    journal.set_agent_state(session_date, state, config_hash, heartbeat=now)

    if now.time() < cutoff:
        return {"state": state, "summary": f"monitoring (decision freezes at {config.decision_time})"}
    if _decision_exists(symbol, session_date, config_hash):
        return {"state": "DAILY_REVIEW", "summary": "decision already frozen for today"}

    open_count = 1 if open_row else 0
    decision = make_decision(symbol, session_date, now, account, config,
                             open_positions=open_count, kill_switch=kill_switch)
    decision_id = journal.save_decision(decision)

    if decision.decision == "NO_TRADE":
        journal.set_agent_state(session_date, "NO_TRADE", config_hash, heartbeat=now)
        journal.save_account_snapshot(account.snapshot(session_date), config_hash)
        return {"state": "NO_TRADE", "summary": f"NO TRADE -- {decision.no_trade_reason}"}

    # ---- 3. PAPER_ENTRY ------------------------------------------------
    broker = PaperBroker()
    position = open_position(decision, now, broker)
    position_id = journal.save_position(position, decision_id)
    journal.set_agent_state(session_date, "PAPER_ENTRY", config_hash, heartbeat=now)
    account.capital_in_trade = position.capital_allocated
    journal.save_account_snapshot(account.snapshot(session_date), config_hash)
    return {
        "state": "PAPER_ENTRY",
        "summary": (f"{decision.decision} {position.option_type} {position.strike:.0f} x{position.quantity} "
                    f"@ ask {position.entry_price} (paper) SL {position.initial_stop} "
                    f"TGT {position.initial_target} [position {position_id}]"),
    }


def _decision_exists(symbol: str, session_date: date, config_hash: str) -> bool:
    from db.connection import fetch_one
    return fetch_one(
        "SELECT 1 FROM paper_decisions WHERE symbol=%s AND session_date=%s AND configuration_hash=%s",
        (symbol, session_date, config_hash),
    ) is not None


def _manage(row: dict, symbol: str, session_date: date, now: datetime,
            account: PaperAccount, config: PaperConfig, kill_switch: bool) -> dict:
    """POSITION_MANAGEMENT for one minute. This is the only place the agent
    reads post-14:59 data, and it can only manage or exit -- never revise
    the frozen decision."""
    position = _rehydrate_position(row)
    position_id = row["id"]
    at = now.time()
    bid, ask, ltp = _quote(symbol, session_date, at, position.strike, position.option_type)
    underlying = _spot(symbol, session_date, at)
    atr = None
    state_row = db_reader.get_levels_snapshot_near(symbol, session_date, at.strftime("%H:%M:%S"))
    broker = PaperBroker()

    minutes_in = int((now - position.entry_timestamp).total_seconds() // 60)
    deadline_reached = minutes_in >= config.max_holding_minutes

    if kill_switch and not deadline_reached:
        # The kill switch stops NEW entries and closes an open position at
        # the next available bid -- it never deletes records.
        closed = close_position(position, now, bid, ask, ltp, "MANUAL_PAPER_KILL_SWITCH",
                                broker, account, spot=underlying)
        journal.save_events(position_id, closed)
        journal.close_position_row(position_id, closed)
        return {"state": "PAPER_EXIT", "summary": f"kill switch exit at {closed.exit_price} "
                                                  f"(net {closed.net_pnl})"}

    exit_reason, _event = evaluate_minute(
        position, now, underlying, bid, ask, atr, _adverse_minutes(position), config)
    journal.save_events(position_id, position)

    if exit_reason:
        closed = close_position(position, now, bid, ask, ltp, exit_reason, broker, account, spot=underlying)
        journal.save_events(position_id, closed)
        journal.close_position_row(position_id, closed)
        return {
            "state": "TRADE_COMPLETE",
            "summary": (f"EXIT {exit_reason} at bid {closed.exit_price} after {minutes_in} min -- "
                        f"net {closed.net_pnl} ({closed.return_pct}%) PRE-COST"),
        }

    journal.save_position(position, row.get("decision_id"))
    unrealized = ((bid - position.entry_price) * position.quantity) if bid is not None else 0.0
    return {
        "state": "POSITION_MANAGEMENT",
        "summary": (f"holding {minutes_in}/{config.max_holding_minutes} min, bid {bid}, "
                    f"unrealized {round(unrealized, 2)}, stop {position.current_stop}"),
    }
