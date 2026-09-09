"""Persistence for the paper agent.

Writes live here rather than in the backend: the FastAPI layer stays
read-only (allow_methods=["GET"]), so no frontend request can ever create
a decision or a position. The agent process is the only writer.

paper_decisions is insert-once. Re-running the agent for the same
(symbol, session_date, configuration_hash) is a no-op rather than an
update, which is what makes the 14:59 snapshot genuinely immutable.
"""

import json
import logging
from dataclasses import asdict
from datetime import date

from db.connection import execute, fetch_all, fetch_one
from paper_trading.config import STRATEGY_VERSION
from paper_trading.models import PaperDecision, PaperPosition

logger = logging.getLogger(__name__)


def _json(value):
    from psycopg.types.json import Jsonb
    return Jsonb(value) if value is not None else None


def save_decision(decision: PaperDecision) -> int | None:
    """Insert-once. Returns the decision id, or the existing id if this
    (symbol, date, config) decision was already frozen."""
    s, c, p = decision.state, decision.candidate, decision.risk_plan
    existing = fetch_one(
        "SELECT id FROM paper_decisions WHERE symbol=%s AND session_date=%s AND configuration_hash=%s",
        (decision.symbol, decision.session_date, decision.configuration_hash),
    )
    if existing:
        logger.info("Decision already frozen for %s %s -- not overwriting", decision.symbol, decision.session_date)
        return existing[0]

    row = fetch_one(
        """
        INSERT INTO paper_decisions (
            symbol, session_date, decision_timestamp, decision, decision_reason, no_trade_reason,
            trend_assessment, confidence, strategy_version, decision_version, configuration_version,
            configuration_hash, spot, trend_label, institutional_bias_label, vwap, poc, vah, val,
            support_low, support_high, resistance_low, resistance_high, atr_14,
            rvol_pct, dominant_side, volume_character, amd_phase,
            pcr, atm_iv_call, atm_iv_put, option_snapshot_age_sec,
            transition_verdict, probability_up, probability_down, probability_no_move,
            expected_move_low, expected_move_high, transition_risk_tier, n_analogs,
            option_type, strike, expiry, entry_bid, entry_ask, entry_spread, entry_spread_pct, option_delta,
            dynamic_stop, dynamic_target, underlying_invalidation, underlying_target,
            reward_risk, risk_amount, quantity, capital_allocated,
            supporting_factors, conflicting_factors, risk_factors, explanation,
            data_quality, missing_fields
        ) VALUES (
            %s,%s,%s,%s,%s,%s, %s,%s,%s,%s,%s,%s, %s,%s,%s,%s,%s,%s,%s,
            %s,%s,%s,%s,%s, %s,%s,%s,%s, %s,%s,%s,%s,
            %s,%s,%s,%s, %s,%s,%s,%s,
            %s,%s,%s,%s,%s,%s,%s,%s, %s,%s,%s,%s, %s,%s,%s,%s,
            %s,%s,%s,%s, %s,%s
        ) RETURNING id
        """,
        (
            decision.symbol, decision.session_date, decision.decision_timestamp, decision.decision,
            decision.decision_reason, decision.no_trade_reason, decision.trend_assessment, decision.confidence,
            decision.strategy_version, decision.decision_version, decision.configuration_version,
            decision.configuration_hash,
            s.spot, s.trend_label, s.institutional_bias_label, s.vwap, s.poc, s.vah, s.val,
            s.support_low, s.support_high, s.resistance_low, s.resistance_high, s.atr_14,
            s.rvol_pct, s.dominant_side, s.volume_character, s.amd_phase,
            s.pcr, s.atm_iv_call, s.atm_iv_put, s.option_snapshot_age_sec,
            s.transition_verdict, s.probability_up, s.probability_down, s.probability_no_move,
            s.expected_move_low, s.expected_move_high, s.transition_risk_tier, s.n_analogs,
            c.option_type if c else None, c.strike if c else None, c.expiry if c else None,
            c.bid if c else None, c.ask if c else None, c.spread if c else None,
            c.spread_pct if c else None, c.delta if c else None,
            p.stop_price if p else None, p.target_price if p else None,
            p.underlying_invalidation if p else None, p.underlying_target if p else None,
            p.reward_risk if p else None, p.risk_amount if p else None,
            decision.quantity, decision.capital_allocated,
            _json(decision.trend.supporting_factors), _json(decision.trend.conflicting_factors),
            _json(decision.trend.risk_factors), _json(decision.explanation),
            s.data_quality, _json(s.missing_fields),
        ),
    )
    return row[0] if row else None


