"""Read-only queries for the 12C scalping decision panel (levels context).

Query construction only -- no business logic, no writes. Option snapshots, candles and
paper positions come from OptionRiskRepository, which already reads exactly that window.
"""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import LevelsSnapshot


class ScalpDecisionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def levels_between(self, symbol: str, start: datetime, end: datetime) -> list[LevelsSnapshot]:
        stmt = (select(LevelsSnapshot)
                .where(LevelsSnapshot.symbol == symbol, LevelsSnapshot.as_of >= start, LevelsSnapshot.as_of <= end)
                .order_by(LevelsSnapshot.as_of))
        return list((await self._session.execute(stmt)).scalars().all())

    async def levels_at_or_before(self, symbol: str, as_of: datetime) -> LevelsSnapshot | None:
        stmt = (select(LevelsSnapshot)
                .where(LevelsSnapshot.symbol == symbol, LevelsSnapshot.as_of <= as_of)
                .order_by(LevelsSnapshot.as_of.desc()).limit(1))
        return (await self._session.execute(stmt)).scalars().first()
