from fastapi import APIRouter, Depends

from app.api.v1.dependencies import get_dashboard_service
from app.schemas.levels_detail import LevelsDetailDTO
from app.services.dashboard_service import DashboardService

router = APIRouter()


@router.get("/levels/{symbol}/latest/detail", response_model=LevelsDetailDTO)
async def get_levels_latest_detail(
    symbol: str, service: DashboardService = Depends(get_dashboard_service)
) -> LevelsDetailDTO:
    """Reserved for v1.1 chart overlays (swings/trendlines/breakout boxes/
    volume-profile bins) -- not called by any V1 screen yet.
    """
    return await service.get_latest_detail(symbol)
