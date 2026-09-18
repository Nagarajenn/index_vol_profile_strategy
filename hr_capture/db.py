"""HR-only database access.

A separate psycopg connection (application_name=hr_capture) with statement
and lock timeouts, so HR can never hold the platform's database hostage.
It does NOT use db/connection.py's shared connection. Every write this
module can build targets an ``hr_*`` table (``insert_sql`` refuses anything
else); the only non-hr statements HR ever runs are the read-only SELECTs in
hr_capture/universe.py.
"""

import psycopg
from psycopg.types.json import Jsonb

from config.settings import DB_SCHEMA, require_database_url
from hr_capture.config import HRConfig

TABLE_COLUMNS: dict[str, tuple[str, ...]] = {
    "hr_capture_sessions": (
        "session_id", "trading_date", "mode", "pipeline_version", "parser_version", "implied_spot_method",
        "window_start", "window_end", "started_at", "status", "instruments_expected", "config",
    ),
    "hr_instruments": (
        "session_id", "symbol", "exchange_segment", "security_id", "instrument_type", "trading_symbol", "expiry",
        "strike", "option_type", "atm_offset", "band_atm_strike", "reference_spot", "subscribe_mode", "id_source",
    ),
    "hr_raw_ticks": (
        "session_id", "packet_seq", "symbol", "exchange_segment", "security_id", "instrument_type", "expiry",
        "strike", "option_type", "packet_type", "ltt_epoch", "exchange_ts", "receive_ts", "receive_ns", "ltp", "ltq",
        "avg_price", "volume", "oi", "oi_day_high", "oi_day_low", "total_buy_qty", "total_sell_qty", "day_open",
        "day_high", "day_low", "day_close_field", "prev_close", "prev_oi", "bid_price_1", "bid_qty_1", "bid_orders_1",
        "ask_price_1", "ask_qty_1", "ask_orders_1", "depth", "payload_hash", "raw_packet",
    ),
    "hr_ohlc_5s": (
        "session_id", "symbol", "exchange_segment", "security_id", "instrument_type", "bar_ts", "open", "high", "low",
        "close", "volume", "cumulative_volume_end", "update_count", "trade_count", "first_trade_ts", "last_trade_ts",
        "first_receive_ts", "last_receive_ts", "source", "data_quality",
    ),
    "hr_option_5s": (
        "session_id", "symbol", "exchange_segment", "security_id", "expiry", "strike", "option_type", "atm_offset",
        "bar_ts", "updated_in_bucket", "update_count", "trade_count", "ltp", "bid", "ask", "mid", "spread",
        "spread_pct", "quote_age_s", "volume_delta", "cumulative_volume", "oi", "oi_delta", "bid_qty_l1",
        "ask_qty_l1", "bid_qty_total5", "ask_qty_total5", "depth_imbalance", "data_quality",
    ),
    "hr_option_transition_state": (
        "session_id", "symbol", "bar_ts", "band_atm_strike", "parity_atm_strike", "underlying_last_price",
        "underlying_status", "underlying_seconds_since_packet", "underlying_seconds_since_change",
        "last_reliable_underlying_price", "last_reliable_underlying_ts", "futures_last_price", "futures_status",
        "futures_bid", "futures_ask", "futures_volume_delta", "options_expected", "options_updated",
        "options_with_valid_quotes", "ce_volume_delta_sum", "pe_volume_delta_sum", "ce_volume_delta_change",
        "pe_volume_delta_change", "ce_oi_delta_sum", "pe_oi_delta_sum", "ce_oi_delta_n", "pe_oi_delta_n",
        "ce_l1_imbalance", "pe_l1_imbalance", "ce_depth_imbalance", "pe_depth_imbalance", "straddle_mid",
        "straddle_change", "straddle_change_delta", "pcr_oi", "pcr_oi_change", "pcr_volume",
        "option_implied_spot_research_only", "implied_spot_method", "implied_spot_n", "implied_spot_iqr",
        "implied_spot_strikes", "implied_spot_quality", "implied_spot_calc_ts", "market_state", "data_quality",
    ),
    "hr_capture_events": ("session_id", "event_ts", "event_type", "symbol", "detail"),
}

JSONB_COLUMNS = {
    "hr_capture_sessions": {"config", "quality_summary"},
    "hr_raw_ticks": {"depth"},
    "hr_option_transition_state": {"implied_spot_strikes"},
    "hr_capture_events": {"detail"},
}


def connect(config: HRConfig) -> psycopg.Connection:
    options = (
        f"-c search_path={DB_SCHEMA},public -c statement_timeout={config.db_statement_timeout_ms} "
        f"-c lock_timeout={config.db_lock_timeout_ms}"
    )
    return psycopg.connect(
        require_database_url(), autocommit=True, application_name="hr_capture", options=options,
        connect_timeout=10, keepalives=1, keepalives_idle=30, keepalives_interval=10, keepalives_count=3,
    )


def insert_sql(table: str) -> str:
    if not table.startswith("hr_") or table not in TABLE_COLUMNS:
        raise ValueError(f"HR writer refuses non-hr table: {table!r}")
    columns = TABLE_COLUMNS[table]
    return (f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({', '.join(['%s'] * len(columns))}) "
            "ON CONFLICT DO NOTHING")


def adapt_row(table: str, row: dict) -> tuple:
    json_cols = JSONB_COLUMNS.get(table, set())
    return tuple(
        Jsonb(row.get(col)) if col in json_cols and row.get(col) is not None else row.get(col)
        for col in TABLE_COLUMNS[table]
    )


FINALIZE_SESSION_SQL = """
UPDATE hr_capture_sessions SET
    ended_at = %s, status = %s, instruments_received = %s, packets_received = %s, ticks_persisted = %s,
    duplicates_dropped = %s, reconnect_count = %s, gap_count = %s, error_count = %s, ltt_convention = %s,
    quality_summary = %s
WHERE session_id = %s
"""

BACKFILL_EXCHANGE_TS_SQL = """
UPDATE hr_raw_ticks SET exchange_ts = to_timestamp(ltt_epoch - %s)
WHERE session_id = %s AND exchange_ts IS NULL AND ltt_epoch > 0
"""
