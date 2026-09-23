-- 13-live-trading-v1. Package-owned schema: db/schema.sql is frozen, so these tables are
-- created by live_trading.state.apply_schema, which asserts only live_* objects appear here.

CREATE TABLE IF NOT EXISTS live_session_state (
    id                BIGSERIAL PRIMARY KEY,
    symbol            TEXT NOT NULL,
    session_date      DATE NOT NULL,
    armed             BOOLEAN NOT NULL DEFAULT FALSE,   -- disarmed on every process start
    halted            BOOLEAN NOT NULL DEFAULT FALSE,
    halt_reason       TEXT,
    kill_switch       BOOLEAN NOT NULL DEFAULT FALSE,
    entries_used      INTEGER NOT NULL DEFAULT 0,
    realised_pnl      DOUBLE PRECISION NOT NULL DEFAULT 0,
    armed_at          TIMESTAMPTZ,
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (symbol, session_date)
);

-- Append-only. One row per order INTENT, whether or not it ever reached the broker: a day
-- with no trades must be as explainable as a day with two.
CREATE TABLE IF NOT EXISTS live_orders (
    id                BIGSERIAL PRIMARY KEY,
    correlation_id    TEXT NOT NULL UNIQUE,             -- (symbol, date, signal_minute) -> idempotency
    symbol            TEXT NOT NULL,
    session_date      DATE NOT NULL,
    signal_minute     TEXT NOT NULL,
    decision          TEXT NOT NULL,                    -- BUY_CE / BUY_PE
    confirmation      TEXT,
    decision_reason   TEXT,
    episode_minutes   INTEGER,
    contract_label    TEXT,
    security_id       TEXT,
    exchange_segment  TEXT,
    option_type       TEXT,
    strike            DOUBLE PRECISION,
    expiry            DATE,
    quantity          INTEGER,
    lot_size          INTEGER,
    ask               DOUBLE PRECISION,
    bid               DOUBLE PRECISION,
    spread_pct        DOUBLE PRECISION,
    limit_price       DOUBLE PRECISION,
    entry_cost        DOUBLE PRECISION,
    status            TEXT NOT NULL,                    -- REFUSED / DRY_RUN / SENT / FILLED / NOT_FILLED / REJECTED / ERROR
    refusal_reasons   JSONB,                            -- every guard that said no, named
    guards_passed     JSONB,
    dry_run           BOOLEAN NOT NULL,
    broker_request    JSONB,
    broker_response   JSONB,
    broker_order_id   TEXT,
    fill_price        DOUBLE PRECISION,
    filled_at         TIMESTAMPTZ,
    evidence          JSONB,                            -- the 12C evidence snapshot behind the intent
    live_version      TEXT NOT NULL,
    live_config_hash  TEXT NOT NULL,
    decision_config_hash TEXT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_live_orders_symbol_date ON live_orders (symbol, session_date DESC);

CREATE TABLE IF NOT EXISTS live_positions (
    id                BIGSERIAL PRIMARY KEY,
    correlation_id    TEXT NOT NULL UNIQUE REFERENCES live_orders (correlation_id),
    symbol            TEXT NOT NULL,
    session_date      DATE NOT NULL,
    contract_label    TEXT NOT NULL,
    security_id       TEXT NOT NULL,
    option_type       TEXT NOT NULL,
    strike            DOUBLE PRECISION NOT NULL,
    expiry            DATE,
    quantity          INTEGER NOT NULL,
    entry_price       DOUBLE PRECISION NOT NULL,
    entry_at          TIMESTAMPTZ NOT NULL,
    entry_cost        DOUBLE PRECISION,
    exit_price        DOUBLE PRECISION,
    exit_at           TIMESTAMPTZ,
    exit_route        TEXT,                             -- TRADER / FORCE_FLAT_15_10 / BROKER
    realised_pnl      DOUBLE PRECISION,
    is_open           BOOLEAN NOT NULL DEFAULT TRUE,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_live_positions_open ON live_positions (symbol, session_date DESC, is_open);

-- Every refusal, arm, disarm, kill and force-flat, so the session reads as a narrative.
CREATE TABLE IF NOT EXISTS live_journal (
    id                BIGSERIAL PRIMARY KEY,
    symbol            TEXT,
    session_date      DATE NOT NULL,
    at                TIMESTAMPTZ NOT NULL DEFAULT now(),
    minute            TEXT,
    event             TEXT NOT NULL,
    detail            TEXT,
    payload           JSONB
);
CREATE INDEX IF NOT EXISTS idx_live_journal_date ON live_journal (session_date DESC, at DESC);
