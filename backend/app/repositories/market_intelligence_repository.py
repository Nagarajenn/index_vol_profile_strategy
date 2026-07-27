from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.models import ClassifiedEvent


class MarketIntelligenceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_recent(self, limit: int, relevant_only: bool = True) -> list[ClassifiedEvent]:
        stmt = select(ClassifiedEvent).options(joinedload(ClassifiedEvent.news_item)).order_by(
            ClassifiedEvent.classified_at.desc()
        ).limit(limit)
        if relevant_only:
            stmt = stmt.where(ClassifiedEvent.is_relevant.is_(True))
        result = await self._session.execute(stmt)
        return list(result.scalars().all())
