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

-- Dual-resolution pre/post-3pm transition detail (Phase 7B, see
-- market_transition/cas_windows.py + cas_forecast.py). Purely additive
-- presentation/analysis tables over the same raw_candles/option_chain_*
-- history everything else reads -- never a replacement for the 1-minute
-- Feature Store grain. Lazy-loaded per day (not eagerly joined into the
-- hot mti_cas_daily_transitions poll) -- see backend windowed-detail
-- endpoint.

CREATE TABLE IF NOT EXISTS cas_pretransition_windows (
    id BIGSERIAL PRIMARY KEY,
    symbol TEXT NOT NULL,
    session_date DATE NOT NULL,
    window_index SMALLINT NOT NULL CHECK (window_index BETWEEN 1 AND 6),
    window_label TEXT NOT NULL,
    open DOUBLE PRECISION, close DOUBLE PRECISION, high DOUBLE PRECISION, low DOUBLE PRECISION,
    net_point_change DOUBLE PRECISION, pct_change DOUBLE PRECISION,
    volume DOUBLE PRECISION NOT NULL,
    rvol_pct DOUBLE PRECISION, volume_acceleration_ratio DOUBLE PRECISION,
    buy_volume_estimate DOUBLE PRECISION, sell_volume_estimate DOUBLE PRECISION,
    dominance_ratio DOUBLE PRECISION NOT NULL, dominant_side TEXT NOT NULL,
    vwap_at_window_end DOUBLE PRECISION, price_distance_from_vwap DOUBLE PRECISION,
    price_distance_from_vwap_pct DOUBLE PRECISION, vwap_slope DOUBLE PRECISION,
    poc_at_window_end DOUBLE PRECISION, poc_change_during_window DOUBLE PRECISION, poc_slope DOUBLE PRECISION,
    vah DOUBLE PRECISION, val DOUBLE PRECISION,
    pcr DOUBLE PRECISION, pcr_change DOUBLE PRECISION,
    call_oi_change DOUBLE PRECISION, put_oi_change DOUBLE PRECISION,
    iv_change DOUBLE PRECISION, option_pressure_score DOUBLE PRECISION,
    market_regime TEXT, institutional_bias_label TEXT, institutional_bias_score SMALLINT,
    news_risk_score SMALLINT,
    data_quality_flag TEXT,
    computed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (symbol, session_date, window_index)
);
CREATE INDEX IF NOT EXISTS idx_cas_pretransition_windows_symbol_date ON cas_pretransition_windows (symbol, session_date DESC);

-- minute_offset 0-15 are the native 1-min rows (15:00-15:15 inclusive);
-- 16 is the single 15:30 closing-print checkpoint (is_closing_snapshot
-- true) -- see market_transition/cas_windows.py::CLOSING_SNAPSHOT_TIME.
CREATE TABLE IF NOT EXISTS cas_post_transition_minutes (
    id BIGSERIAL PRIMARY KEY,
    symbol TEXT NOT NULL,
    session_date DATE NOT NULL,
    minute_offset SMALLINT NOT NULL CHECK (minute_offset BETWEEN 0 AND 16),
    minute_time TEXT NOT NULL,
    close DOUBLE PRECISION NOT NULL, price_change DOUBLE PRECISION NOT NULL,
    volume DOUBLE PRECISION NOT NULL, rvol_pct DOUBLE PRECISION,
    dominance_ratio DOUBLE PRECISION NOT NULL, dominant_side TEXT NOT NULL,
    poc_change DOUBLE PRECISION, vwap_change DOUBLE PRECISION,
    pcr_change DOUBLE PRECISION, call_oi_change DOUBLE PRECISION, put_oi_change DOUBLE PRECISION, iv_change DOUBLE PRECISION,
    option_pressure_score DOUBLE PRECISION,
    range_expansion DOUBLE PRECISION NOT NULL,
    transition_shock_score DOUBLE PRECISION NOT NULL,
    is_closing_snapshot BOOLEAN NOT NULL DEFAULT false,
    data_quality_flag TEXT,
    computed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (symbol, session_date, minute_offset)
);
CREATE INDEX IF NOT EXISTS idx_cas_post_transition_minutes_symbol_date ON cas_post_transition_minutes (symbol, session_date DESC);

