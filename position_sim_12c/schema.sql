-- 12C-position-simulation-v1 history. SIMULATION ONLY: these rows describe hypothetical
-- positions derived from 12C decisions. They are not orders, not paper-account trades, and
-- nothing in the trading path reads them. Only sim12c_* objects are created here; no existing
-- table is touched.
CREATE TABLE IF NOT EXISTS sim12c_positions (
    id BIGSERIAL PRIMARY KEY,
    symbol TEXT NOT NULL,
    session_date DATE NOT NULL,

    -- the signal that opened it
    signal_minute TEXT NOT NULL,
    entry_minute TEXT NOT NULL,
    entry_confirmation TEXT,
    side TEXT NOT NULL CHECK (side IN ('CE', 'PE')),
    strike DOUBLE PRECISION,
    expiry DATE,
    contract TEXT,

    -- entry is always the ASK; the LTP is kept only for reference
    entry_price DOUBLE PRECISION,
    entry_price_type TEXT NOT NULL DEFAULT 'ASK',
    entry_ltp DOUBLE PRECISION,
    quantity INTEGER,
    quantity_source TEXT,
    entry_value DOUBLE PRECISION,

    -- advisory stop
    stop_loss_pct DOUBLE PRECISION,
    stop_loss_price DOUBLE PRECISION,
    stop_breach_minute TEXT,

    -- the exit, and WHICH DECISION closed it
    exit_minute TEXT,
    exit_bid DOUBLE PRECISION,
    exit_reason TEXT,                -- WAIT | SIGNAL_FLIP | STOP_BREACH | SESSION_END
    closing_decision TEXT,           -- the 12C decision at the exit minute
    closing_confirmation TEXT,
    closing_reason TEXT,             -- the decision's own plain-English reason
    risk_state_at_exit TEXT,
    families_against_at_exit JSONB,

    -- outcome (BID-based)
    realised_pnl_per_unit DOUBLE PRECISION,
    realised_pnl DOUBLE PRECISION,
    realised_pnl_pct DOUBLE PRECISION,
    mfe_per_unit DOUBLE PRECISION,
    mae_per_unit DOUBLE PRECISION,
    mfe DOUBLE PRECISION,
    mae DOUBLE PRECISION,
    hold_minutes INTEGER,

    -- provenance, so a row can always be tied back to the exact rules that produced it
    sim_version TEXT NOT NULL,
    sim_config_hash TEXT NOT NULL,
    decision_config_hash TEXT NOT NULL,
    entry_at_next_minute BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (symbol, session_date, signal_minute, side, strike, sim_config_hash)
);
CREATE INDEX IF NOT EXISTS idx_sim12c_positions_date ON sim12c_positions (session_date DESC, symbol);
