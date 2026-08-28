from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    CasDailyTransition,
    CasFactorCorrelation,
    CasPostTransitionMinute,
    CasPretransitionWindow,
    CasTransitionForecast,
    MtiDailyTransition,
    MtiFactorCorrelation,
)


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
        return list(result.scalars().all())  # most recent first, matching list_daily's convention

    async def list_cas_correlations(self, symbol: str) -> list[CasFactorCorrelation]:
        stmt = select(CasFactorCorrelation).where(CasFactorCorrelation.symbol == symbol)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    # --- Phase 7B: dual-resolution pre/post-3pm transition detail, lazy-
    # loaded per (symbol, session_date) -- never eagerly joined into the
    # hot list_cas_daily poll above.

    async def list_pretransition_windows(self, symbol: str, session_date: date) -> list[CasPretransitionWindow]:
        stmt = (
            select(CasPretransitionWindow)
            .where(CasPretransitionWindow.symbol == symbol, CasPretransitionWindow.session_date == session_date)
            .order_by(CasPretransitionWindow.window_index)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_post_transition_minutes(self, symbol: str, session_date: date) -> list[CasPostTransitionMinute]:
        stmt = (
            select(CasPostTransitionMinute)
            .where(CasPostTransitionMinute.symbol == symbol, CasPostTransitionMinute.session_date == session_date)
            .order_by(CasPostTransitionMinute.minute_offset)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_transition_forecasts(self, symbol: str, session_date: date) -> list[CasTransitionForecast]:
        stmt = (
            select(CasTransitionForecast)
            .where(CasTransitionForecast.symbol == symbol, CasTransitionForecast.session_date == session_date)
            .order_by(CasTransitionForecast.checkpoint_time)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())
