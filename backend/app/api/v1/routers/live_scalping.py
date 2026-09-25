from datetime import date

from fastapi import APIRouter, Depends

from app.api.v1.dependencies import get_live_scalping_service
from app.schemas.live_scalping import LiveScalpingDTO
from app.services.live_scalping_service import LiveScalpingService

router = APIRouter()


@router.get("/live-scalping-13a/{symbol}", response_model=LiveScalpingDTO)
async def get_live_scalping(
    symbol: str, session_date: date | None = None,
    service: LiveScalpingService = Depends(get_live_scalping_service),
) -> LiveScalpingDTO:
    """13A live scalping decision: BUY CE / BUY PE / WAIT with the gate that refused it.

    DECISION SUPPORT ONLY and read-only. This endpoint places no order, cannot open or close
    any position, and has no broker path behind it. The risk brake reports allocated capital and
    the daily loss limit as separate quantities -- they are not the same number."""
    return await service.get_panel(symbol.upper(), session_date)
