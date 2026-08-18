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

-- Market Transition Intelligence (research engine, independent of the
-- trading decision engine -- see market_transition/ package). One row per
-- symbol/session_date: the extracted 2-3pm features/outcome plus the most
-- recently computed research score (recomputed and overwritten each time
-- scripts/run_market_transition_research.py runs, since the score depends
-- on the current correlation study across all history, not just this day).
CREATE TABLE IF NOT EXISTS mti_daily_transitions (
    id BIGSERIAL PRIMARY KEY,
    symbol TEXT NOT NULL,
    session_date DATE NOT NULL,
    poc_migration_1400_1459 DOUBLE PRECISION,
    vwap_distance_1459 DOUBLE PRECISION,
    vwap_distance_1459_pct DOUBLE PRECISION,
    volume_slope_1400_1459 DOUBLE PRECISION,
    realized_range_1400_1459 DOUBLE PRECISION,
    profile_shape_1459 TEXT,
    rotation_label_1459 TEXT,
    market_regime_1459 TEXT,
    is_inside_initial_balance_1459 BOOLEAN,
    day_of_week SMALLINT,
    expiry_type TEXT,
    prior_day_profile_shape TEXT,
    prior_day_close_vs_poc TEXT,
    close_1459 DOUBLE PRECISION NOT NULL,
    close_1501 DOUBLE PRECISION NOT NULL,
    market_close DOUBLE PRECISION NOT NULL,
    transition_move DOUBLE PRECISION NOT NULL,
    transition_direction TEXT NOT NULL,
    post_transition_move DOUBLE PRECISION NOT NULL,
    outcome TEXT NOT NULL CHECK (outcome IN ('continuation', 'reversal', 'neutral')),
    outcome_magnitude DOUBLE PRECISION NOT NULL,
    transition_risk_score DOUBLE PRECISION,
    probability_continuation DOUBLE PRECISION,
    probability_reversal DOUBLE PRECISION,
    expected_volatility DOUBLE PRECISION,
    expected_direction TEXT,
    historical_similarity_score DOUBLE PRECISION,
    top_contributing_factors JSONB,
    statistical_confidence TEXT,
    explanation TEXT,
    computed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (symbol, session_date)
);
CREATE INDEX IF NOT EXISTS idx_mti_daily_symbol_date ON mti_daily_transitions (symbol, session_date DESC);

-- One row per symbol/factor/target: the current correlation-study finding.
-- Overwritten (upserted) each research run -- this table always reflects
-- the latest study, not a history of past studies.
CREATE TABLE IF NOT EXISTS mti_factor_correlations (
    id BIGSERIAL PRIMARY KEY,
    symbol TEXT NOT NULL,
    factor_name TEXT NOT NULL,
    factor_type TEXT NOT NULL CHECK (factor_type IN ('continuous', 'categorical')),
    target TEXT NOT NULL CHECK (target IN ('reversal', 'magnitude')),
    n_days INTEGER NOT NULL,
    statistic DOUBLE PRECISION,
    p_value DOUBLE PRECISION,
    confidence_label TEXT NOT NULL,
    direction_note TEXT,
    category_breakdown JSONB,
    computed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (symbol, factor_name, target)
);
CREATE INDEX IF NOT EXISTS idx_mti_correlations_symbol ON mti_factor_correlations (symbol);

