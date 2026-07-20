from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from app.schemas.candle import CandleDTO
from app.schemas.option_chain import OptionChainSummaryDTO


class LevelsSummaryDTO(BaseModel):
    close: float
    vwap_now: float | None
    today_poc: float | None
    today_vah: float | None
    today_val: float | None
    support_low: float | None
    support_high: float | None
    resistance_low: float | None
    resistance_high: float | None
    trend_label: str | None
    trend_score: int | None
    institutional_bias_label: str | None
    confidence_score: int | None
    action_text: str | None
    interpretation: str | None


class DashboardResponseDTO(BaseModel):
    symbol: str
    status: Literal["live", "stale", "no_data"]
    as_of: datetime | None
    staleness_seconds: float | None
    is_market_hours: bool
    levels: LevelsSummaryDTO | None
    candles: list[CandleDTO]
    option_chain: OptionChainSummaryDTO | None
