-- Raw input data: 1-min candles (finest granularity Dhan's REST intraday API supports)
CREATE TABLE IF NOT EXISTS raw_candles (
    id BIGSERIAL PRIMARY KEY,
    symbol TEXT NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    open DOUBLE PRECISION NOT NULL,
    high DOUBLE PRECISION NOT NULL,
    low DOUBLE PRECISION NOT NULL,
    close DOUBLE PRECISION NOT NULL,
    volume DOUBLE PRECISION NOT NULL,
    open_interest DOUBLE PRECISION,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (symbol, timestamp)
);
CREATE INDEX IF NOT EXISTS idx_raw_candles_symbol_ts ON raw_candles (symbol, timestamp DESC);

-- Raw input data: daily candles (prior-day H/L/C reference)
CREATE TABLE IF NOT EXISTS raw_daily_candles (
    id BIGSERIAL PRIMARY KEY,
    symbol TEXT NOT NULL,
    date DATE NOT NULL,
    open DOUBLE PRECISION NOT NULL,
    high DOUBLE PRECISION NOT NULL,
    low DOUBLE PRECISION NOT NULL,
    close DOUBLE PRECISION NOT NULL,
    volume DOUBLE PRECISION NOT NULL,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (symbol, date)
);

-- Raw input data: full option chain payload as fetched (live only)
CREATE TABLE IF NOT EXISTS option_chain_raw (
    id BIGSERIAL PRIMARY KEY,
    symbol TEXT NOT NULL,
    expiry DATE NOT NULL,
    fetched_at TIMESTAMPTZ NOT NULL,
    spot DOUBLE PRECISION,
    raw_payload JSONB NOT NULL,
    UNIQUE (symbol, expiry, fetched_at)
);

-- Derived (but cheap/queryable) option chain summary: PCR, OI deltas, IV, OI walls
CREATE TABLE IF NOT EXISTS option_chain_summary (
    id BIGSERIAL PRIMARY KEY,
    symbol TEXT NOT NULL,
    expiry DATE NOT NULL,
    fetched_at TIMESTAMPTZ NOT NULL,
    spot DOUBLE PRECISION,
    atm_strike DOUBLE PRECISION,
    pcr DOUBLE PRECISION,
    call_oi_change_near_atm DOUBLE PRECISION,
    put_oi_change_near_atm DOUBLE PRECISION,
    total_call_oi DOUBLE PRECISION,
    total_put_oi DOUBLE PRECISION,
    atm_iv_call DOUBLE PRECISION,
    atm_iv_put DOUBLE PRECISION,
    max_call_oi_strike DOUBLE PRECISION,
    max_put_oi_strike DOUBLE PRECISION,
    UNIQUE (symbol, expiry, fetched_at)
);

-- Final computed output: one row per (symbol, as_of) checkpoint
CREATE TABLE IF NOT EXISTS levels_snapshots (
    id BIGSERIAL PRIMARY KEY,
    symbol TEXT NOT NULL,
    as_of TIMESTAMPTZ NOT NULL,
    mode TEXT NOT NULL CHECK (mode IN ('live', 'backfill')),
    close DOUBLE PRECISION NOT NULL,
    vwap_now DOUBLE PRECISION,
    today_poc DOUBLE PRECISION,
    today_vah DOUBLE PRECISION,
    today_val DOUBLE PRECISION,
    today_total_volume DOUBLE PRECISION,
    yesterday_poc DOUBLE PRECISION,
    yesterday_vah DOUBLE PRECISION,
    yesterday_val DOUBLE PRECISION,
    support_low DOUBLE PRECISION,
    support_high DOUBLE PRECISION,
    resistance_low DOUBLE PRECISION,
    resistance_high DOUBLE PRECISION,
    trend_label TEXT,
    trend_score SMALLINT,
    institutional_bias_label TEXT,
    institutional_bias_score SMALLINT,
    institutional_bias_data TEXT,
    confidence_score SMALLINT,
    sub_score_trend_alignment DOUBLE PRECISION,
    sub_score_vwap_position DOUBLE PRECISION,
    sub_score_structure_hh_hl DOUBLE PRECISION,
    sub_score_trendline_confluence DOUBLE PRECISION,
    sub_score_sr_proximity DOUBLE PRECISION,
    sub_score_breakout_confirmation DOUBLE PRECISION,
    sub_score_institutional_bias DOUBLE PRECISION,
    confidence_weights_used JSONB,
    confidence_partial_data BOOLEAN,
    action_text TEXT,
    today_vp_bins JSONB,
    swings JSONB,
    trendlines JSONB,
    breakout_boxes JSONB,
    chart_path TEXT,
    chart_triggered_by TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (symbol, as_of)
);
CREATE INDEX IF NOT EXISTS idx_levels_symbol_asof ON levels_snapshots (symbol, as_of DESC);
CREATE INDEX IF NOT EXISTS idx_levels_symbol_mode_asof ON levels_snapshots (symbol, mode, as_of DESC);
-- (symbol, mode, as_of::date) would be a tighter index for should_render_chart()'s
-- "today's rows" lookup, but ::date on a timestamptz isn't IMMUTABLE (it's
-- timezone-dependent) so Postgres won't allow it in a plain index expression.
-- Not worth an IMMUTABLE wrapper function for this data volume (low
-- thousands of rows) -- the composite index above is enough for Postgres to
-- narrow by symbol+mode efficiently before filtering the date client-side.

