from fastapi import APIRouter, Depends

from app.api.v1.dependencies import get_session_amd_service
from app.schemas.session_amd import SessionAmdDTO
from app.services.session_amd_service import SessionAmdService

router = APIRouter()


@router.get("/session-amd/{symbol}", response_model=SessionAmdDTO)
async def get_session_amd(symbol: str, service: SessionAmdService = Depends(get_session_amd_service)) -> SessionAmdDTO:
    """Session AMD (Accumulation / Manipulation / Distribution) structure --
    an ICT-style heuristic synthesis of today's opening accumulation range,
    any liquidity-sweep/manipulation events, and the resulting distribution
    move. Informational only, does not feed the strategy engine's
    trend/confidence/action outputs.
    """
    return await service.get_latest(symbol)
