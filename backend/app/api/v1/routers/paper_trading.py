from datetime import date

from fastapi import APIRouter, Depends

from app.api.v1.dependencies import get_paper_trading_service
from app.schemas.paper_trading import (
    PaperAccountDTO,
    PaperDecisionDTO,
    PaperPositionDTO,
    PaperStatusDTO,
    PaperTodayDTO,
)
from app.services.paper_trading_service import PaperTradingService

router = APIRouter()

_PAPER_NOTE = (
    "PAPER MODE -- entirely simulated. No real order is ever placed and this API "
    "cannot cause a trade: it is read-only, and only the paper agent process writes "
    "to the paper_* tables. All P&L is PRE-COST."
)


@router.get("/paper-trading/status", response_model=PaperStatusDTO)
async def get_status(service: PaperTradingService = Depends(get_paper_trading_service)) -> PaperStatusDTO:
    """Agent state, kill-switch state, versions, and experiment day. """ + _PAPER_NOTE
    return await service.get_status()


@router.get("/paper-trading/account", response_model=PaperAccountDTO)
async def get_account(service: PaperTradingService = Depends(get_paper_trading_service)) -> PaperAccountDTO:
    """Virtual account: balance, P&L, drawdown and streaks. """ + _PAPER_NOTE
    return await service.get_account()


@router.get("/paper-trading/today", response_model=PaperTodayDTO)
async def get_today(service: PaperTradingService = Depends(get_paper_trading_service)) -> PaperTodayDTO:
    """Everything the Command Center needs for the current session in one
    poll: status, account, both symbols' 14:59 decisions, any open
    position, closed trades and decision-quality outcomes. """ + _PAPER_NOTE
    return await service.get_today()


@router.get("/paper-trading/decisions", response_model=list[PaperDecisionDTO])
async def list_decisions(
    session_date: date | None = None, limit: int = 100,
    service: PaperTradingService = Depends(get_paper_trading_service),
) -> list[PaperDecisionDTO]:
    """Frozen 14:59 decisions, including every NO TRADE -- a NO TRADE day
    still records the full market state the agent saw. """ + _PAPER_NOTE
    return await service.list_decisions(session_date, limit)


@router.get("/paper-trading/open-position", response_model=PaperPositionDTO | None)
async def get_open_position(
    service: PaperTradingService = Depends(get_paper_trading_service),
) -> PaperPositionDTO | None:
    """The currently open simulated position with its management-event
    trail, or null. """ + _PAPER_NOTE
    return await service.get_open_position()


@router.get("/paper-trading/trades", response_model=list[PaperPositionDTO])
async def list_trades(
    limit: int = 200, service: PaperTradingService = Depends(get_paper_trading_service),
) -> list[PaperPositionDTO]:
    """Closed simulated trades with full management history. """ + _PAPER_NOTE
    return await service.list_trades(limit)
