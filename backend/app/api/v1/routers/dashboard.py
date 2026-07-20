from fastapi import APIRouter, Depends

from app.api.v1.dependencies import get_dashboard_service
from app.schemas.dashboard import DashboardResponseDTO
from app.services.dashboard_service import DashboardService

router = APIRouter()


@router.get("/dashboard/{symbol}/latest", response_model=DashboardResponseDTO)
async def get_dashboard_latest(
    symbol: str, service: DashboardService = Depends(get_dashboard_service)
) -> DashboardResponseDTO:
    return await service.get_latest(symbol)
