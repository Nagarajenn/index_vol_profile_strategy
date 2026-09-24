"""Durable storage for the signal-outcome dataset (sl12d_signals).

Observation only. Nothing in the trading path reads these rows; they exist so that questions
about entry timing, momentum and exit quality can be answered from evidence instead of from
the impression a single session leaves.

Rows are keyed by (signal_id, config_hash): re-running a session updates its rows, and changing
a measurement boundary produces a SEPARATE generation rather than silently rewriting history.
"""

import json
from datetime import date
from pathlib import Path

import psycopg

from config.settings import DB_SCHEMA, require_database_url

SCHEMA_SQL = Path(__file__).with_name("schema.sql")

COLUMNS = (
    "signal_id", "market", "session_date", "signal_minute", "direction", "side", "strike", "expiry",
    "contract", "confidence", "signal_reason", "episode_minutes",
    "entry_minute", "entry_price", "entry_price_type", "quantity", "quantity_source",
    "entry_timing", "entry_timing_note", "entry_timing_provisional", "momentum_state", "momentum_note",
    "exhaustion_state", "exhaustion_note", "entry_features",
    "outcome_1m", "outcome_3m", "outcome_5m", "outcome_10m",
    "outcome_1m_pct", "outcome_3m_pct", "outcome_5m_pct", "outcome_10m_pct",
    "mfe_1m", "mfe_3m", "mfe_5m", "mfe_10m", "mae_1m", "mae_3m", "mae_5m", "mae_10m",
    "mfe_per_unit", "mae_per_unit", "mfe_pct", "mae_pct", "time_to_mfe", "time_to_mae", "marks_observed",
    "exit_minute", "exit_bid", "exit_reason", "hold_minutes",
    "final_pnl_per_unit", "final_pnl", "final_pnl_pct",
    "position_path", "position_final_state", "minutes_in_caution", "minutes_in_prepare_exit",
    "entry_decision_went_wait_at", "entry_waits_survived",
    "outcome_label", "lifecycle_label", "direction_correct", "entry_timing_ok", "exit_ok", "capture_ratio",
    "version", "config_hash", "decision_config_hash",
)


def connect(read_only: bool = False) -> psycopg.Connection:
    opts = f"-c search_path={DB_SCHEMA},public -c statement_timeout=180000"
    if read_only:
        opts += " -c default_transaction_read_only=on"
    return psycopg.connect(require_database_url(), autocommit=True, application_name="sl12d", options=opts)


def apply_schema(conn) -> None:
    sql = SCHEMA_SQL.read_text(encoding="utf-8")
    assert "sl12d_" in sql and not any(w in sql.upper() for w in ("DROP ", "DELETE FROM", "TRUNCATE")), \
        "the 12D schema may only create sl12d_* objects"
    conn.execute(sql)


def to_row(r: dict) -> dict:
    out = {k: r.get(k) for k in COLUMNS}
    out["entry_features"] = json.dumps(r.get("entry_features") or {}, default=str)
    out["momentum_note"] = (r.get("momentum_note") or "")[:1000]
    out["signal_reason"] = (r.get("signal_reason") or "")[:1000]
    return out


def store(conn, rows: list[dict]) -> int:
    if not rows:
        return 0
    cols = ", ".join(COLUMNS)
    ph = ", ".join(f"%({c})s" for c in COLUMNS)
    updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in COLUMNS if c not in ("signal_id", "config_hash"))
    sql = (f"INSERT INTO sl12d_signals ({cols}) VALUES ({ph}) "
           f"ON CONFLICT (signal_id, config_hash) DO UPDATE SET {updates}, computed_at = now()")
    with conn.cursor() as cur:
        cur.executemany(sql, [to_row(r) for r in rows])
    return len(rows)


def load(conn, market: str | None = None, session_date: date | None = None,
         config_hash: str | None = None, limit: int = 100000) -> list[dict]:
    where, args = [], []
    for col, val in (("market", market), ("session_date", session_date), ("config_hash", config_hash)):
        if val is not None:
            where.append(f"{col} = %s")
            args.append(val)
    sql = (f"SELECT {', '.join(COLUMNS)} FROM sl12d_signals "
           f"{'WHERE ' + ' AND '.join(where) if where else ''} "
           f"ORDER BY session_date, market, signal_minute LIMIT %s")
    rows = conn.execute(sql, (*args, limit)).fetchall()
    return [dict(zip(COLUMNS, r)) for r in rows]
