"""Pure dataclasses for the Market Transition Intelligence engine. No
DB/pipeline/network dependency -- mirrors market_intelligence/models.py's
"plain dataclasses, provider-independent" pattern.

This module is deliberately independent of analytics/confidence_score.py,
analytics/trend_classifier.py, and decision/decision_card.py: it is a
research tool over historical data, not part of the live trading-decision
path.
"""

from dataclasses import dataclass, field
from datetime import date, datetime, time
from typing import Literal

MarketRegime = Literal["Trending", "Range-Bound", "Volatile"]
ProfileShape = Literal["P", "b", "D", "B"]
RotationLabel = Literal["Trending", "Rotational"]
TransitionDirection = Literal["up", "down", "flat"]
TransitionOutcomeLabel = Literal["continuation", "reversal", "neutral"]
ExpiryType = Literal["weekly", "monthly"]
ConfidenceLabel = Literal["Strong", "Moderate", "Weak", "Not significant", "Insufficient data"]
FactorType = Literal["continuous", "categorical"]
CorrelationTarget = Literal["reversal", "magnitude"]
TransitionStage = Literal[
    "Not Yet Active", "Pre-Transition Monitoring", "Transition Window", "Post-Transition Follow-Through", "Session Complete"
]
TransitionRiskLevel = Literal["Observe", "Low", "Medium", "High", "Very High"]


@dataclass
class PreWindowFeatures:
    """Everything measured as of ~14:59, before the 3pm transition."""

    poc_migration_1400_1459: float | None
    vwap_distance_1459: float | None
    vwap_distance_1459_pct: float | None
    volume_slope_1400_1459: float | None  # relative change, 2nd half vs 1st half avg volume
    realized_range_1400_1459: float | None
    profile_shape_1459: ProfileShape | None
    rotation_label_1459: RotationLabel | None
    market_regime_1459: MarketRegime | None
    is_inside_initial_balance_1459: bool | None
    day_of_week: int  # 0=Monday .. 4=Friday
    expiry_type: ExpiryType | None
    prior_day_profile_shape: ProfileShape | None
    prior_day_close_vs_poc: Literal["above", "below", "at"] | None


@dataclass
class TransitionOutcome:
    """The 15:00-15:01 move and what happened afterward, through close."""

    close_1459: float
    close_1501: float
    market_close: float
    transition_move: float  # close_1501 - close_1459
    transition_direction: TransitionDirection
    post_transition_move: float  # market_close - close_1501
    outcome: TransitionOutcomeLabel
    outcome_magnitude: float  # abs(post_transition_move)


@dataclass
class DailyTransitionRecord:
    """One historical trading day's features + outcome -- the unit the
    statistical study and the scoring engine both operate on."""

    symbol: str
    session_date: date
    features: PreWindowFeatures
    outcome: TransitionOutcome


@dataclass
class FactorCorrelationResult:
    """Output of the statistical study for one candidate predictor factor
    against one target, across all available historical days. Each factor
    is tested against two targets: whether the transition reverses
    (binary/categorical association) and how large the post-transition move
    is (magnitude)."""

    factor_name: str
    factor_type: FactorType
    target: CorrelationTarget
    n: int
    statistic: float | None
    p_value: float | None
    confidence_label: ConfidenceLabel
    direction_note: str
    category_breakdown: dict[str, dict] | None = None  # categorical factors only


@dataclass
class ContributingFactor:
    factor_name: str
    today_value: str
    note: str
    contribution: float  # signed: positive pushes toward reversal, negative toward continuation


@dataclass
class DailyTransitionScore:
    """The per-day research output for a specific symbol/date, produced by
    scoring.py using the current factor-correlation study."""

    symbol: str
    session_date: date
    transition_risk_score: float  # 0-100
    probability_continuation: float  # 0-1
    probability_reversal: float  # 0-1
    expected_volatility: float
    expected_direction: TransitionDirection
    historical_similarity_score: float  # 0-1
    top_contributing_factors: list[ContributingFactor] = field(default_factory=list)
    statistical_confidence: ConfidenceLabel = "Insufficient data"
    explanation: str = ""
    computed_at: datetime | None = None
    # Phase 9C: the unified UP/DOWN/NO-MATERIAL-MOVE read (spec Part 9) --
    # exposes the SAME up_count/down_count/other tally score_day() already
    # computes internally from analogs' real post_transition_move sign,
    # just as proportions rather than only the derived expected_direction
    # label. Safe defaults so every existing call site/fixture that builds
    # a DailyTransitionScore directly keeps working unchanged.
    probability_up: float = 0.0
    probability_down: float = 0.0
    probability_flat: float = 0.0


@dataclass
class MostSimilarDay:
    session_date: date
    distance: float  # lower = more similar
    similarity: float  # 1/(1+distance), 0-1
    outcome: TransitionOutcomeLabel
    transition_direction: TransitionDirection


@dataclass
class TransitionTimingEstimate:
    """When, historically, the transition tended to actually begin among
    the matched analogs -- distinct from the fixed 15:00-15:01 definition
    used to MEASURE the transition; this estimates when price action
    actually started moving."""

    earliest: time | None
    latest: time | None
    n_analogs_with_onset: int
    note: str


@dataclass
class LiveAdvisory:
    """The Live Market Transition Advisor's output for one point-in-time
    check during the 2:00-3:01pm window. Never a trading signal -- only
    Observe/Low/Medium/High/Very High transition risk plus a confidence
    label. Entirely independent of the trading decision engine; consumes
    the historical MTI database (DailyTransitionRecord/FactorCorrelationResult)
    read-only, never writes back to it."""

    symbol: str
    session_date: date
    as_of: datetime
    stage: TransitionStage
    historical_similarity_score: float
    most_similar_days: list[MostSimilarDay]
    expected_direction: TransitionDirection
    probability_continuation: float
    probability_reversal: float
    expected_volatility: float
    expected_timing: TransitionTimingEstimate | None
    estimated_move: float  # signed mean of analogs' post_transition_move
    risk_level: TransitionRiskLevel
    statistical_confidence: ConfidenceLabel
    top_contributing_factors: list[ContributingFactor]
    institutional_bias_label: str | None
    news_risk_score: int | None
    news_sentiment: str | None
    explanation: str
