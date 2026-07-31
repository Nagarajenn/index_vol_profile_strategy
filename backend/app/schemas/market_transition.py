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


class MtiResearchResponseDTO(BaseModel):
    symbol: str
    total_days_analyzed: int
    correlations: list[MtiFactorCorrelationDTO]
    daily_results: list[MtiDailyResultDTO]
