"""Session state, order rows and position rows. The only module that writes live_* tables.

Writes are confined to live_* objects. Nothing here reads or writes any other table, and the
read-only FastAPI backend is not involved: control actions come through the separate local
control service.
"""

import json
from datetime import date
from pathlib import Path

import psycopg

from config.settings import DB_SCHEMA, require_database_url

SCHEMA_SQL = Path(__file__).with_name("schema.sql")


def connect(read_only: bool = False) -> psycopg.Connection:
    opts = f"-c search_path={DB_SCHEMA},public -c statement_timeout=30000"
    if read_only:
        opts += " -c default_transaction_read_only=on"
    return psycopg.connect(require_database_url(), autocommit=True, application_name="live_trading", options=opts)


def apply_schema(conn) -> None:
    sql = SCHEMA_SQL.read_text(encoding="utf-8")
    assert "live_" in sql and not any(w in sql.upper() for w in ("DROP ", "DELETE FROM", "TRUNCATE")), \
        "the live trading schema may only create live_* objects"
    conn.execute(sql)


# ---------------------------------------------------------------- session state
def session(conn, symbol: str, d: date) -> dict:
    """The session row, created disarmed if it does not exist. Disarmed is always the default."""
    conn.execute("""INSERT INTO live_session_state (symbol, session_date) VALUES (%s, %s)
                    ON CONFLICT (symbol, session_date) DO NOTHING""", (symbol, d))
    cols = ("armed", "halted", "halt_reason", "kill_switch", "entries_used", "realised_pnl")
    r = conn.execute(f"SELECT {', '.join(cols)} FROM live_session_state WHERE symbol=%s AND session_date=%s",
                     (symbol, d)).fetchone()
    return dict(zip(cols, r))


def set_flags(conn, symbol: str, d: date, **flags) -> None:
    allowed = {"armed", "halted", "halt_reason", "kill_switch"}
    bad = set(flags) - allowed
    assert not bad, f"not a settable session flag: {bad}"
    sets = ", ".join(f"{k} = %s" for k in flags)
    conn.execute(f"UPDATE live_session_state SET {sets}, updated_at = now() WHERE symbol=%s AND session_date=%s",
                 (*flags.values(), symbol, d))


def disarm_all(conn, d: date) -> None:
    """Called on every process start: a restart must never inherit an armed session."""
    conn.execute("UPDATE live_session_state SET armed = FALSE, updated_at = now() WHERE session_date = %s", (d,))


def refresh_counters(conn, symbol: str, d: date) -> dict:
    """Recompute entries_used and realised_pnl from the rows themselves, never from memory."""
    n = conn.execute("""SELECT count(*) FROM live_orders WHERE symbol=%s AND session_date=%s
                        AND status IN ('SENT','FILLED','DRY_RUN')""", (symbol, d)).fetchone()[0]
    pnl = conn.execute("""SELECT coalesce(sum(realised_pnl), 0) FROM live_positions
                          WHERE symbol=%s AND session_date=%s AND is_open = FALSE""", (symbol, d)).fetchone()[0]
    conn.execute("""UPDATE live_session_state SET entries_used=%s, realised_pnl=%s, updated_at=now()
                    WHERE symbol=%s AND session_date=%s""", (n, float(pnl), symbol, d))
    return dict(entries_used=n, realised_pnl=float(pnl))


def open_position(conn, symbol: str, d: date) -> dict | None:
    cols = ("correlation_id", "contract_label", "security_id", "option_type", "strike", "quantity",
            "entry_price", "entry_cost", "entry_at")
    r = conn.execute(f"""SELECT {', '.join(cols)} FROM live_positions
                         WHERE symbol=%s AND session_date=%s AND is_open ORDER BY entry_at DESC LIMIT 1""",
                     (symbol, d)).fetchone()
    return dict(zip(cols, r)) if r else None


def seen(conn, correlation_id: str) -> bool:
    return conn.execute("SELECT 1 FROM live_orders WHERE correlation_id=%s", (correlation_id,)).fetchone() is not None


# ---------------------------------------------------------------- orders and positions
ORDER_COLUMNS = ("correlation_id", "symbol", "session_date", "signal_minute", "decision", "confirmation",
                 "decision_reason", "episode_minutes", "contract_label", "security_id", "exchange_segment",
                 "option_type", "strike", "expiry", "quantity", "lot_size", "ask", "bid", "spread_pct",
                 "limit_price", "entry_cost", "status", "refusal_reasons", "guards_passed", "dry_run",
                 "broker_request", "broker_response", "broker_order_id", "fill_price", "evidence",
                 "live_version", "live_config_hash", "decision_config_hash")

_JSON_COLUMNS = ("refusal_reasons", "guards_passed", "broker_request", "broker_response", "evidence")


def record_order(conn, row: dict) -> None:
    """Append-only. Written BEFORE anything is sent, so a crash mid-flight still leaves a trace."""
    r = {k: row.get(k) for k in ORDER_COLUMNS}
    for k in _JSON_COLUMNS:
        if r[k] is not None and not isinstance(r[k], str):
            r[k] = json.dumps(r[k], default=str)
    cols = ", ".join(ORDER_COLUMNS)
    ph = ", ".join(f"%({c})s" for c in ORDER_COLUMNS)
    conn.execute(f"INSERT INTO live_orders ({cols}) VALUES ({ph}) ON CONFLICT (correlation_id) DO NOTHING", r)


def update_order(conn, correlation_id: str, **fields) -> None:
    allowed = {"status", "broker_response", "broker_order_id", "fill_price", "filled_at"}
    bad = set(fields) - allowed
    assert not bad, f"not an updatable order field: {bad}"
    vals = {k: (json.dumps(v, default=str) if k == "broker_response" and not isinstance(v, str) else v)
            for k, v in fields.items()}
    sets = ", ".join(f"{k} = %s" for k in vals)
    conn.execute(f"UPDATE live_orders SET {sets} WHERE correlation_id = %s", (*vals.values(), correlation_id))


def record_position(conn, row: dict) -> None:
    cols = ("correlation_id", "symbol", "session_date", "contract_label", "security_id", "option_type",
            "strike", "expiry", "quantity", "entry_price", "entry_at", "entry_cost")
    ph = ", ".join(f"%({c})s" for c in cols)
    conn.execute(f"INSERT INTO live_positions ({', '.join(cols)}) VALUES ({ph}) "
                 f"ON CONFLICT (correlation_id) DO NOTHING", {k: row.get(k) for k in cols})


def close_position(conn, correlation_id: str, exit_price: float, exit_at, route: str) -> float:
    r = conn.execute("SELECT quantity, entry_price FROM live_positions WHERE correlation_id=%s",
                     (correlation_id,)).fetchone()
    if not r:
        return 0.0
    qty, entry = r
    pnl = (float(exit_price) - float(entry)) * int(qty)
    conn.execute("""UPDATE live_positions SET exit_price=%s, exit_at=%s, exit_route=%s, realised_pnl=%s,
                    is_open=FALSE, updated_at=now() WHERE correlation_id=%s""",
                 (exit_price, exit_at, route, pnl, correlation_id))
    return pnl
