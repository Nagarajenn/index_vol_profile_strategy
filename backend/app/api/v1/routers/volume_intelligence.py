from fastapi import APIRouter, Depends

from app.api.v1.dependencies import get_volume_intelligence_service
from app.schemas.volume_intelligence import VolumeIntelligenceDTO
from app.services.volume_intelligence_service import VolumeIntelligenceService

router = APIRouter()


@router.get("/volume-intelligence/{symbol}", response_model=VolumeIntelligenceDTO)
async def get_volume_intelligence(
    symbol: str, service: VolumeIntelligenceService = Depends(get_volume_intelligence_service)
) -> VolumeIntelligenceDTO:
    """RVOL, Volume Acceleration, Buy/Sell Dominance, Cumulative Pressure,
    Volume Momentum, Institutional Participation, Spike/Dry-up Detection,
    Absorption/Exhaustion Detection, Volume Trend/Character Classification,
    Historical Volume Similarity, and a 5-15 minute forecast -- informational
    only, does not feed the strategy engine's trend/confidence/action outputs.
    """
    return await service.get_latest(symbol)
