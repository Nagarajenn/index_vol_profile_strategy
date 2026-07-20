"""DTOs mirroring analytics/swings.py::SwingPoint, analytics/trendlines.py::Trendline,
analytics/breakout_boxes.py::BreakoutBox. Defined now (cheap, shapes already
exist) so the wire format is locked in before v1.1 wires them into chart
overlays -- not used by the hot-polled /dashboard/{symbol}/latest endpoint,
only by the reserved /levels/{symbol}/latest/detail endpoint (see M20).
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from app.schemas.dashboard import LevelsSummaryDTO


class SwingPointDTO(BaseModel):
    timestamp: datetime
    price: float
    kind: Literal["high", "low"]
    confirmed: bool


class TrendlineDTO(BaseModel):
    points: list[tuple[datetime, float]]
    direction: Literal["up", "down"]
    r2: float
    touch_count: int


class BreakoutBoxDTO(BaseModel):
    t_start: datetime
    t_end: datetime
    p_low: float
    p_high: float
    status: Literal["forming", "confirmed_up", "confirmed_down"]
    avg_volume: float


class LevelsDetailDTO(LevelsSummaryDTO):
    """Everything in LevelsSummaryDTO plus the JSONB-derived detail arrays --
    only served by /levels/{symbol}/latest/detail, never the hot-polled
    /dashboard/{symbol}/latest (today_vp_bins alone can run to hundreds of
    keys, unnecessary weight on something polled every 15-30s).
    """

    today_vp_bins: dict[str, float] | None
    swings: list[SwingPointDTO]
    trendlines: list[TrendlineDTO]
    breakout_boxes: list[BreakoutBoxDTO]
