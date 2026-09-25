from typing import Any

from pydantic import BaseModel


class LiveScalpingDTO(BaseModel):
    """13A-live-scalping-engine-v1. DECISION SUPPORT ONLY.

    `panel` carries the market read (regime, direction, option confirmation, timing, IV, spread,
    economics) and `risk` carries the brake, with allocated capital and the daily loss limit as
    separate fields so the UI can never present one as the other."""

    version: str
    config_hash: str
    mode: str
    symbol: str
    session_date: str
    is_live_session: bool
    minute: str | None = None
    decision: str
    quality: str
    primary_rejection_reason: str | None = None
    reason_note: str | None = None
    panel: dict[str, Any]
    risk: dict[str, Any]
    open_position: dict[str, Any] | None = None
    closed_positions: list[dict[str, Any]] = []
    daily_review: dict[str, Any] | None = None
    config: dict[str, Any] | None = None
    notice: str
