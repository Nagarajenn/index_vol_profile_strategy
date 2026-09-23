"""Storage for closed simulated positions (sim12c_positions).

SIMULATION ONLY. These rows are a record of what the 12C decisions would have produced; they
are not orders and not paper-account trades, and no trading code reads them. The table exists
so the decisions can be reviewed later -- in particular WHICH decision closed each position.

Writes are confined to sim12c_* objects; nothing else in the database is touched.
"""

import json
from datetime import date
from pathlib import Path

import psycopg

from config.settings import DB_SCHEMA, require_database_url
from position_sim_12c import VERSION
from position_sim_12c.config import DEFAULT

SCHEMA_SQL = Path(__file__).with_name("schema.sql")
COLUMNS = ("symbol", "session_date", "signal_minute", "entry_minute", "entry_confirmation", "side", "strike",
           "expiry", "contract", "entry_price", "entry_price_type", "entry_ltp", "quantity", "quantity_source",
           "entry_value", "stop_loss_pct", "stop_loss_price", "stop_breach_minute", "exit_minute", "exit_bid",
           "exit_reason", "closing_decision", "closing_confirmation", "closing_reason", "risk_state_at_exit",
           "families_against_at_exit", "realised_pnl_per_unit", "realised_pnl", "realised_pnl_pct", "mfe_per_unit",
           "mae_per_unit", "mfe", "mae", "hold_minutes", "sim_version", "sim_config_hash", "decision_config_hash",
           "entry_at_next_minute")


def connect(read_only: bool = False) -> psycopg.Connection:
    opts = f"-c search_path={DB_SCHEMA},public -c statement_timeout=120000"
    if read_only:
        opts += " -c default_transaction_read_only=on"
    return psycopg.connect(require_database_url(), autocommit=True, application_name="sim12c_history", options=opts)


def apply_schema(conn) -> None:
    sql = SCHEMA_SQL.read_text(encoding="utf-8")
    assert "sim12c_" in sql and not any(w in sql.upper() for w in ("DROP ", "ALTER TABLE PAPER", "DELETE FROM")), \
        "the 12C simulation schema may only create sim12c_* objects"
    conn.execute(sql)


def to_row(p: dict, session_date: date, decision_config_hash: str, cfg=DEFAULT) -> dict:
    """One closed simulated position -> one storable row."""
    ex = p.get("excursions") or {}
    return dict(symbol=p["symbol"], session_date=session_date, signal_minute=p["signal_minute"],
                entry_minute=p["entry_minute"], entry_confirmation=p.get("confirmation"), side=p["side"],
                strike=p.get("strike"), expiry=p.get("expiry"), contract=p.get("contract"),
                entry_price=p.get("entry_price"), entry_price_type=p.get("entry_price_type", "ASK"),
                entry_ltp=p.get("entry_ltp_at_signal"), quantity=p.get("quantity"),
                quantity_source=p.get("quantity_source"), entry_value=p.get("entry_value"),
                stop_loss_pct=p.get("stop_loss_pct"), stop_loss_price=p.get("stop_loss_price"),
                stop_breach_minute=p.get("stop_breach_minute"), exit_minute=p.get("exit_minute"),
                exit_bid=p.get("exit_bid"), exit_reason=p.get("exit_reason"),
                closing_decision=p.get("closing_decision"), closing_confirmation=p.get("closing_confirmation"),
                closing_reason=p.get("closing_reason"),
                risk_state_at_exit=(p.get("risk") or {}).get("risk_state"),
                families_against_at_exit=json.dumps((p.get("risk") or {}).get("families_against") or []),
                realised_pnl_per_unit=p.get("realised_pnl_per_unit"), realised_pnl=p.get("realised_pnl"),
                realised_pnl_pct=p.get("realised_pnl_pct"), mfe_per_unit=ex.get("mfe_per_unit"),
                mae_per_unit=ex.get("mae_per_unit"), mfe=ex.get("mfe"), mae=ex.get("mae"),
                hold_minutes=p.get("hold_minutes"), sim_version=VERSION, sim_config_hash=cfg.config_hash(),
                decision_config_hash=decision_config_hash, entry_at_next_minute=cfg.entry_at_next_minute)


def store(conn, rows: list[dict]) -> int:
    """Idempotent upsert: re-running a session updates its rows instead of duplicating them."""
    if not rows:
        return 0
    cols = ", ".join(COLUMNS)
    ph = ", ".join(f"%({c})s" for c in COLUMNS)
    updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in COLUMNS
                        if c not in ("symbol", "session_date", "signal_minute", "side", "strike", "sim_config_hash"))
    sql = (f"INSERT INTO sim12c_positions ({cols}) VALUES ({ph}) "
           f"ON CONFLICT (symbol, session_date, signal_minute, side, strike, sim_config_hash) "
           f"DO UPDATE SET {updates}")
    with conn.cursor() as cur:
        cur.executemany(sql, rows)
    return len(rows)


def load(conn, symbol: str | None = None, session_date: date | None = None, limit: int = 200) -> list[dict]:
    where, args = [], []
    if symbol:
        where.append("symbol = %s")
        args.append(symbol)
    if session_date:
        where.append("session_date = %s")
        args.append(session_date)
    sql = (f"SELECT {', '.join(COLUMNS)} FROM sim12c_positions "
           f"{'WHERE ' + ' AND '.join(where) if where else ''} "
           f"ORDER BY session_date DESC, signal_minute DESC LIMIT %s")
    rows = conn.execute(sql, (*args, limit)).fetchall()
    return [dict(zip(COLUMNS, r)) for r in rows]
