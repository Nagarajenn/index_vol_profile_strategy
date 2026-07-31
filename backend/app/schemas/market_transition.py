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
