from datetime import date

from fastapi import APIRouter, Depends

from app.api.v1.dependencies import get_option_risk_service
from app.schemas.option_risk import OptionRiskClosingStateDTO
from app.services.option_risk_service import OptionRiskService

router = APIRouter()


@router.get("/option-risk-12b/{symbol}/closing-state", response_model=OptionRiskClosingStateDTO)
async def get_closing_state(
    symbol: str, session_date: date | None = None,
    service: OptionRiskService = Depends(get_option_risk_service),
) -> OptionRiskClosingStateDTO:
    """15:00-15:30 option-chain continuation, underlying state, option pressure, implied spot and
    ADVISORY position risk (12B-option-risk-v1). Read-only: this endpoint cannot open, close or
    modify any position and places no order. The 11D exit engine remains authoritative."""
    return await service.get_closing_state(symbol.upper(), session_date)