def save_position(position: PaperPosition, decision_id: int | None) -> int | None:
    row = fetch_one(
        """
        INSERT INTO paper_positions (
            decision_id, symbol, session_date, option_type, strike, expiry, quantity,
            entry_timestamp, entry_bid, entry_ask, entry_ltp, entry_spread, entry_spread_pct,
            entry_price, capital_allocated, spot_at_entry,
            initial_stop, initial_target, current_stop, current_target, is_open,
            strategy_version, configuration_hash
        ) VALUES (%s,%s,%s,%s,%s,%s,%s, %s,%s,%s,%s,%s,%s, %s,%s,%s, %s,%s,%s,%s,%s, %s,%s)
        ON CONFLICT (symbol, session_date, entry_timestamp) DO UPDATE SET
            current_stop = EXCLUDED.current_stop, current_target = EXCLUDED.current_target
        RETURNING id
        """,
        (
            decision_id, position.symbol, position.session_date, position.option_type, position.strike,
            position.expiry, position.quantity, position.entry_timestamp, position.entry_bid,
            position.entry_ask, position.entry_ltp, position.entry_spread, position.entry_spread_pct,
            position.entry_price, position.capital_allocated, position.spot_at_entry,
            position.initial_stop, position.initial_target, position.current_stop,
            position.current_target, position.is_open,
            STRATEGY_VERSION, _config_hash(),
        ),
    )
    return row[0] if row else None


def _config_hash() -> str:
    from paper_trading.config import DEFAULT_CONFIG
    return DEFAULT_CONFIG.config_hash()


def close_position_row(position_id: int, position: PaperPosition) -> None:
    execute(
        """
        UPDATE paper_positions SET
            is_open = false, exit_timestamp = %s, exit_bid = %s, exit_ask = %s, exit_price = %s,
            exit_reason = %s, gross_pnl = %s, costs = %s, net_pnl = %s, return_pct = %s,
            mfe_pct = %s, mae_pct = %s, underlying_move = %s, direction_correct = %s,
            current_stop = %s, current_target = %s, data_quality = %s
        WHERE id = %s
        """,
        (
            position.exit_timestamp, position.exit_bid, position.exit_ask, position.exit_price,
            position.exit_reason, position.gross_pnl, position.costs, position.net_pnl,
            position.return_pct, position.mfe_pct, position.mae_pct, position.underlying_move,
            position.direction_correct, position.current_stop, position.current_target,
            position.data_quality, position_id,
        ),
    )


def save_events(position_id: int, position: PaperPosition) -> int:
    """Append-only. ON CONFLICT DO NOTHING so a re-processed minute never
    rewrites history."""
    written = 0
    for e in position.events:
        execute(
            """
            INSERT INTO paper_position_events (
                position_id, event_timestamp, minutes_in_trade, event_type, underlying_price,
                option_bid, option_ask, unrealized_pnl, momentum, current_stop, current_target, note
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (position_id, event_timestamp) DO NOTHING
            """,
            (
                position_id, e.event_timestamp, e.minutes_in_trade, e.event_type, e.underlying_price,
                e.option_bid, e.option_ask, e.unrealized_pnl, e.momentum, e.current_stop,
                e.current_target, e.note,
            ),
        )
        written += 1
    return written


