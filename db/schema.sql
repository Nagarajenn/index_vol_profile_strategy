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

-- CAS Intelligence (see market_transition/cas_transition.py): additive,
-- parallel re-analysis of the 3pm transition under NSE's post-2026-08-03
-- Closing Auction Session framework. One row per symbol/session_date,
-- recomputed and upserted on each daily run -- entirely independent of
-- mti_daily_transitions/mti_factor_correlations (the original methodology,
-- still the source of truth for the Live Advisor and the existing
-- dashboard read). old_methodology_* columns carry the same day's outcome
-- under the original engine, purely for side-by-side comparison.
CREATE TABLE IF NOT EXISTS mti_cas_daily_transitions (
    id BIGSERIAL PRIMARY KEY,
    symbol TEXT NOT NULL,
    session_date DATE NOT NULL,
    close_1431 DOUBLE PRECISION,
    close_1459 DOUBLE PRECISION,
    close_1539 DOUBLE PRECISION,
    pre_direction TEXT,
    post_direction TEXT,
    conclusion TEXT NOT NULL CHECK (conclusion IN ('continuation', 'reversal', 'neutral')),
    outcome_magnitude DOUBLE PRECISION,
    pre_window_volume DOUBLE PRECISION,
    -- Only summed through 15:14: NSE's Closing Auction Session starts at
    -- 15:15 and Dhan's 1-min volume field is not reliable from that point
    -- through close (confirmed 2026-08-21 -- price keeps moving genuinely,
    -- volume freezes at one value). Never claims to cover 15:15-15:39.
    post_window_pre_auction_volume DOUBLE PRECISION,
    volume_ratio DOUBLE PRECISION,
    -- Signed points move using the best print actually reached (high for
    -- "up", low for "down"; positive = ran up, negative = ran down), not
    -- just the close-to-close net move -- price stays reliable through
    -- 15:39 (only volume freezes at 15:15), so post_window_points_move
    -- uses the full 15:00-15:39 window, unlike the volume columns above.
    pre_window_points_move DOUBLE PRECISION,
    post_window_points_move DOUBLE PRECISION,
    pcr_1459 DOUBLE PRECISION,
    institutional_bias_label_1459 TEXT,
    institutional_bias_score_1459 SMALLINT,
    expiry_type TEXT,
    day_of_week SMALLINT,
    old_methodology_outcome TEXT,
    old_methodology_outcome_magnitude DOUBLE PRECISION,
    data_quality_flag TEXT,
    -- Independent-dimension reclassification (Phase 7A): `conclusion` above
    -- stays untouched (still powers the correlation study/agreement
    -- comparison unchanged) -- these are additive, richer fields so a flat
    -- pre-window + large post-window move is no longer indistinguishable
    -- from a genuinely quiet day (see market_transition/cas_transition.py::
    -- classify_transition_type/classify_transition_magnitude).
    transition_type TEXT NOT NULL DEFAULT 'NO_MATERIAL_TRANSITION' CHECK (transition_type IN (
        'CONTINUATION_UP', 'CONTINUATION_DOWN', 'REVERSAL_UP', 'REVERSAL_DOWN',
        'POST_WINDOW_INITIATION_UP', 'POST_WINDOW_INITIATION_DOWN', 'NO_MATERIAL_TRANSITION'
    )),
    magnitude_pct_return DOUBLE PRECISION,
    magnitude_atr_normalized DOUBLE PRECISION,
    magnitude_tier TEXT CHECK (magnitude_tier IN ('NORMAL', 'MODERATE', 'LARGE', 'EXTREME') OR magnitude_tier IS NULL),
    computed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (symbol, session_date)
);
CREATE INDEX IF NOT EXISTS idx_mti_cas_daily_symbol_date ON mti_cas_daily_transitions (symbol, session_date DESC);

-- CAS factor-correlation study (see market_transition/cas_statistics.py) --
-- the same statistical machinery as mti_factor_correlations, reused
-- unmodified, applied to the CAS-adjusted outcome plus the new option/
-- volume/points-move dimensions mti_cas_daily_transitions introduced.
-- Overwritten (upserted) each daily run, same convention as the original.
CREATE TABLE IF NOT EXISTS mti_cas_factor_correlations (
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
CREATE INDEX IF NOT EXISTS idx_mti_cas_correlations_symbol ON mti_cas_factor_correlations (symbol);
