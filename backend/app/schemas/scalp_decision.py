from typing import Any

from pydantic import BaseModel


class ScalpDecisionDTO(BaseModel):
    """12C-scalp-decision-v1. ADVISORY ONLY: rule-based, explainable, never an order.

    `entry`, `risk_brake`, `evidence`, `summary`, `option_state`, `closing_state` and
    `trace` are passed through from scalp_decision_12c.engine unchanged."""
    version: str
    config_hash: str
    symbol: str
    session_date: str
    minute: str | None
    status: str
    position_state: str | None = None
    is_live_session: bool = False
    position_source: str | None = None
    advisory_only: bool = True
    notice: str | None = None
    reason: str | None = None
    decision: str | None = None
    confirmation: str | None = None
    entry: dict[str, Any] | None = None
    risk_brake: dict[str, Any] | None = None
    evidence: dict[str, Any] | None = None
    summary: dict[str, Any] | None = None
    option_state: dict[str, Any] | None = None
    closing_state: list[dict[str, Any]] = []
    levels: dict[str, Any] | None = None
    trace: dict[str, Any] | None = None
    position_simulation: dict[str, Any] | None = None