-- Quant Feature Store & Forward Outcome Engine (see quant_features/ package).
-- Wraps/flattens every existing analytics module (VWAP, Volume Profile
-- Intelligence, the Volume Intelligence Engine, the trend/confidence
-- decision engine, market regime, expiry calendar, option chain, news) into
-- versioned, leakage-safe per-minute rows for backtesting/threshold-tuning/
-- a future ML step. Purely additive/informational -- feeds no existing
-- trading-decision logic. `feature_version` is part of every unique key so
-- a future feature-catalogue revision can be backfilled alongside the old
-- one without deleting history.
--
-- Column names below match quant_features/models.py's dataclass field names
-- 1:1 (MarketFeatureRow's price/vwap/volume_profile/volume_intelligence/
-- structure/decision/regime/expiry/news sub-dataclasses flattened in that
-- order) -- db/writer.py derives its column list directly from those
-- dataclasses, so a new field only needs a matching column added here.
CREATE TABLE IF NOT EXISTS quant_market_features (
    id BIGSERIAL PRIMARY KEY,
    symbol TEXT NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    feature_version TEXT NOT NULL,
    -- PriceVolatilityFeatures
    close DOUBLE PRECISION NOT NULL,
    ret_1m DOUBLE PRECISION,
    ret_5m DOUBLE PRECISION,
    realized_vol_20m DOUBLE PRECISION,
    atr_14 DOUBLE PRECISION,
    gap_open_pct DOUBLE PRECISION,
    body_pct DOUBLE PRECISION,
    upper_wick_pct DOUBLE PRECISION,
    lower_wick_pct DOUBLE PRECISION,
    -- VwapFeatures
    vwap_now DOUBLE PRECISION,
    vwap_distance_pct DOUBLE PRECISION,
    vwap_distance_atr DOUBLE PRECISION,
    vwap_slope_5m DOUBLE PRECISION,
    -- VolumeProfileFeatureSet
    today_poc DOUBLE PRECISION,
    today_vah DOUBLE PRECISION,
    today_val DOUBLE PRECISION,
    poc_distance_pct DOUBLE PRECISION,
    profile_shape TEXT,
    opening_type TEXT,
    rotation_label TEXT,
    volume_pace_pct DOUBLE PRECISION,
    is_inside_initial_balance BOOLEAN,
    poc_migration_intraday DOUBLE PRECISION,
    -- VolumeIntelligenceFeatureSet
    rvol_interval_pct DOUBLE PRECISION,
    rvol_cumulative_pct DOUBLE PRECISION,
    rvol_label TEXT,
    volume_acceleration_label TEXT,
    dominance_ratio DOUBLE PRECISION,
    dominant_side TEXT,
    consecutive_dominant_minutes INTEGER,
    cumulative_pressure_ratio DOUBLE PRECISION,
    momentum_score DOUBLE PRECISION,
    momentum_label TEXT,
    institutional_participation_score INTEGER,
    institutional_participation_label TEXT,
    is_volume_spike BOOLEAN,
    is_volume_dryup BOOLEAN,
    is_absorption BOOLEAN,
    is_exhaustion BOOLEAN,
    volume_trend_label TEXT,
    volume_character_label TEXT,
    historical_similarity_top1_score DOUBLE PRECISION,
    forecast_probability_continuation DOUBLE PRECISION,
    forecast_confidence TEXT,
    -- StructureFeatureSet
    support_low DOUBLE PRECISION,
    support_high DOUBLE PRECISION,
    resistance_low DOUBLE PRECISION,
    resistance_high DOUBLE PRECISION,
    support_distance_pct DOUBLE PRECISION,
    resistance_distance_pct DOUBLE PRECISION,
    nearest_trendline_touch_count INTEGER,
    nearest_trendline_direction TEXT,
    breakout_box_status TEXT,
    swing_structure_score SMALLINT,
    -- DecisionFeatureSet
    trend_label TEXT,
    trend_score SMALLINT,
    confidence_score SMALLINT,
    sub_score_trend_alignment DOUBLE PRECISION,
    sub_score_vwap_position DOUBLE PRECISION,
    sub_score_structure_hh_hl DOUBLE PRECISION,
    sub_score_trendline_confluence DOUBLE PRECISION,
    sub_score_sr_proximity DOUBLE PRECISION,
    sub_score_breakout_confirmation DOUBLE PRECISION,
    sub_score_institutional_bias DOUBLE PRECISION,
    confidence_partial_data BOOLEAN,
    -- RegimeFeatureSet
    market_regime_3way TEXT,
    market_regime_expanded TEXT,
    volatility_pace_pct DOUBLE PRECISION,
    -- ExpiryFeatureSet
    expiry_type TEXT,
    is_expiry_day BOOLEAN,
    days_to_weekly_expiry INTEGER,
    days_to_monthly_expiry INTEGER,
    day_of_week SMALLINT,
    minutes_since_open INTEGER,
    -- NewsFeatureSet
    event_count_30m INTEGER,
    max_severity_30m SMALLINT,
    dominant_sentiment_30m TEXT,
    most_recent_event_direction TEXT,
    most_recent_event_risk_level TEXT,
    -- DataQualityFlags
    data_quality_flags JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (symbol, timestamp, feature_version)
);
CREATE INDEX IF NOT EXISTS idx_quant_market_features_symbol_ts ON quant_market_features (symbol, timestamp DESC);

