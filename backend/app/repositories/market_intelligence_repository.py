from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import contains_eager

from app.models import ClassifiedEvent, NewsItem


class MarketIntelligenceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_recent(
        self, limit: int, relevant_only: bool = True, published_since: datetime | None = None
    ) -> list[ClassifiedEvent]:
        # Ordered by when the news happened (published_at), not when the AI
        # got around to classifying it (classified_at) -- a backfill run can
        # classify a week-old item today, and it must not jump to the top.
        stmt = (
            select(ClassifiedEvent)
            .join(NewsItem, ClassifiedEvent.news_item_id == NewsItem.id)
            .options(contains_eager(ClassifiedEvent.news_item))
            .order_by(NewsItem.published_at.desc())
            .limit(limit)
        )
        if relevant_only:
            stmt = stmt.where(ClassifiedEvent.is_relevant.is_(True))
        if published_since is not None:
            stmt = stmt.where(NewsItem.published_at >= published_since)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())
