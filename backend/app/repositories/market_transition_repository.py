from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CasDailyTransition, CasFactorCorrelation, MtiDailyTransition, MtiFactorCorrelation


class MarketTransitionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_daily(self, symbol: str, limit: int = 200) -> list[MtiDailyTransition]:
        stmt = (
            select(MtiDailyTransition)
            .where(MtiDailyTransition.symbol == symbol)
            .order_by(MtiDailyTransition.session_date.desc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_correlations(self, symbol: str) -> list[MtiFactorCorrelation]:
        stmt = select(MtiFactorCorrelation).where(MtiFactorCorrelation.symbol == symbol)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_cas_daily(self, symbol: str, limit: int = 60) -> list[CasDailyTransition]:
        stmt = (
            select(CasDailyTransition)
            .where(CasDailyTransition.symbol == symbol)
            .order_by(CasDailyTransition.session_date.desc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return list(reversed(result.scalars().all()))

    async def list_cas_correlations(self, symbol: str) -> list[CasFactorCorrelation]:
        stmt = select(CasFactorCorrelation).where(CasFactorCorrelation.symbol == symbol)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())
