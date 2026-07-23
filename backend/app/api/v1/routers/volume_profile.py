from fastapi import APIRouter, Depends

from app.api.v1.dependencies import get_volume_profile_intelligence_service
from app.schemas.volume_profile_intelligence import VolumeProfileIntelligenceDTO
from app.services.volume_profile_intelligence_service import VolumeProfileIntelligenceService

router = APIRouter()


@router.get("/volume-profile/{symbol}/intelligence", response_model=VolumeProfileIntelligenceDTO)
async def get_volume_profile_intelligence(
    symbol: str, service: VolumeProfileIntelligenceService = Depends(get_volume_profile_intelligence_service)
) -> VolumeProfileIntelligenceDTO:
    """Developing POC/VAH/VAL, HVN/LVN, Value Migration, Acceptance/Rejection,
    Profile Shape, Initial Balance, Opening Type, Rotation Factor, and Volume
    Pace -- informational only, does not feed the strategy engine's
    trend/confidence/action outputs.
    """
    return await service.get_latest(symbol)
