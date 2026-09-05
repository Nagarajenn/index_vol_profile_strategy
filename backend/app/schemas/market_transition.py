"""DTOs for the Market Transition Intelligence research dashboard. Served
only by GET /api/v1/market-transition/{symbol}/research -- a research view
over market_transition/, entirely independent of the trading decision
engine and the confidence_score/trend_classifier tables.
"""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel

ConfidenceLabelLiteral = Literal["Strong", "Moderate", "Weak", "Not significant", "Insufficient data"]


class ContributingFactorDTO(BaseModel):
    factor_name: str
    today_value: str
    note: str
    contribution: float


class MtiFactorCorrelationDTO(BaseModel):
    factor_name: str
    factor_type: Literal["continuous", "categorical"]
    target: Literal["reversal", "magnitude"]
    n_days: int
    statistic: float | None
    p_value: float | None
    confidence_label: ConfidenceLabelLiteral
    direction_note: str | None
    category_breakdown: dict | None


class MtiDailyResultDTO(BaseModel):
    session_date: date
    profile_shape_1459: str | None
    market_regime_1459: str | None
    expiry_type: str | None
    transition_direction: Literal["up", "down", "flat"]
    transition_move: float
    post_transition_move: float
    outcome: Literal["continuation", "reversal", "neutral"]
    outcome_magnitude: float
    transition_risk_score: float | None
    probability_continuation: float | None
    probability_reversal: float | None
    expected_volatility: float | None
    expected_direction: str | None
    historical_similarity_score: float | None
    top_contributing_factors: list[ContributingFactorDTO]
    statistical_confidence: ConfidenceLabelLiteral | None
    explanation: str | None
    computed_at: datetime | None
    # Forecast-vs-actual: `predicted_outcome` is the pre-3pm forecast's lean
    # (whichever of probability_reversal/probability_continuation was
    # higher), derived at read time -- not stored, since it's fully implied
    # by the two probability columns already on this row. None when the
    # forecast was a dead-even split (i.e. score_day() had insufficient
    # analogs). `forecast_correct` compares that lean against the actual
    # `outcome`; None when there's no forecast to grade, or when the actual
    # outcome was "neutral" (no significant move -- not a fair test of a
    # reversal-vs-continuation call).
    predicted_outcome: Literal["reversal", "continuation"] | None
    forecast_correct: bool | None


class MtiResearchResponseDTO(BaseModel):
    symbol: str
    total_days_analyzed: int
    correlations: list[MtiFactorCorrelationDTO]
    daily_results: list[MtiDailyResultDTO]
    # Aggregate forecast accuracy across all graded days (see MtiDailyResultDTO
    # docstring for what makes a day "evaluable"). forecast_accuracy_pct is
    # None when forecast_evaluable_days == 0 -- avoids a misleading 0/0 rate.
    forecast_evaluable_days: int
    forecast_hit_count: int
    forecast_accuracy_pct: float | None


# ---------------------------------------------------------------------------
# Live Market Transition Advisor -- served by
# GET /api/v1/market-transition/{symbol}/live-advisor. A read-time advisory
# comparing today's in-progress session against the historical MTI database
# above; never a trading signal (risk_level is capped to the fixed
# vocabulary below), entirely independent of the trading decision engine.
# ---------------------------------------------------------------------------
TransitionStageLiteral = Literal[
    "Not Yet Active", "Pre-Transition Monitoring", "Transition Window", "Post-Transition Follow-Through", "Session Complete"
]
TransitionRiskLevelLiteral = Literal["Observe", "Low", "Medium", "High", "Very High"]


class MostSimilarDayDTO(BaseModel):
    session_date: date
    distance: float
    similarity: float
    outcome: Literal["continuation", "reversal", "neutral"]
    transition_direction: Literal["up", "down", "flat"]


class TransitionTimingEstimateDTO(BaseModel):
    earliest: str | None  # "HH:MM AM/PM", pre-formatted -- there's no clean JSON `time` wire format worth the client-side parsing
    latest: str | None
    n_analogs_with_onset: int
    note: str


