from fastapi import APIRouter, Depends

from app.api.v1.dependencies import get_market_intelligence_service
from app.schemas.market_intelligence import MarketIntelligenceSummaryDTO
from app.services.market_intelligence_service import MarketIntelligenceService

router = APIRouter()


@router.get("/market-intelligence/latest", response_model=MarketIntelligenceSummaryDTO)
async def get_market_intelligence_latest(
    service: MarketIntelligenceService = Depends(get_market_intelligence_service),
) -> MarketIntelligenceSummaryDTO:
    """Latest classified news events plus a derived overall sentiment / news
    risk score -- informational only, does not feed the strategy engine's
    trend/confidence/action outputs. Symbol-independent (news isn't scoped
    to one index).
    """
    return await service.get_latest()