-- One row per (symbol, session_date, checkpoint) -- 7 rows/day, see
-- market_transition/cas_forecast.py. FORECAST information only; never
-- joined against the actual outcome in this table -- the UI/service layer
-- fetches mti_cas_daily_transitions separately to compare.
CREATE TABLE IF NOT EXISTS cas_transition_forecasts (
    id BIGSERIAL PRIMARY KEY,
    symbol TEXT NOT NULL,
    session_date DATE NOT NULL,
    checkpoint_time TEXT NOT NULL,
    probability_no_material_transition DOUBLE PRECISION NOT NULL,
    probability_large_up DOUBLE PRECISION NOT NULL,
    probability_large_down DOUBLE PRECISION NOT NULL,
    probability_reversal DOUBLE PRECISION NOT NULL,
    probability_continuation DOUBLE PRECISION NOT NULL,
    n_analogs INTEGER NOT NULL,
    confidence_label TEXT NOT NULL,
    top_contributing_factors JSONB,
    historical_similarity_score DOUBLE PRECISION NOT NULL,
    -- Phase 9C (spec Parts 1, 9-11): the unified UP/DOWN/NO-MATERIAL-MOVE
    -- read, layered on top of the existing 7-checkpoint forecast row
    -- rather than a parallel table -- see market_transition/verdict.py.
    probability_up DOUBLE PRECISION,
    probability_down DOUBLE PRECISION,
    expected_move_low DOUBLE PRECISION,
    expected_move_high DOUBLE PRECISION,
    expected_move_pct DOUBLE PRECISION,
    expected_move_percentile DOUBLE PRECISION,
    transition_risk_tier TEXT,
    verdict TEXT,
    primary_driver TEXT,
    secondary_driver TEXT,
    tertiary_driver TEXT,
    contradictory_factors JSONB,
    option_bias TEXT,
    computed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (symbol, session_date, checkpoint_time)
);
CREATE INDEX IF NOT EXISTS idx_cas_transition_forecasts_symbol_date ON cas_transition_forecasts (symbol, session_date DESC);

-- Historical cohorts + pre-3pm warning-indicator statistics (Phase 7C, see
-- market_transition/cas_cohorts.py). Cohort-vs-rest comparison: for each
-- of 7 named cohorts (derived from Phase 7A's transition_type x
-- magnitude_tier), how did that cohort's pre-3pm (14:55-14:59) state
-- differ from the rest of the sample. Complementary to, not a
-- replacement for, mti_cas_factor_correlations' single-model regression.
CREATE TABLE IF NOT EXISTS mti_cas_cohort_analysis (
    id BIGSERIAL PRIMARY KEY,
    symbol TEXT NOT NULL,
    cohort TEXT NOT NULL CHECK (cohort IN (
        'FLAT_LARGE_UP', 'FLAT_LARGE_DOWN', 'UP_REVERSAL_DOWN', 'DOWN_REVERSAL_UP',
        'UP_CONTINUATION', 'DOWN_CONTINUATION', 'FLAT_NO_MATERIAL_MOVE'
    )),
    feature_name TEXT NOT NULL,
    n INTEGER NOT NULL,
    median DOUBLE PRECISION,
    mean DOUBLE PRECISION,
    percentile_within_full_sample DOUBLE PRECISION,
    effect_size DOUBLE PRECISION,
    statistic DOUBLE PRECISION,
    p_value DOUBLE PRECISION,
    confidence_label TEXT NOT NULL,
    direction_note TEXT,
    computed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (symbol, cohort, feature_name)
);
CREATE INDEX IF NOT EXISTS idx_mti_cas_cohort_analysis_symbol ON mti_cas_cohort_analysis (symbol);

-- Categorical companion to mti_cas_cohort_analysis above -- kept as a
-- separate table since its row shape (category-count dicts) is genuinely
-- different from the numeric feature-stat rows, not a variant of the same
-- grain (mirrors mti_factor_correlations vs. mti_daily_transitions).
CREATE TABLE IF NOT EXISTS mti_cas_cohort_categorical (
    id BIGSERIAL PRIMARY KEY,
    symbol TEXT NOT NULL,
    cohort TEXT NOT NULL CHECK (cohort IN (
        'FLAT_LARGE_UP', 'FLAT_LARGE_DOWN', 'UP_REVERSAL_DOWN', 'DOWN_REVERSAL_UP',
        'UP_CONTINUATION', 'DOWN_CONTINUATION', 'FLAT_NO_MATERIAL_MOVE'
    )),
    feature_name TEXT NOT NULL,
    n INTEGER NOT NULL,
    category_counts JSONB,
    full_sample_category_counts JSONB,
    computed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (symbol, cohort, feature_name)
);
CREATE INDEX IF NOT EXISTS idx_mti_cas_cohort_categorical_symbol ON mti_cas_cohort_categorical (symbol);

