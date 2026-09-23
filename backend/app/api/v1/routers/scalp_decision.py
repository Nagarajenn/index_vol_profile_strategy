from datetime import date

from fastapi import APIRouter, Depends

from app.api.v1.dependencies import get_scalp_decision_service
from app.schemas.scalp_decision import ScalpDecisionDTO, SimPositionHistoryDTO
from app.services.scalp_decision_service import ScalpDecisionService

router = APIRouter()


@router.get("/scalp-decision-12c/{symbol}", response_model=ScalpDecisionDTO)
async def get_scalp_decision(
    symbol: str, session_date: date | None = None, position: str | None = None, strike: float | None = None,
    service: ScalpDecisionService = Depends(get_scalp_decision_service),
) -> ScalpDecisionDTO:
    """Explainable scalping decision (BUY CE / BUY PE / WAIT) and, when a position exists, the
    advisory risk brake (HOLD / CAUTION / PREPARE_EXIT / EXIT), with the evidence behind it.

    ADVISORY ONLY and read-only: this endpoint places no order and cannot open, close or modify
    any position. `position` (CE|PE) and `strike` let a trader see the brake for a position they
    hold themselves; an open paper position always takes precedence."""
    return await service.get_decision(symbol.upper(), session_date, position.upper() if position else None, strike)


@router.get("/scalp-decision-12c/{symbol}/history", response_model=SimPositionHistoryDTO)
async def get_position_history(
    symbol: str, session_date: date | None = None, limit: int = 200,
    service: ScalpDecisionService = Depends(get_scalp_decision_service),
) -> SimPositionHistoryDTO:
    """Closed HYPOTHETICAL positions for a session, each with the decision that closed it.

    SIMULATION ONLY and read-only: these are not orders and not paper-account trades. Rows come
    from sim12c_positions when the session has been stored (scripts/run_12c_position_history.py),
    otherwise the session is replayed on the fly and marked LIVE_REPLAY."""
    return await service.get_history(symbol.upper(), session_date, limit)