def save_account_snapshot(snapshot, config_hash: str) -> None:
    execute(
        """
        INSERT INTO paper_account_snapshots (
            session_date, starting_capital, current_capital, available_capital, capital_in_trade,
            realized_pnl, unrealized_pnl, daily_pnl, total_pnl, daily_drawdown, max_drawdown,
            trade_count, win_count, loss_count, consecutive_wins, consecutive_losses,
            average_win, average_loss, largest_win, largest_loss, profit_factor,
            strategy_version, configuration_hash
        ) VALUES (%s,%s,%s,%s,%s, %s,%s,%s,%s,%s,%s, %s,%s,%s,%s,%s, %s,%s,%s,%s,%s, %s,%s)
        ON CONFLICT (session_date, configuration_hash) DO UPDATE SET
            current_capital = EXCLUDED.current_capital, available_capital = EXCLUDED.available_capital,
            capital_in_trade = EXCLUDED.capital_in_trade, realized_pnl = EXCLUDED.realized_pnl,
            unrealized_pnl = EXCLUDED.unrealized_pnl, daily_pnl = EXCLUDED.daily_pnl,
            total_pnl = EXCLUDED.total_pnl, daily_drawdown = EXCLUDED.daily_drawdown,
            max_drawdown = EXCLUDED.max_drawdown, trade_count = EXCLUDED.trade_count,
            win_count = EXCLUDED.win_count, loss_count = EXCLUDED.loss_count,
            consecutive_wins = EXCLUDED.consecutive_wins, consecutive_losses = EXCLUDED.consecutive_losses,
            average_win = EXCLUDED.average_win, average_loss = EXCLUDED.average_loss,
            largest_win = EXCLUDED.largest_win, largest_loss = EXCLUDED.largest_loss,
            profit_factor = EXCLUDED.profit_factor
        """,
        (
            snapshot.session_date, snapshot.starting_capital, snapshot.current_capital,
            snapshot.available_capital, snapshot.capital_in_trade, snapshot.realized_pnl,
            snapshot.unrealized_pnl, snapshot.daily_pnl, snapshot.total_pnl, snapshot.daily_drawdown,
            snapshot.max_drawdown, snapshot.trade_count, snapshot.win_count, snapshot.loss_count,
            snapshot.consecutive_wins, snapshot.consecutive_losses, snapshot.average_win,
            snapshot.average_loss, snapshot.largest_win, snapshot.largest_loss, snapshot.profit_factor,
            STRATEGY_VERSION, config_hash,
        ),
    )


def load_closed_trades(config_hash: str) -> list[dict]:
    """Rebuilds the account from the journal so the agent is stateless
    between ticks and survives a mid-session restart."""
    rows = fetch_all(
        """
        SELECT session_date, symbol, net_pnl FROM paper_positions
        WHERE is_open = false AND net_pnl IS NOT NULL AND configuration_hash = %s
        ORDER BY exit_timestamp
        """,
        (config_hash,),
    )
    return [{"session_date": r[0], "symbol": r[1], "net_pnl": float(r[2])} for r in rows]


def load_open_position_row(config_hash: str) -> dict | None:
    row = fetch_one(
        """
        SELECT id, symbol, session_date, option_type, strike, expiry, quantity, entry_timestamp,
               entry_price, capital_allocated, spot_at_entry, initial_stop, initial_target,
               current_stop, current_target
        FROM paper_positions WHERE is_open = true AND configuration_hash = %s
        ORDER BY entry_timestamp DESC LIMIT 1
        """,
        (config_hash,),
    )
    if not row:
        return None
    cols = ["id", "symbol", "session_date", "option_type", "strike", "expiry", "quantity",
            "entry_timestamp", "entry_price", "capital_allocated", "spot_at_entry",
            "initial_stop", "initial_target", "current_stop", "current_target"]
    return dict(zip(cols, row))


def is_kill_switch_active(session_date: date, config_hash: str) -> bool:
    row = fetch_one(
        "SELECT kill_switch_active FROM paper_sessions WHERE session_date=%s AND configuration_hash=%s",
        (session_date, config_hash),
    )
    return bool(row[0]) if row else False


def set_agent_state(session_date: date, state: str, config_hash: str, heartbeat=None, kill_switch=None) -> None:
    execute(
        """
        INSERT INTO paper_sessions (session_date, agent_state, kill_switch_active, last_heartbeat,
                                    strategy_version, configuration_hash)
        VALUES (%s,%s,COALESCE(%s,false),%s,%s,%s)
        ON CONFLICT (session_date, configuration_hash) DO UPDATE SET
            agent_state = EXCLUDED.agent_state,
            last_heartbeat = EXCLUDED.last_heartbeat,
            kill_switch_active = COALESCE(%s, paper_sessions.kill_switch_active)
        """,
        (session_date, state, kill_switch, heartbeat, STRATEGY_VERSION, config_hash, kill_switch),
    )
