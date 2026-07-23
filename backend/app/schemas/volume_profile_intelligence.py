"""DTOs mirroring analytics/volume_profile_intelligence.py's dataclasses.
Served only by GET /api/v1/volume-profile/{symbol}/intelligence -- not part
of the hot-polled /dashboard/{symbol}/latest response, since this needs a
multi-day candle fetch and full profile recomputation, much heavier than the
regular poll.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class DevelopingPointDTO(BaseModel):
    timestamp: datetime
    poc: float
    vah: float
    val: float


class VolumeNodeDTO(BaseModel):
    price: float
    volume: float
    kind: Literal["hvn", "lvn"]


class ValueMigrationDTO(BaseModel):
    poc_shift: float
    poc_shift_pct: float
    direction: Literal["up", "down", "flat"]
    vah_shift: float
    val_shift: float
    intraday_poc_drift: float


class LevelTestDTO(BaseModel):
    level_name: str
    price: float
    outcome: Literal["accepted", "rejected", "untested"]
    touches: int


class ProfileShapeDTO(BaseModel):
    shape: Literal["P", "b", "D", "B"]
    description: str


class InitialBalanceDTO(BaseModel):
    ib_high: float
    ib_low: float
    ib_range: float
    end_time: datetime
    is_complete: bool


class OpeningTypeDTO(BaseModel):
    type: Literal["Open-Drive", "Open-Test-Drive", "Open-Rejection-Reverse", "Open-Auction"]
    description: str


class RotationFactorDTO(BaseModel):
    value: int
    periods: int
    label: Literal["Trending", "Rotational"]


class VolumePaceDTO(BaseModel):
    pace_pct: float
    today_cumulative: float
    average_cumulative: float
    label: Literal["Above Average", "Average", "Below Average"]


class VolumeProfileIntelligenceDTO(BaseModel):
    symbol: str
    as_of: datetime | None
    developing: list[DevelopingPointDTO]
    hvns: list[VolumeNodeDTO]
    lvns: list[VolumeNodeDTO]
    migration: ValueMigrationDTO | None
    level_tests: list[LevelTestDTO]
    profile_shape: ProfileShapeDTO | None
    initial_balance: InitialBalanceDTO | None
    opening_type: OpeningTypeDTO | None
    rotation_factor: RotationFactorDTO | None
    volume_pace: VolumePaceDTO | None
