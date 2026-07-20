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
