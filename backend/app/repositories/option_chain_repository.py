from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import OptionChainSummary


class OptionChainRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_latest_summary(self, symbol: str) -> OptionChainSummary | None:
        stmt = (
            select(OptionChainSummary)
            .where(OptionChainSummary.symbol == symbol)
            .order_by(OptionChainSummary.fetched_at.desc())
            .limit(1)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()
