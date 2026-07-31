from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.repositories.candle_repository import CandleRepository
from app.repositories.levels_snapshot_repository import LevelsSnapshotRepository
from app.repositories.market_intelligence_repository import MarketIntelligenceRepository
from app.repositories.market_transition_repository import MarketTransitionRepository
from app.repositories.option_chain_repository import OptionChainRepository
from app.services.dashboard_service import DashboardService
from app.services.live_transition_advisor_service import LiveTransitionAdvisorService
from app.services.market_intelligence_service import MarketIntelligenceService
from app.services.market_transition_service import MarketTransitionService
from app.services.volume_profile_intelligence_service import VolumeProfileIntelligenceService


def get_levels_repository(session: AsyncSession = Depends(get_db_session)) -> LevelsSnapshotRepository:
    return LevelsSnapshotRepository(session)


def get_candle_repository(session: AsyncSession = Depends(get_db_session)) -> CandleRepository:
    return CandleRepository(session)


def get_option_chain_repository(session: AsyncSession = Depends(get_db_session)) -> OptionChainRepository:
    return OptionChainRepository(session)


def get_dashboard_service(
    levels_repo: LevelsSnapshotRepository = Depends(get_levels_repository),
    candle_repo: CandleRepository = Depends(get_candle_repository),
    option_chain_repo: OptionChainRepository = Depends(get_option_chain_repository),
) -> DashboardService:
    return DashboardService(levels_repo, candle_repo, option_chain_repo)


def get_volume_profile_intelligence_service(
    candle_repo: CandleRepository = Depends(get_candle_repository),
) -> VolumeProfileIntelligenceService:
    return VolumeProfileIntelligenceService(candle_repo)


def get_market_intelligence_repository(
    session: AsyncSession = Depends(get_db_session),
) -> MarketIntelligenceRepository:
    return MarketIntelligenceRepository(session)


def get_market_intelligence_service(
    repo: MarketIntelligenceRepository = Depends(get_market_intelligence_repository),
) -> MarketIntelligenceService:
    return MarketIntelligenceService(repo)


def get_market_transition_repository(
    session: AsyncSession = Depends(get_db_session),
) -> MarketTransitionRepository:
    return MarketTransitionRepository(session)


def get_market_transition_service(
    repo: MarketTransitionRepository = Depends(get_market_transition_repository),
) -> MarketTransitionService:
    return MarketTransitionService(repo)


def get_live_transition_advisor_service(
    candle_repo: CandleRepository = Depends(get_candle_repository),
    mti_repo: MarketTransitionRepository = Depends(get_market_transition_repository),
    levels_repo: LevelsSnapshotRepository = Depends(get_levels_repository),
    mi_service: MarketIntelligenceService = Depends(get_market_intelligence_service),
) -> LiveTransitionAdvisorService:
    return LiveTransitionAdvisorService(candle_repo, mti_repo, levels_repo, mi_service)
