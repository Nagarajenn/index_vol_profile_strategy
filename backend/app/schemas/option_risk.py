from typing import Any

from pydantic import BaseModel


class OptionRiskClosingStateDTO(BaseModel):
    """12B-option-risk-v1 view for one symbol-day (15:00-15:30). ADVISORY / RESEARCH ONLY.

    ``minutes`` and ``summary`` are passed through from option_risk_12b.engine
    unchanged (nested, self-describing JSON)."""
    version: str
    config_hash: str
    symbol: str
    session_date: str
    as_of: str
    is_live_session: bool
    advisory_only: bool
    caveat: str
    positions: list[dict[str, Any]]
    minutes: list[dict[str, Any]]
    ltp_series: list[dict[str, Any]] = []
    summary: dict[str, Any]