class LiveAdvisoryDTO(BaseModel):
    symbol: str
    session_date: date
    as_of: datetime
    stage: TransitionStageLiteral
    is_active: bool
    historical_similarity_score: float
    most_similar_days: list[MostSimilarDayDTO]
    expected_direction: Literal["up", "down", "flat"]
    probability_continuation: float
    probability_reversal: float
    expected_volatility: float
    expected_timing: TransitionTimingEstimateDTO | None
    estimated_move: float
    risk_level: TransitionRiskLevelLiteral
    statistical_confidence: ConfidenceLabelLiteral
    top_contributing_factors: list[ContributingFactorDTO]
    institutional_bias_label: str | None
    news_risk_score: int | None
    news_sentiment: Literal["Bullish", "Bearish", "Neutral"] | None
    explanation: str


# ---------------------------------------------------------------------------
# CAS Intelligence -- served by GET /api/v1/market-transition/{symbol}/
# cas-intelligence. Additive, parallel re-analysis of the 3pm transition
# under NSE's post-2026-08-03 Closing Auction Session framework (see
# market_transition/cas_transition.py) -- does not replace the research/
# live-advisor endpoints above, which remain the source of truth.
# ---------------------------------------------------------------------------
class CasDailyResultDTO(BaseModel):
    session_date: date
    close_1431: float | None
    close_1459: float | None
    close_1539: float | None
    pre_direction: Literal["up", "down", "flat"] | None
    post_direction: Literal["up", "down", "flat"] | None
    conclusion: Literal["continuation", "reversal", "neutral"]
    outcome_magnitude: float | None
    pre_window_volume: float | None
    post_window_pre_auction_volume: float | None
    volume_ratio: float | None
    pre_window_points_move: float | None
    post_window_points_move: float | None
    pcr_1459: float | None
    institutional_bias_label_1459: str | None
    institutional_bias_score_1459: int | None
    expiry_type: str | None
    day_of_week: int | None
    old_methodology_outcome: Literal["continuation", "reversal", "neutral"] | None
    old_methodology_outcome_magnitude: float | None
    data_quality_flag: str | None
    # Independent-dimension reclassification (Phase 7A) -- additive, see
    # market_transition/cas_transition.py. `conclusion` above is untouched.
    transition_type: Literal[
        "CONTINUATION_UP", "CONTINUATION_DOWN", "REVERSAL_UP", "REVERSAL_DOWN",
        "POST_WINDOW_INITIATION_UP", "POST_WINDOW_INITIATION_DOWN", "NO_MATERIAL_TRANSITION",
    ]
    magnitude_pct_return: float | None
    magnitude_atr_normalized: float | None
    magnitude_tier: Literal["NORMAL", "MODERATE", "LARGE", "EXTREME"] | None
    computed_at: datetime


class CasIntelligenceResponseDTO(BaseModel):
    symbol: str
    total_days_analyzed: int
    # Agreement between this row's conclusion and old_methodology_outcome,
    # over days where both exist -- computed at read time (not stored), see
    # CasIntelligenceService for the exact rule.
    agreement_count: int
    agreement_pct: float | None
    daily_results: list[CasDailyResultDTO]
    # Factor-correlation study over the CAS-adjusted outcome -- see
    # market_transition/cas_statistics.py. Same MtiFactorCorrelationDTO
    # shape as the original engine's study, just a separate result set.
    correlations: list[MtiFactorCorrelationDTO]


