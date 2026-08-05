"""Pure dataclasses for the Volume Intelligence Engine (VIE). No DB/pipeline/
network dependency -- mirrors market_transition/models.py's "define the
entire output vocabulary as dataclasses + Literal types up front" pattern,
so downstream code can never emit an out-of-band label.

VIE reads volume as a leading indicator: how today's 1-minute volume
behavior (magnitude, direction, persistence, shape) compares to historical
behavior, and what that implies about the next 5-15 minutes. It is
deliberately independent of analytics/confidence_score.py,
analytics/trend_classifier.py, analytics/institutional_bias.py, and
decision/decision_card.py -- informational only, never part of the live
trading-decision path.

No tick/bid-ask data exists anywhere in this pipeline (Dhan's REST API only
provides 1-minute OHLCV). Every "buy volume" / "sell volume" figure in this
package is therefore an ESTIMATED PROXY derived from where each candle
closed within its own high-low range (see proxy.py), not real trade-side
data -- disclosed explicitly wherever it's surfaced.
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Literal

BaselineGroup = Literal["yesterday", "last_5_days", "last_20_days", "same_weekday", "expiry_day", "monthly_expiry_day"]
RvolLabel = Literal["Above Average", "Average", "Below Average"]
DominantSide = Literal["buy", "sell", "balanced"]
AccelerationLabel = Literal["Accelerating", "Stable", "Decelerating"]
MomentumLabel = Literal["Strong Buy Momentum", "Buy Momentum", "Neutral", "Sell Momentum", "Strong Sell Momentum"]
InstitutionalLabel = Literal["Minimal", "Low", "Moderate", "High", "Very High"]
VolumeTrendLabel = Literal["Strong Increasing", "Increasing", "Stable", "Decreasing", "Strong Decreasing"]
VolumeCharacterLabel = Literal["Accumulation", "Distribution", "Markup", "Markdown", "Climactic", "Quiet-Consolidation"]
ExhaustionDirection = Literal["up", "down"]
ResemblanceLabel = Literal[
    "accumulation-like sessions",
    "distribution-like sessions",
    "climactic/high-volume sessions",
    "quiet/low-volume sessions",
    "mixed/typical sessions",
]
ForecastConfidence = Literal["Low", "Medium", "High"]
DailyComparisonLabel = Literal["Much Higher", "Higher", "Similar", "Lower", "Much Lower"]
PriceDirection = Literal["up", "down", "flat"]


@dataclass
class BaselineReading:
    """One historical comparison baseline's volume curve, read at a single
    elapsed-session-minute -- the same "average across days, at the same
    elapsed time" technique volume_profile_intelligence.py's
    compute_volume_pace() already uses, generalized across 6 groupings."""

    group: BaselineGroup
    elapsed_minutes: int
    interval_avg_volume: float | None  # mean of that single minute's volume, across sample days
    cumulative_avg_volume: float | None  # mean of cumulative volume from session start through elapsed_minutes
    sample_days: int
    dates_used: list[date] = field(default_factory=list)


@dataclass
class RvolBaselineResult:
    group: BaselineGroup
    interval_rvol_pct: float | None  # current 1-min volume / baseline interval avg * 100
    cumulative_rvol_pct: float | None  # today's cumulative volume so far / baseline cumulative avg * 100
    label: RvolLabel | None
    sample_days: int


@dataclass
class RvolReading:
    by_baseline: dict[BaselineGroup, RvolBaselineResult] = field(default_factory=dict)
    primary: RvolBaselineResult | None = None  # last_20_days, used for the headline read


@dataclass
class VolumeAcceleration:
    """Is the RATE of total volume itself speeding up or slowing down --
    distinct from VolumeMomentum, which measures which SIDE (buy/sell) has
    been persistently dominant."""

    recent_avg_volume: float
    prior_avg_volume: float
    ratio: float | None
    pct_change: float | None
    label: AccelerationLabel


@dataclass
class VolumeSpike:
    is_spike: bool
    multiple: float | None
    baseline_source: Literal["historical_20d", "intraday_rolling"] | None
    baseline_volume: float | None


@dataclass
class VolumeDryUp:
    is_dryup: bool
    fraction: float | None
    baseline_source: Literal["historical_20d", "intraday_rolling"] | None
    baseline_volume: float | None


@dataclass
class BuySellDominance:
    window_minutes: int  # actual window used -- may be less than the nominal window near session open
    buy_volume: float
    sell_volume: float
    dominance_ratio: float  # buy / (buy+sell); 0.5 if both zero
    dominant_side: DominantSide
    consecutive_dominant_minutes: int


@dataclass
class CumulativePressure:
    cum_buy_volume: float
    cum_sell_volume: float
    net_pressure: float
    pressure_ratio: float  # cum_buy / (cum_buy+cum_sell); 0.5 if both zero


@dataclass
class VolumeMomentum:
    ema_signed_volume: float
    normalized_score: float  # -1..1
    streak_minutes: int
    label: MomentumLabel


@dataclass
class InstitutionalParticipation:
    """Volume-side-only signal (large/blocky candles + sustained RVOL +
    sustained dominance). Deliberately does NOT read option-chain OI --
    analytics/institutional_bias.py already covers OI-based positioning;
    this is a complementary, distinct signal source, not a duplicate."""

    score: int  # 0-100
    label: InstitutionalLabel
    rvol_component: float
    blockiness_component: float
    dominance_component: float


@dataclass
class AbsorptionSignal:
    """High volume with little price movement -- a documented pattern hint
    (large size being absorbed without letting price move), not a
    definitive claim, same spirit as this codebase's Profile Shape/Opening
    Type heuristics."""

    detected: bool
    range_ratio: float | None
    volume_multiple: float | None
    side_hint: Literal["buy_absorption", "sell_absorption", "undetermined"]


@dataclass
class ExhaustionSignal:
    """A volume climax after an extended directional move with a rejection
    wick -- a documented "blow-off" pattern hint often preceding a
    reversal, not a guarantee."""

    detected: bool
    direction: ExhaustionDirection | None
    move_over_window: float | None
    volume_multiple: float | None
    wick_ratio: float | None


@dataclass
class VolumeTrend:
    window_minutes: int
    pct_change: float | None
    label: VolumeTrendLabel


@dataclass
class VolumeCharacter:
    """A reasonable, documented heuristic synthesis (Wyckoff-inspired), not
    a claim of matching one canonical textbook definition -- same framing
    already used for Profile Shape/Opening Type/Rotation Factor in
    analytics/volume_profile_intelligence.py."""

    label: VolumeCharacterLabel
    rationale: str


@dataclass
class SimilarDay:
    session_date: date
    distance: float  # lower = more similar
    similarity: float  # 1/(1+distance), 0-1
    dominant_side: DominantSide
    total_volume_ratio: float  # that day's total volume to the same elapsed point, vs today's 20-day RVOL baseline (1.0 if unavailable)


@dataclass
class HistoricalSimilarity:
    top_days: list[SimilarDay] = field(default_factory=list)
    resemblance_label: ResemblanceLabel | None = None
    n_days_compared: int = 0


@dataclass
class NextIntervalForecast:
    """Estimates ONLY the next horizon_minutes -- never the rest of the
    trading day. A documented heuristic composite (like
    market_transition/live_advisor.py's compute_transition_risk_level()),
    not a fitted statistical model -- this codebase deliberately avoids
    fitted models given limited history."""

    horizon_minutes: int
    probability_continuation: float
    probability_reversal: float
    confidence: ForecastConfidence
    supporting_factors: list[str] = field(default_factory=list)
    composite_score: float = 0.0


@dataclass
class VolumeNarrative:
    """Deterministic, template-generated text -- never an LLM call, same
    design decision as every other live/per-minute explanation in this app
    (market_transition's _explanation()/_build_explanation()) -- composed
    only from the numbers actually computed above, so it can never overstate
    certainty."""

    headline: str
    observations: list[str] = field(default_factory=list)


@dataclass
class DailyVolumeComparison:
    """One row of the day-over-day volume trend table: a trading day's
    volume-so-far (as of the same elapsed session time as the current
    read) vs. the immediately preceding trading day's volume at that same
    elapsed point -- a chain of consecutive day-over-day comparisons, not
    comparisons against a multi-day average (that's RvolReading's job)."""

    session_date: date
    volume_as_of: float
    prior_day_volume_as_of: float | None
    pct_change: float | None
    label: DailyComparisonLabel | None
    interpretation: str


@dataclass
class DailyVolumeTrend:
    elapsed_minutes: int  # the elapsed-session-time cutoff every row was measured at, for context
    days: list[DailyVolumeComparison] = field(default_factory=list)


@dataclass
class SignificantInterval:
    """One 5-minute bucket of today's session whose volume cleared the
    "notable" bar against the historical average for that same time-of-day
    window. Only buckets that clear the bar are ever produced -- most of
    the day should show nothing here, same "don't spam" philosophy as
    narrative.py's observation gate."""

    start_time: datetime
    end_time: datetime
    interval_volume: float
    baseline_volume: float | None
    pct_change: float | None
    multiple: float | None
    dominant_side: DominantSide
    price_direction: PriceDirection
    institutional_note: str
    trend_note: str


@dataclass
class VolumeIntelligence:
    """The top-level snapshot returned by engine.py::compute_volume_intelligence().
    Every field is optional/None-able so a thin-data session (e.g. the first
    few minutes after open) degrades gracefully rather than raising."""

    symbol: str
    as_of: datetime | None
    rvol: RvolReading | None = None
    acceleration: VolumeAcceleration | None = None
    dominance: BuySellDominance | None = None
    cumulative_pressure: CumulativePressure | None = None
    momentum: VolumeMomentum | None = None
    institutional: InstitutionalParticipation | None = None
    spike: VolumeSpike | None = None
    dryup: VolumeDryUp | None = None
    absorption: AbsorptionSignal | None = None
    exhaustion: ExhaustionSignal | None = None
    trend: VolumeTrend | None = None
    character: VolumeCharacter | None = None
    similarity: HistoricalSimilarity | None = None
    forecast: NextIntervalForecast | None = None
    narrative: VolumeNarrative | None = None
    daily_volume_trend: DailyVolumeTrend | None = None
    significant_intervals: list[SignificantInterval] = field(default_factory=list)
