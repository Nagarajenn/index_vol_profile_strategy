"""DTOs mirroring analytics/session_amd.py's dataclasses. Served only by
GET /api/v1/session-amd/{symbol} -- informational, does not feed the
strategy engine, matches the volume-intelligence/volume-profile DTO
pattern.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

SweepDirectionLiteral = Literal["swept_high", "swept_low"]
DistributionDirectionLiteral = Literal["up", "down"]
DistributionStatusLiteral = Literal["Confirmed", "Developing", "Failed"]
CurrentPhaseLiteral = Literal[
    "Accumulating",
    "Range Established -- Awaiting Move",
    "Testing Range",
    "Distribution",
    "Breakout (not manipulation)",
    "No Clear Setup",
]


class AccumulationRangeDTO(BaseModel):
    high: float
    low: float
    range: float
    start_time: datetime
    end_time: datetime
    is_complete: bool


class ManipulationSweepDTO(BaseModel):
    direction: SweepDirectionLiteral
    extreme_price: float
    breakout_time: datetime
    reversal_time: datetime
    candles_to_reverse: int
    expected_distribution_direction: DistributionDirectionLiteral


class DistributionPhaseDTO(BaseModel):
    direction: DistributionDirectionLiteral
    started_at: datetime
    net_move_points: float
    net_move_pct: float
    dominant_side_confirms: bool | None
    status: DistributionStatusLiteral


class SessionAmdDTO(BaseModel):
    symbol: str
    as_of: datetime | None
    accumulation: AccumulationRangeDTO | None
    sweeps: list[ManipulationSweepDTO]
    latest_sweep: ManipulationSweepDTO | None
    distribution: DistributionPhaseDTO | None
    current_phase: CurrentPhaseLiteral
    narrative: str