-- Project/requirements audit trail -- NOT part of the trading data model,
-- purely a durable record of feature requirements as they're submitted, so
-- "what was asked for and when" survives independent of chat history or
-- PROJECT_STATUS.md edits.
-- Market Intelligence Engine: raw collected news + AI classification.
-- Independent of the trading data model (raw_candles/levels_snapshots) --
-- purely additive, informational, does not feed the strategy engine.
CREATE TABLE IF NOT EXISTS news_items (
    id BIGSERIAL PRIMARY KEY,
    source TEXT NOT NULL,
    title TEXT NOT NULL,
    link TEXT NOT NULL,
    guid TEXT NOT NULL,
    published_at TIMESTAMPTZ,
    summary TEXT,
    collected_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (source, guid)
);
CREATE INDEX IF NOT EXISTS idx_news_items_collected ON news_items (collected_at DESC);

CREATE TABLE IF NOT EXISTS classified_events (
    id BIGSERIAL PRIMARY KEY,
    news_item_id BIGINT NOT NULL REFERENCES news_items (id),
    is_relevant BOOLEAN NOT NULL,
    category TEXT NOT NULL,
    severity SMALLINT NOT NULL CHECK (severity BETWEEN 1 AND 5),
    confidence DOUBLE PRECISION NOT NULL,
    sentiment TEXT NOT NULL,
    expected_duration TEXT NOT NULL,
    volatility_impact TEXT NOT NULL,
    reversal_probability DOUBLE PRECISION NOT NULL,
    affected_sectors JSONB NOT NULL,
    affected_indices JSONB NOT NULL,
    expected_direction_nifty TEXT NOT NULL,
    expected_direction_sensex TEXT NOT NULL,
    expected_direction_banknifty TEXT NOT NULL,
    recommended_action TEXT NOT NULL,
    risk_level TEXT NOT NULL,
    rationale TEXT NOT NULL,
    model TEXT NOT NULL,
    classified_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (news_item_id)
);
CREATE INDEX IF NOT EXISTS idx_classified_events_classified_at ON classified_events (classified_at DESC);
CREATE INDEX IF NOT EXISTS idx_classified_events_relevant_at ON classified_events (is_relevant, classified_at DESC);

CREATE TABLE IF NOT EXISTS product_requirements (
    id BIGSERIAL PRIMARY KEY,
    title TEXT NOT NULL,
    submitted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    requirement_text TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'submitted' CHECK (status IN ('submitted', 'planned', 'in_progress', 'shipped', 'deferred')),
    notes TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_product_requirements_submitted ON product_requirements (submitted_at DESC);
