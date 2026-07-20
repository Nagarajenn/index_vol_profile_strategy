from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import LevelsSnapshot


class LevelsSnapshotRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_latest(self, symbol: str, mode: str = "live") -> LevelsSnapshot | None:
        stmt = (
            select(LevelsSnapshot)
            .where(LevelsSnapshot.symbol == symbol, LevelsSnapshot.mode == mode)
            .order_by(LevelsSnapshot.as_of.desc())
            .limit(1)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()
