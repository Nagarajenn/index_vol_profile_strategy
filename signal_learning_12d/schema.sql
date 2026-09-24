-- 12D-signal-learning-v1. Package-owned schema (db/schema.sql is frozen).
-- Created by signal_learning_12d.learning_dataset.apply_schema, which asserts only sl12d_*
-- objects appear here. Observation only: no trading code reads these tables.

CREATE TABLE IF NOT EXISTS sl12d_signals (
    id                      BIGSERIAL PRIMARY KEY,
    signal_id               TEXT NOT NULL,
    market                  TEXT NOT NULL,
    session_date            DATE NOT NULL,
    signal_minute           TEXT NOT NULL,
    direction               TEXT NOT NULL,
    side                    TEXT NOT NULL,
    strike                  DOUBLE PRECISION,
    expiry                  DATE,
    contract                TEXT,
    confidence              TEXT,
    signal_reason           TEXT,
    episode_minutes         INTEGER,

    -- entry, priced at the ASK a buyer would actually pay
    entry_minute            TEXT,
    entry_price             DOUBLE PRECISION,
    entry_price_type        TEXT,
    quantity                INTEGER,
    quantity_source         TEXT,

    -- entry-time assessment (from data <= signal_minute only)
    entry_timing            TEXT,
    entry_timing_note       TEXT,
    entry_timing_provisional BOOLEAN,
    momentum_state          TEXT,
    momentum_note           TEXT,
    exhaustion_state        TEXT,
    exhaustion_note         TEXT,
    entry_features          JSONB,

    -- outcomes (future data, used ONLY for scoring)
    outcome_1m              DOUBLE PRECISION, outcome_3m  DOUBLE PRECISION,
    outcome_5m              DOUBLE PRECISION, outcome_10m DOUBLE PRECISION,
    outcome_1m_pct          DOUBLE PRECISION, outcome_3m_pct  DOUBLE PRECISION,
    outcome_5m_pct          DOUBLE PRECISION, outcome_10m_pct DOUBLE PRECISION,
    mfe_1m  DOUBLE PRECISION, mfe_3m  DOUBLE PRECISION, mfe_5m  DOUBLE PRECISION, mfe_10m DOUBLE PRECISION,
    mae_1m  DOUBLE PRECISION, mae_3m  DOUBLE PRECISION, mae_5m  DOUBLE PRECISION, mae_10m DOUBLE PRECISION,
    mfe_per_unit            DOUBLE PRECISION,
    mae_per_unit            DOUBLE PRECISION,
    mfe_pct                 DOUBLE PRECISION,
    mae_pct                 DOUBLE PRECISION,
    time_to_mfe             INTEGER,
    time_to_mae             INTEGER,
    marks_observed          INTEGER,

    -- exit, priced at the BID a seller would actually receive
    exit_minute             TEXT,
    exit_bid                DOUBLE PRECISION,
    exit_reason             TEXT NOT NULL,
    hold_minutes            INTEGER,
    final_pnl_per_unit      DOUBLE PRECISION,
    final_pnl               DOUBLE PRECISION,
    final_pnl_pct           DOUBLE PRECISION,

    -- position management, independent of the entry decision
    position_path           TEXT,
    position_final_state    TEXT,
    minutes_in_caution      INTEGER,
    minutes_in_prepare_exit INTEGER,
    entry_decision_went_wait_at TEXT,
    entry_waits_survived    INTEGER,

    -- labels
    outcome_label           TEXT,
    lifecycle_label         TEXT,
    direction_correct       BOOLEAN,
    entry_timing_ok         BOOLEAN,
    exit_ok                 BOOLEAN,
    capture_ratio           DOUBLE PRECISION,

    -- provenance
    version                 TEXT NOT NULL,
    config_hash             TEXT NOT NULL,
    decision_config_hash    TEXT,
    computed_at             TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE (signal_id, config_hash)
);
CREATE INDEX IF NOT EXISTS idx_sl12d_market_date ON sl12d_signals (market, session_date DESC);
CREATE INDEX IF NOT EXISTS idx_sl12d_timing ON sl12d_signals (entry_timing, momentum_state);
