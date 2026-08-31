from datetime import date, datetime

from sqlalchemy import BigInteger, Boolean, CheckConstraint, Date, DateTime, Double, Integer, SmallInteger, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class MtiDailyTransition(Base):
    __tablename__ = "mti_daily_transitions"
    __table_args__ = (
        UniqueConstraint("symbol", "session_date", name="mti_daily_transitions_symbol_session_date_key"),
        CheckConstraint("outcome IN ('continuation', 'reversal', 'neutral')", name="mti_daily_transitions_outcome_check"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    symbol: Mapped[str] = mapped_column(Text, nullable=False)
    session_date: Mapped[date] = mapped_column(Date, nullable=False)

    poc_migration_1400_1459: Mapped[float | None] = mapped_column(Double, nullable=True)
    vwap_distance_1459: Mapped[float | None] = mapped_column(Double, nullable=True)
    vwap_distance_1459_pct: Mapped[float | None] = mapped_column(Double, nullable=True)
    volume_slope_1400_1459: Mapped[float | None] = mapped_column(Double, nullable=True)
    realized_range_1400_1459: Mapped[float | None] = mapped_column(Double, nullable=True)
    profile_shape_1459: Mapped[str | None] = mapped_column(Text, nullable=True)
    rotation_label_1459: Mapped[str | None] = mapped_column(Text, nullable=True)
    market_regime_1459: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_inside_initial_balance_1459: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    day_of_week: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    expiry_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    prior_day_profile_shape: Mapped[str | None] = mapped_column(Text, nullable=True)
    prior_day_close_vs_poc: Mapped[str | None] = mapped_column(Text, nullable=True)

    close_1459: Mapped[float] = mapped_column(Double, nullable=False)
    close_1501: Mapped[float] = mapped_column(Double, nullable=False)
    market_close: Mapped[float] = mapped_column(Double, nullable=False)
    transition_move: Mapped[float] = mapped_column(Double, nullable=False)
    transition_direction: Mapped[str] = mapped_column(Text, nullable=False)
    post_transition_move: Mapped[float] = mapped_column(Double, nullable=False)
    outcome: Mapped[str] = mapped_column(Text, nullable=False)
    outcome_magnitude: Mapped[float] = mapped_column(Double, nullable=False)

    transition_risk_score: Mapped[float | None] = mapped_column(Double, nullable=True)
    probability_continuation: Mapped[float | None] = mapped_column(Double, nullable=True)
    probability_reversal: Mapped[float | None] = mapped_column(Double, nullable=True)
    expected_volatility: Mapped[float | None] = mapped_column(Double, nullable=True)
    expected_direction: Mapped[str | None] = mapped_column(Text, nullable=True)
    historical_similarity_score: Mapped[float | None] = mapped_column(Double, nullable=True)
    top_contributing_factors: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    statistical_confidence: Mapped[str | None] = mapped_column(Text, nullable=True)
    explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    computed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class MtiFactorCorrelation(Base):
    __tablename__ = "mti_factor_correlations"
    __table_args__ = (
        UniqueConstraint("symbol", "factor_name", "target", name="mti_factor_correlations_symbol_factor_name_target_key"),
        CheckConstraint("factor_type IN ('continuous', 'categorical')", name="mti_factor_correlations_factor_type_check"),
        CheckConstraint("target IN ('reversal', 'magnitude')", name="mti_factor_correlations_target_check"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    symbol: Mapped[str] = mapped_column(Text, nullable=False)
    factor_name: Mapped[str] = mapped_column(Text, nullable=False)
    factor_type: Mapped[str] = mapped_column(Text, nullable=False)
    target: Mapped[str] = mapped_column(Text, nullable=False)
    n_days: Mapped[int] = mapped_column(Integer, nullable=False)
    statistic: Mapped[float | None] = mapped_column(Double, nullable=True)
    p_value: Mapped[float | None] = mapped_column(Double, nullable=True)
    confidence_label: Mapped[str] = mapped_column(Text, nullable=False)
    direction_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    category_breakdown: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CasFactorCorrelation(Base):
    """CAS-adjusted factor correlation study -- see
    market_transition/cas_statistics.py. Same shape as MtiFactorCorrelation
    above, entirely separate table/study."""

    __tablename__ = "mti_cas_factor_correlations"
    __table_args__ = (
        UniqueConstraint("symbol", "factor_name", "target", name="mti_cas_factor_correlations_symbol_factor_name_target_key"),
        CheckConstraint("factor_type IN ('continuous', 'categorical')", name="mti_cas_factor_correlations_factor_type_check"),
        CheckConstraint("target IN ('reversal', 'magnitude')", name="mti_cas_factor_correlations_target_check"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    symbol: Mapped[str] = mapped_column(Text, nullable=False)
    factor_name: Mapped[str] = mapped_column(Text, nullable=False)
    factor_type: Mapped[str] = mapped_column(Text, nullable=False)
    target: Mapped[str] = mapped_column(Text, nullable=False)
    n_days: Mapped[int] = mapped_column(Integer, nullable=False)
    statistic: Mapped[float | None] = mapped_column(Double, nullable=True)
    p_value: Mapped[float | None] = mapped_column(Double, nullable=True)
    confidence_label: Mapped[str] = mapped_column(Text, nullable=False)
    direction_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    category_breakdown: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CasDailyTransition(Base):
    """CAS Intelligence -- see market_transition/cas_transition.py. Entirely
    additive/parallel to MtiDailyTransition above, not a replacement."""

    __tablename__ = "mti_cas_daily_transitions"
    __table_args__ = (
        UniqueConstraint("symbol", "session_date", name="mti_cas_daily_transitions_symbol_session_date_key"),
        CheckConstraint("conclusion IN ('continuation', 'reversal', 'neutral')", name="mti_cas_daily_transitions_conclusion_check"),
        CheckConstraint(
            "transition_type IN ('CONTINUATION_UP', 'CONTINUATION_DOWN', 'REVERSAL_UP', 'REVERSAL_DOWN', "
            "'POST_WINDOW_INITIATION_UP', 'POST_WINDOW_INITIATION_DOWN', 'NO_MATERIAL_TRANSITION')",
            name="mti_cas_daily_transitions_transition_type_check",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    symbol: Mapped[str] = mapped_column(Text, nullable=False)
    session_date: Mapped[date] = mapped_column(Date, nullable=False)

    close_1431: Mapped[float | None] = mapped_column(Double, nullable=True)
    close_1459: Mapped[float | None] = mapped_column(Double, nullable=True)
    close_1539: Mapped[float | None] = mapped_column(Double, nullable=True)
    pre_direction: Mapped[str | None] = mapped_column(Text, nullable=True)
    post_direction: Mapped[str | None] = mapped_column(Text, nullable=True)
    conclusion: Mapped[str] = mapped_column(Text, nullable=False)
    outcome_magnitude: Mapped[float | None] = mapped_column(Double, nullable=True)

    pre_window_volume: Mapped[float | None] = mapped_column(Double, nullable=True)
    post_window_pre_auction_volume: Mapped[float | None] = mapped_column(Double, nullable=True)
    volume_ratio: Mapped[float | None] = mapped_column(Double, nullable=True)
    pre_window_points_move: Mapped[float | None] = mapped_column(Double, nullable=True)
    post_window_points_move: Mapped[float | None] = mapped_column(Double, nullable=True)

    pcr_1459: Mapped[float | None] = mapped_column(Double, nullable=True)
    institutional_bias_label_1459: Mapped[str | None] = mapped_column(Text, nullable=True)
    institutional_bias_score_1459: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)

    expiry_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    day_of_week: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    old_methodology_outcome: Mapped[str | None] = mapped_column(Text, nullable=True)
    old_methodology_outcome_magnitude: Mapped[float | None] = mapped_column(Double, nullable=True)
    data_quality_flag: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Independent-dimension reclassification (Phase 7A) -- additive, see
    # market_transition/cas_transition.py::classify_transition_type/
    # classify_transition_magnitude. `conclusion` above is untouched.
    transition_type: Mapped[str] = mapped_column(Text, nullable=False)
    magnitude_pct_return: Mapped[float | None] = mapped_column(Double, nullable=True)
    magnitude_atr_normalized: Mapped[float | None] = mapped_column(Double, nullable=True)
    magnitude_tier: Mapped[str | None] = mapped_column(Text, nullable=True)

    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CasPretransitionWindow(Base):
    """Phase 7B: one of 6 five-minute pre-3pm decision windows -- see
    market_transition/cas_windows.py. FORECAST information -- never
    contains anything from 15:00 onward."""

    __tablename__ = "cas_pretransition_windows"
    __table_args__ = (
        UniqueConstraint("symbol", "session_date", "window_index", name="cas_pretransition_windows_symbol_session_date_window_index_key"),
        CheckConstraint("window_index BETWEEN 1 AND 6", name="cas_pretransition_windows_window_index_check"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    symbol: Mapped[str] = mapped_column(Text, nullable=False)
    session_date: Mapped[date] = mapped_column(Date, nullable=False)
    window_index: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    window_label: Mapped[str] = mapped_column(Text, nullable=False)

    open: Mapped[float | None] = mapped_column(Double, nullable=True)
    close: Mapped[float | None] = mapped_column(Double, nullable=True)
    high: Mapped[float | None] = mapped_column(Double, nullable=True)
    low: Mapped[float | None] = mapped_column(Double, nullable=True)
    net_point_change: Mapped[float | None] = mapped_column(Double, nullable=True)
    pct_change: Mapped[float | None] = mapped_column(Double, nullable=True)

    volume: Mapped[float] = mapped_column(Double, nullable=False)
    rvol_pct: Mapped[float | None] = mapped_column(Double, nullable=True)
    volume_acceleration_ratio: Mapped[float | None] = mapped_column(Double, nullable=True)
    buy_volume_estimate: Mapped[float | None] = mapped_column(Double, nullable=True)
    sell_volume_estimate: Mapped[float | None] = mapped_column(Double, nullable=True)
    dominance_ratio: Mapped[float] = mapped_column(Double, nullable=False)
    dominant_side: Mapped[str] = mapped_column(Text, nullable=False)

    vwap_at_window_end: Mapped[float | None] = mapped_column(Double, nullable=True)
    price_distance_from_vwap: Mapped[float | None] = mapped_column(Double, nullable=True)
    price_distance_from_vwap_pct: Mapped[float | None] = mapped_column(Double, nullable=True)
    vwap_slope: Mapped[float | None] = mapped_column(Double, nullable=True)
    poc_at_window_end: Mapped[float | None] = mapped_column(Double, nullable=True)
    poc_change_during_window: Mapped[float | None] = mapped_column(Double, nullable=True)
    poc_slope: Mapped[float | None] = mapped_column(Double, nullable=True)
    vah: Mapped[float | None] = mapped_column(Double, nullable=True)
    val: Mapped[float | None] = mapped_column(Double, nullable=True)

    pcr: Mapped[float | None] = mapped_column(Double, nullable=True)
    pcr_change: Mapped[float | None] = mapped_column(Double, nullable=True)
    call_oi_change: Mapped[float | None] = mapped_column(Double, nullable=True)
    put_oi_change: Mapped[float | None] = mapped_column(Double, nullable=True)
    iv_change: Mapped[float | None] = mapped_column(Double, nullable=True)
    option_pressure_score: Mapped[float | None] = mapped_column(Double, nullable=True)

    market_regime: Mapped[str | None] = mapped_column(Text, nullable=True)
    institutional_bias_label: Mapped[str | None] = mapped_column(Text, nullable=True)
    institutional_bias_score: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    news_risk_score: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    data_quality_flag: Mapped[str | None] = mapped_column(Text, nullable=True)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CasPostTransitionMinute(Base):
    """Phase 7B: 16 native 1-minute post-3pm rows (15:00-15:15 inclusive)
    plus a single 17th row at 15:30 (minute_offset 16, is_closing_snapshot
    true) -- the NSE Closing Auction Session's actual settlement print,
    added because 15:16-15:35 was otherwise untracked. See
    market_transition/cas_windows.py::CLOSING_SNAPSHOT_TIME. ACTUAL
    OUTCOME -- never joined against the forecast tables at this layer."""

    __tablename__ = "cas_post_transition_minutes"
    __table_args__ = (
        UniqueConstraint("symbol", "session_date", "minute_offset", name="cas_post_transition_minutes_symbol_session_date_minute_offset_key"),
        CheckConstraint("minute_offset BETWEEN 0 AND 16", name="cas_post_transition_minutes_minute_offset_check"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    symbol: Mapped[str] = mapped_column(Text, nullable=False)
    session_date: Mapped[date] = mapped_column(Date, nullable=False)
    minute_offset: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    minute_time: Mapped[str] = mapped_column(Text, nullable=False)

    close: Mapped[float] = mapped_column(Double, nullable=False)
    price_change: Mapped[float] = mapped_column(Double, nullable=False)
    volume: Mapped[float] = mapped_column(Double, nullable=False)
    rvol_pct: Mapped[float | None] = mapped_column(Double, nullable=True)
    dominance_ratio: Mapped[float] = mapped_column(Double, nullable=False)
    dominant_side: Mapped[str] = mapped_column(Text, nullable=False)
    poc_change: Mapped[float | None] = mapped_column(Double, nullable=True)
    vwap_change: Mapped[float | None] = mapped_column(Double, nullable=True)
    pcr_change: Mapped[float | None] = mapped_column(Double, nullable=True)
    call_oi_change: Mapped[float | None] = mapped_column(Double, nullable=True)
    put_oi_change: Mapped[float | None] = mapped_column(Double, nullable=True)
    iv_change: Mapped[float | None] = mapped_column(Double, nullable=True)
    option_pressure_score: Mapped[float | None] = mapped_column(Double, nullable=True)
    range_expansion: Mapped[float] = mapped_column(Double, nullable=False)
    transition_shock_score: Mapped[float] = mapped_column(Double, nullable=False)
    is_closing_snapshot: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    data_quality_flag: Mapped[str | None] = mapped_column(Text, nullable=True)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CasTransitionForecast(Base):
    """Phase 7B: one of 7 leakage-safe forecast checkpoints
    (14:30/35/40/45/50/55/59) -- see market_transition/cas_forecast.py.
    FORECAST information only -- built strictly from data available at
    checkpoint_time, never the actual outcome."""

    __tablename__ = "cas_transition_forecasts"
    __table_args__ = (
        UniqueConstraint("symbol", "session_date", "checkpoint_time", name="cas_transition_forecasts_symbol_session_date_checkpoint_time_key"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    symbol: Mapped[str] = mapped_column(Text, nullable=False)
    session_date: Mapped[date] = mapped_column(Date, nullable=False)
    checkpoint_time: Mapped[str] = mapped_column(Text, nullable=False)

    probability_no_material_transition: Mapped[float] = mapped_column(Double, nullable=False)
    probability_large_up: Mapped[float] = mapped_column(Double, nullable=False)
    probability_large_down: Mapped[float] = mapped_column(Double, nullable=False)
    probability_reversal: Mapped[float] = mapped_column(Double, nullable=False)
    probability_continuation: Mapped[float] = mapped_column(Double, nullable=False)
    n_analogs: Mapped[int] = mapped_column(Integer, nullable=False)
    confidence_label: Mapped[str] = mapped_column(Text, nullable=False)
    top_contributing_factors: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    historical_similarity_score: Mapped[float] = mapped_column(Double, nullable=False)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


_COHORT_CHECK = (
    "cohort IN ('FLAT_LARGE_UP', 'FLAT_LARGE_DOWN', 'UP_REVERSAL_DOWN', 'DOWN_REVERSAL_UP', "
    "'UP_CONTINUATION', 'DOWN_CONTINUATION', 'FLAT_NO_MATERIAL_MOVE')"
)


class CasCohortFeatureStat(Base):
    """Phase 7C: cohort-vs-rest comparison of one pre-3pm feature for one
    of the 7 named cohorts -- see market_transition/cas_cohorts.py.
    Complementary to CasFactorCorrelation's single-model regression, not a
    replacement."""

    __tablename__ = "mti_cas_cohort_analysis"
    __table_args__ = (
        UniqueConstraint("symbol", "cohort", "feature_name", name="mti_cas_cohort_analysis_symbol_cohort_feature_name_key"),
        CheckConstraint(_COHORT_CHECK, name="mti_cas_cohort_analysis_cohort_check"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    symbol: Mapped[str] = mapped_column(Text, nullable=False)
    cohort: Mapped[str] = mapped_column(Text, nullable=False)
    feature_name: Mapped[str] = mapped_column(Text, nullable=False)
    n: Mapped[int] = mapped_column(Integer, nullable=False)
    median: Mapped[float | None] = mapped_column(Double, nullable=True)
    mean: Mapped[float | None] = mapped_column(Double, nullable=True)
    percentile_within_full_sample: Mapped[float | None] = mapped_column(Double, nullable=True)
    effect_size: Mapped[float | None] = mapped_column(Double, nullable=True)
    statistic: Mapped[float | None] = mapped_column(Double, nullable=True)
    p_value: Mapped[float | None] = mapped_column(Double, nullable=True)
    confidence_label: Mapped[str] = mapped_column(Text, nullable=False)
    direction_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CasCohortCategorical(Base):
    """Phase 7C: categorical companion to CasCohortFeatureStat -- category
    counts within the cohort vs. the full sample, descriptive only (no
    formal significance test for multi-category small-N comparisons in
    this phase)."""

    __tablename__ = "mti_cas_cohort_categorical"
    __table_args__ = (
        UniqueConstraint("symbol", "cohort", "feature_name", name="mti_cas_cohort_categorical_symbol_cohort_feature_name_key"),
        CheckConstraint(_COHORT_CHECK, name="mti_cas_cohort_categorical_cohort_check"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    symbol: Mapped[str] = mapped_column(Text, nullable=False)
    cohort: Mapped[str] = mapped_column(Text, nullable=False)
    feature_name: Mapped[str] = mapped_column(Text, nullable=False)
    n: Mapped[int] = mapped_column(Integer, nullable=False)
    category_counts: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    full_sample_category_counts: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
