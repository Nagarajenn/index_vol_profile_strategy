"""DTOs mirroring analytics/volume_intelligence/models.py's dataclasses.
Served only by GET /api/v1/volume-intelligence/{symbol} -- not part of the
hot-polled /dashboard/{symbol}/latest response, since this needs a
multi-day (~60 trading day) candle fetch and full recomputation of 14
metrics, much heavier than the regular poll.
"""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel

BaselineGroupLiteral = Literal["yesterday", "last_5_days", "last_20_days", "same_weekday", "expiry_day", "monthly_expiry_day"]
RvolLabelLiteral = Literal["Above Average", "Average", "Below Average"]
DominantSideLiteral = Literal["buy", "sell", "balanced"]
AccelerationLabelLiteral = Literal["Accelerating", "Stable", "Decelerating"]
MomentumLabelLiteral = Literal["Strong Buy Momentum", "Buy Momentum", "Neutral", "Sell Momentum", "Strong Sell Momentum"]
InstitutionalLabelLiteral = Literal["Minimal", "Low", "Moderate", "High", "Very High"]
VolumeTrendLabelLiteral = Literal["Strong Increasing", "Increasing", "Stable", "Decreasing", "Strong Decreasing"]
VolumeCharacterLabelLiteral = Literal["Accumulation", "Distribution", "Markup", "Markdown", "Climactic", "Quiet-Consolidation"]
ExhaustionDirectionLiteral = Literal["up", "down"]
ResemblanceLabelLiteral = Literal[
    "accumulation-like sessions",
    "distribution-like sessions",
    "climactic/high-volume sessions",
    "quiet/low-volume sessions",
    "mixed/typical sessions",
]
ForecastConfidenceLiteral = Literal["Low", "Medium", "High"]
DailyComparisonLabelLiteral = Literal["Much Higher", "Higher", "Similar", "Lower", "Much Lower"]
PriceDirectionLiteral = Literal["up", "down", "flat"]


class RvolBaselineResultDTO(BaseModel):
    group: BaselineGroupLiteral
    interval_rvol_pct: float | None
    cumulative_rvol_pct: float | None
    label: RvolLabelLiteral | None
    sample_days: int


class RvolReadingDTO(BaseModel):
    by_baseline: dict[str, RvolBaselineResultDTO]
    primary: RvolBaselineResultDTO | None


class VolumeAccelerationDTO(BaseModel):
    recent_avg_volume: float
    prior_avg_volume: float
    ratio: float | None
    pct_change: float | None
    label: AccelerationLabelLiteral


class VolumeSpikeDTO(BaseModel):
    is_spike: bool
    multiple: float | None
    baseline_source: Literal["historical_20d", "intraday_rolling"] | None
    baseline_volume: float | None


class VolumeDryUpDTO(BaseModel):
    is_dryup: bool
    fraction: float | None
    baseline_source: Literal["historical_20d", "intraday_rolling"] | None
    baseline_volume: float | None


class BuySellDominanceDTO(BaseModel):
    window_minutes: int
    buy_volume: float
    sell_volume: float
    dominance_ratio: float
    dominant_side: DominantSideLiteral
    consecutive_dominant_minutes: int


class CumulativePressureDTO(BaseModel):
    cum_buy_volume: float
    cum_sell_volume: float
    net_pressure: float
    pressure_ratio: float


class VolumeMomentumDTO(BaseModel):
    ema_signed_volume: float
    normalized_score: float
    streak_minutes: int
    label: MomentumLabelLiteral


class InstitutionalParticipationDTO(BaseModel):
    score: int
    label: InstitutionalLabelLiteral
    rvol_component: float
    blockiness_component: float
    dominance_component: float


class AbsorptionSignalDTO(BaseModel):
    detected: bool
    range_ratio: float | None
    volume_multiple: float | None
    side_hint: Literal["buy_absorption", "sell_absorption", "undetermined"]


class ExhaustionSignalDTO(BaseModel):
    detected: bool
    direction: ExhaustionDirectionLiteral | None
    move_over_window: float | None
    volume_multiple: float | None
    wick_ratio: float | None


class VolumeTrendDTO(BaseModel):
    window_minutes: int
    pct_change: float | None
    label: VolumeTrendLabelLiteral


class VolumeCharacterDTO(BaseModel):
    label: VolumeCharacterLabelLiteral
    rationale: str


class SimilarDayDTO(BaseModel):
    session_date: date
    distance: float
    similarity: float
    dominant_side: DominantSideLiteral
    total_volume_ratio: float


class HistoricalSimilarityDTO(BaseModel):
    top_days: list[SimilarDayDTO]
    resemblance_label: ResemblanceLabelLiteral | None
    n_days_compared: int


class NextIntervalForecastDTO(BaseModel):
    horizon_minutes: int
    probability_continuation: float
    probability_reversal: float
    confidence: ForecastConfidenceLiteral
    supporting_factors: list[str]
    composite_score: float


class VolumeNarrativeDTO(BaseModel):
    headline: str
    observations: list[str]


class DailyVolumeComparisonDTO(BaseModel):
    session_date: date
    volume_as_of: float
    prior_day_volume_as_of: float | None
    pct_change: float | None
    label: DailyComparisonLabelLiteral | None
    interpretation: str


class DailyVolumeTrendDTO(BaseModel):
    elapsed_minutes: int
    days: list[DailyVolumeComparisonDTO]


class SignificantIntervalDTO(BaseModel):
    start_time: datetime
    end_time: datetime
    interval_volume: float
    baseline_volume: float | None
    pct_change: float | None
    multiple: float | None
    dominant_side: DominantSideLiteral
    price_direction: PriceDirectionLiteral
    institutional_note: str
    trend_note: str


class VolumeIntelligenceDTO(BaseModel):
    symbol: str
    as_of: datetime | None
    rvol: RvolReadingDTO | None
    acceleration: VolumeAccelerationDTO | None
    dominance: BuySellDominanceDTO | None
    cumulative_pressure: CumulativePressureDTO | None
    momentum: VolumeMomentumDTO | None
    institutional: InstitutionalParticipationDTO | None
    spike: VolumeSpikeDTO | None
    dryup: VolumeDryUpDTO | None
    absorption: AbsorptionSignalDTO | None
    exhaustion: ExhaustionSignalDTO | None
    trend: VolumeTrendDTO | None
    character: VolumeCharacterDTO | None
    similarity: HistoricalSimilarityDTO | None
    forecast: NextIntervalForecastDTO | None
    narrative: VolumeNarrativeDTO | None
    daily_volume_trend: DailyVolumeTrendDTO | None
    significant_intervals: list[SignificantIntervalDTO]
