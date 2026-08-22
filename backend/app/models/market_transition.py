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
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