-- Phase 9A: Option Chain Snapshot (derived features) + Detail (per-strike
-- raw fields), see option_chain/snapshot_features.py. Derived at the 8
-- fixed daily checkpoint times entirely from option_chain_raw (already
-- captured every live tick) -- no new Dhan API calls, just a query-time
-- derivation. Keyed by checkpoint_label (not raw timestamp) so the fixed
-- 8-checkpoint grain stays stable regardless of exactly which minute's
-- option_chain_raw row backed it; source_raw_fetched_at preserves exact
-- reproducibility back to that row.
CREATE TABLE IF NOT EXISTS option_chain_snapshot (
    id BIGSERIAL PRIMARY KEY,
    symbol TEXT NOT NULL,
    session_date DATE NOT NULL,
    checkpoint_label TEXT NOT NULL,  -- "09:20","11:00","13:00","14:00","14:30","15:00","15:15","15:30"
    snapshot_timestamp TIMESTAMPTZ NOT NULL,
    expiry DATE NOT NULL,
    expiry_type TEXT,
    spot DOUBLE PRECISION NOT NULL,
    atm_strike DOUBLE PRECISION NOT NULL,
    pcr_oi DOUBLE PRECISION,
    pcr_volume DOUBLE PRECISION,
    pcr_change DOUBLE PRECISION,
    call_oi_concentration DOUBLE PRECISION,
    put_oi_concentration DOUBLE PRECISION,
    call_oi_buildup DOUBLE PRECISION,
    put_oi_buildup DOUBLE PRECISION,
    call_unwinding DOUBLE PRECISION,
    put_unwinding DOUBLE PRECISION,
    call_put_volume_imbalance DOUBLE PRECISION,
    atm_iv_call DOUBLE PRECISION,
    atm_iv_put DOUBLE PRECISION,
    iv_skew DOUBLE PRECISION,
    atm_iv_change DOUBLE PRECISION,
    atm_straddle_value DOUBLE PRECISION,
    atm_straddle_change DOUBLE PRECISION,
    max_call_oi_strike DOUBLE PRECISION,
    max_put_oi_strike DOUBLE PRECISION,
    spot_distance_from_max_call_oi DOUBLE PRECISION,
    spot_distance_from_max_put_oi DOUBLE PRECISION,
    oi_migration_note TEXT,
    position_classification TEXT NOT NULL,
    data_quality TEXT NOT NULL CHECK (data_quality IN ('GOOD', 'DEGRADED', 'INSUFFICIENT')),
    source_raw_fetched_at TIMESTAMPTZ,
    computed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (symbol, session_date, checkpoint_label)
);
CREATE INDEX IF NOT EXISTS idx_option_chain_snapshot_symbol_date ON option_chain_snapshot (symbol, session_date DESC);

CREATE TABLE IF NOT EXISTS option_chain_snapshot_detail (
    id BIGSERIAL PRIMARY KEY,
    symbol TEXT NOT NULL,
    session_date DATE NOT NULL,
    checkpoint_label TEXT NOT NULL,
    strike DOUBLE PRECISION NOT NULL,
    leg TEXT NOT NULL CHECK (leg IN ('CE', 'PE')),
    ltp DOUBLE PRECISION,
    volume DOUBLE PRECISION,
    oi DOUBLE PRECISION,
    oi_change DOUBLE PRECISION,
    iv DOUBLE PRECISION,
    bid DOUBLE PRECISION,
    ask DOUBLE PRECISION,
    bid_qty DOUBLE PRECISION,
    ask_qty DOUBLE PRECISION,
    delta DOUBLE PRECISION,
    gamma DOUBLE PRECISION,
    theta DOUBLE PRECISION,
    vega DOUBLE PRECISION,
    UNIQUE (symbol, session_date, checkpoint_label, strike, leg)
);
CREATE INDEX IF NOT EXISTS idx_option_chain_snapshot_detail_lookup ON option_chain_snapshot_detail (symbol, session_date, checkpoint_label);

-- Phase 9D (spec Parts 13-14, 16D/16E): actual outcome + forecast
-- evaluation, kept as separate, immutable tables -- never mixed with the
-- (mutable-until-frozen) forecast row in cas_transition_forecasts, per
-- the spec's explicit "do not mix forecast and actual data in the same
-- mutable record". See market_transition/cas_windows.py::
-- compute_actual_outcome_checkpoints.
CREATE TABLE IF NOT EXISTS transition_actual_outcome (
    id BIGSERIAL PRIMARY KEY,
    symbol TEXT NOT NULL,
    session_date DATE NOT NULL,
    horizon_minutes SMALLINT NOT NULL CHECK (horizon_minutes IN (1, 5, 10, 15)),
    direction TEXT NOT NULL,
    point_move DOUBLE PRECISION NOT NULL,
    pct_move DOUBLE PRECISION,
    vol_normalized_move DOUBLE PRECISION,
    mfe DOUBLE PRECISION NOT NULL,
    mae DOUBLE PRECISION NOT NULL,
    volume_expansion DOUBLE PRECISION,
    shock_score DOUBLE PRECISION NOT NULL,
    computed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (symbol, session_date, horizon_minutes)
);
CREATE INDEX IF NOT EXISTS idx_transition_actual_outcome_symbol_date ON transition_actual_outcome (symbol, session_date DESC);

-- Computed only once both the frozen 14:59 forecast AND the 15-min actual
-- outcome exist for a day -- references, never edits, either. Aggregate
-- accuracy/calibration/FP-FN rates across many days are a query-time
-- computation over this table (e.g. AVG(brier_score)), not a stored
-- mutable running aggregate.
CREATE TABLE IF NOT EXISTS forecast_evaluation (
    id BIGSERIAL PRIMARY KEY,
    symbol TEXT NOT NULL,
    session_date DATE NOT NULL,
    forecast_verdict TEXT NOT NULL,
    actual_direction_15min TEXT NOT NULL,
    directionally_correct BOOLEAN,
    brier_score DOUBLE PRECISION,
    predicted_probability_of_actual DOUBLE PRECISION,
    is_false_positive BOOLEAN,
    is_false_negative BOOLEAN,
    computed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (symbol, session_date)
);
CREATE INDEX IF NOT EXISTS idx_forecast_evaluation_symbol_date ON forecast_evaluation (symbol, session_date DESC);