-- Only populated while a live option_chain_raw snapshot exists at/before a
-- given timestamp -- a much shorter history than quant_market_features
-- (Dhan's option chain API is live-only, no historical backfill), hence a
-- separate table rather than nullable columns bolted onto the wide table
-- above -- exactly why option_chain_summary is already separate from
-- raw_candles in this schema.
CREATE TABLE IF NOT EXISTS quant_option_features (
    id BIGSERIAL PRIMARY KEY,
    symbol TEXT NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    feature_version TEXT NOT NULL,
    expiry DATE,
    spot DOUBLE PRECISION,
    atm_strike DOUBLE PRECISION,
    pcr DOUBLE PRECISION,
    atm_iv_call DOUBLE PRECISION,
    atm_iv_put DOUBLE PRECISION,
    atm_iv_skew DOUBLE PRECISION,
    call_oi_wall_strike DOUBLE PRECISION,
    put_oi_wall_strike DOUBLE PRECISION,
    call_oi_delta_intraday DOUBLE PRECISION,
    put_oi_delta_intraday DOUBLE PRECISION,
    strike_ladder JSONB,
    data_quality_flags JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (symbol, timestamp, feature_version)
);
CREATE INDEX IF NOT EXISTS idx_quant_option_features_symbol_ts ON quant_option_features (symbol, timestamp DESC);

-- Written by a separate, LATER-running process than the two tables above --
-- a row can't be labeled until enough future candles genuinely exist, so
-- feature computation and labeling are independently re-runnable (e.g.
-- redefining horizons doesn't require recomputing input features).
CREATE TABLE IF NOT EXISTS quant_forward_outcomes (
    id BIGSERIAL PRIMARY KEY,
    symbol TEXT NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    feature_version TEXT NOT NULL,
    atr_at_t DOUBLE PRECISION,
    fwd_return_1m DOUBLE PRECISION,
    fwd_return_3m DOUBLE PRECISION,
    fwd_return_5m DOUBLE PRECISION,
    fwd_return_10m DOUBLE PRECISION,
    fwd_return_15m DOUBLE PRECISION,
    fwd_return_30m DOUBLE PRECISION,
    mfe_1m DOUBLE PRECISION,
    mae_1m DOUBLE PRECISION,
    mfe_5m DOUBLE PRECISION,
    mae_5m DOUBLE PRECISION,
    mfe_15m DOUBLE PRECISION,
    mae_15m DOUBLE PRECISION,
    mfe_30m DOUBLE PRECISION,
    mae_30m DOUBLE PRECISION,
    label_5m TEXT,
    label_15m TEXT,
    label_30m TEXT,
    horizon_truncated_by_session_close BOOLEAN NOT NULL DEFAULT false,
    computed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (symbol, timestamp, feature_version)
);
CREATE INDEX IF NOT EXISTS idx_quant_forward_outcomes_symbol_ts ON quant_forward_outcomes (symbol, timestamp DESC);

-- Audit/provenance log -- one row per batch backfill / live incremental /
-- labeling run. The concrete implementation of "feature versioning" as a
-- run-level guarantee, not just a column value.
CREATE TABLE IF NOT EXISTS quant_feature_runs (
    id BIGSERIAL PRIMARY KEY,
    run_type TEXT NOT NULL CHECK (run_type IN ('batch_backfill', 'live_incremental', 'labeling')),
    feature_version TEXT NOT NULL,
    symbol TEXT NOT NULL,
    start_date DATE,
    end_date DATE,
    rows_written INTEGER NOT NULL DEFAULT 0,
    started_at TIMESTAMPTZ NOT NULL,
    finished_at TIMESTAMPTZ,
    status TEXT NOT NULL CHECK (status IN ('running', 'completed', 'failed')),
    error_message TEXT
);
CREATE INDEX IF NOT EXISTS idx_quant_feature_runs_symbol ON quant_feature_runs (symbol, started_at DESC);