# ---------------------------------------------------------------------------
# Phase 7B: dual-resolution pre/post-3pm transition detail -- served by
# GET /api/v1/market-transition/{symbol}/cas-intelligence/{session_date}/
# windowed-detail. Lazy-loaded per day, never eagerly joined into the DTOs
# above. Pre-transition windows are FORECAST INFORMATION; post-transition
# minutes are ACTUAL OUTCOME; forecasts are graded against the latter only
# by the caller comparing timestamps, never merged server-side.
# ---------------------------------------------------------------------------
class PreTransitionWindowDTO(BaseModel):
    window_index: int
    window_label: str
    open: float | None
    close: float | None
    high: float | None
    low: float | None
    net_point_change: float | None
    pct_change: float | None
    volume: float
    rvol_pct: float | None
    volume_acceleration_ratio: float | None
    buy_volume_estimate: float | None
    sell_volume_estimate: float | None
    dominance_ratio: float
    dominant_side: Literal["buy", "sell", "balanced"]
    vwap_at_window_end: float | None
    price_distance_from_vwap: float | None
    price_distance_from_vwap_pct: float | None
    vwap_slope: float | None
    poc_at_window_end: float | None
    poc_change_during_window: float | None
    poc_slope: float | None
    vah: float | None
    val: float | None
    pcr: float | None
    pcr_change: float | None
    call_oi_change: float | None
    put_oi_change: float | None
    iv_change: float | None
    option_pressure_score: float | None
    market_regime: str | None
    institutional_bias_label: str | None
    institutional_bias_score: int | None
    news_risk_score: int | None
    data_quality_flag: str | None


class PostTransitionMinuteDTO(BaseModel):
    minute_offset: int
    minute_time: str
    close: float
    price_change: float
    volume: float
    rvol_pct: float | None
    dominance_ratio: float
    dominant_side: Literal["buy", "sell", "balanced"]
    poc_change: float | None
    vwap_change: float | None
    pcr_change: float | None
    call_oi_change: float | None
    put_oi_change: float | None
    iv_change: float | None
    option_pressure_score: float | None
    range_expansion: float
    transition_shock_score: float
    is_closing_snapshot: bool
    data_quality_flag: str | None


class TransitionForecastDTO(BaseModel):
    checkpoint_time: str
    probability_no_material_transition: float
    probability_large_up: float
    probability_large_down: float
    probability_reversal: float
    probability_continuation: float
    n_analogs: int
    confidence_label: ConfidenceLabelLiteral
    top_contributing_factors: list[ContributingFactorDTO]
    historical_similarity_score: float
    probability_up: float | None = None
    probability_down: float | None = None
    expected_move_low: float | None = None
    expected_move_high: float | None = None
    expected_move_pct: float | None = None
    expected_move_percentile: float | None = None
    transition_risk_tier: str | None = None
    verdict: str | None = None
    primary_driver: str | None = None
    secondary_driver: str | None = None
    tertiary_driver: str | None = None
    contradictory_factors: list[str] = []
    option_bias: str | None = None


class CasWindowedDetailResponseDTO(BaseModel):
    symbol: str
    session_date: date
    pre_transition_windows: list[PreTransitionWindowDTO]
    post_transition_minutes: list[PostTransitionMinuteDTO]
    forecasts: list[TransitionForecastDTO]


# ---------------------------------------------------------------------------
# Phase 7C: historical cohorts + pre-3pm warning-indicator statistics --
# served by GET /api/v1/market-transition/{symbol}/cas-cohort-analysis.
# Cohort-vs-rest comparison, complementary to (not a replacement for) the
# correlation study above. Symbol-wide, not per-day.
# ---------------------------------------------------------------------------
CohortNameLiteral = Literal[
    "FLAT_LARGE_UP", "FLAT_LARGE_DOWN", "UP_REVERSAL_DOWN", "DOWN_REVERSAL_UP",
    "UP_CONTINUATION", "DOWN_CONTINUATION", "FLAT_NO_MATERIAL_MOVE",
]


class CohortFeatureStatDTO(BaseModel):
    feature_name: str
    n: int
    median: float | None
    mean: float | None
    percentile_within_full_sample: float | None
    effect_size: float | None
    statistic: float | None
    p_value: float | None
    confidence_label: ConfidenceLabelLiteral
    direction_note: str | None


class CohortCategoricalDTO(BaseModel):
    feature_name: str
    n: int
    category_counts: dict[str, int]
    full_sample_category_counts: dict[str, int]


class CohortResultDTO(BaseModel):
    cohort: CohortNameLiteral
    n_days: int
    features: list[CohortFeatureStatDTO]
    categorical: list[CohortCategoricalDTO]


class CasCohortAnalysisResponseDTO(BaseModel):
    symbol: str
    cohorts: list[CohortResultDTO]
