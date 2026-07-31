from fastapi import APIRouter, Depends

from app.api.v1.dependencies import get_live_transition_advisor_service, get_market_transition_service
from app.schemas.market_transition import LiveAdvisoryDTO, MtiResearchResponseDTO
from app.services.live_transition_advisor_service import LiveTransitionAdvisorService
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


@router.get("/market-transition/{symbol}/live-advisor", response_model=LiveAdvisoryDTO)
async def get_live_transition_advisor(
    symbol: str, service: LiveTransitionAdvisorService = Depends(get_live_transition_advisor_service)
) -> LiveAdvisoryDTO:
    """Live Market Transition Advisor: compares today's in-progress session
    against the historical MTI database above. Only produces a meaningful
    read between 2:00 PM and 3:01 PM IST -- outside that window `is_active`
    is false. Never a trading signal: risk_level is capped to
    Observe/Low/Medium/High/Very High, no buy/sell language anywhere.
    Read-only, independent of the trading decision engine.
    """
    return await service.get_live_advisory(symbol)
