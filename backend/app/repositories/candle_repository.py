from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import RawCandle


class CandleRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_since(self, symbol: str, since: datetime) -> list[RawCandle]:
        stmt = (
            select(RawCandle)
            .where(RawCandle.symbol == symbol, RawCandle.timestamp >= since)
            .order_by(RawCandle.timestamp.asc())
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_between(self, symbol: str, start: datetime, end: datetime) -> list[RawCandle]:
        """Both-bounded fetch -- used for narrow windows (e.g. a single
        historical analog day's ~14:50-15:10 candles for the live
        advisor's transition-timing estimate), where list_since's
        open-ended upper bound would pull in every day since."""
        stmt = (
            select(RawCandle)
            .where(RawCandle.symbol == symbol, RawCandle.timestamp >= start, RawCandle.timestamp <= end)
            .order_by(RawCandle.timestamp.asc())
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())
