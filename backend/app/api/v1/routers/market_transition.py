from fastapi import APIRouter, Depends

from app.api.v1.dependencies import get_market_transition_service
from app.schemas.market_transition import MtiResearchResponseDTO
from app.services.market_transition_service import MarketTransitionService

router = APIRouter()


@router.get("/market-transition/{symbol}/research", response_model=MtiResearchResponseDTO)
async def get_market_transition_research(
    symbol: str, service: MarketTransitionService = Depends(get_market_transition_service)
) -> MtiResearchResponseDTO:
    """Market Transition Intelligence research view: factor-correlation
    findings across all analyzed trading days, plus each day's per-day
    score. Research/validation tool, entirely independent of the trading
    decision engine -- does not feed confidence_score or any live signal.
    """
    return await service.get_research(symbol)
