"""Read-only queries over the paper-trading tables.

Query construction only -- no business logic, matching the repository
convention used across this backend. The paper engine is the sole writer;
nothing here mutates.
"""

from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import PaperAccountSnapshot, PaperDecision, PaperPosition, PaperPositionEvent, PaperSession


class PaperTradingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_decisions(self, session_date: date | None = None, limit: int = 100) -> list[PaperDecision]:
        stmt = select(PaperDecision)
        if session_date is not None:
            stmt = stmt.where(PaperDecision.session_date == session_date)
        stmt = stmt.order_by(PaperDecision.session_date.desc(), PaperDecision.symbol).limit(limit)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_positions(self, session_date: date | None = None, limit: int = 100) -> list[PaperPosition]:
        stmt = select(PaperPosition)
        if session_date is not None:
            stmt = stmt.where(PaperPosition.session_date == session_date)
        stmt = stmt.order_by(PaperPosition.entry_timestamp.desc()).limit(limit)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_open_position(self) -> PaperPosition | None:
        stmt = (
            select(PaperPosition)
            .where(PaperPosition.is_open.is_(True))
            .order_by(PaperPosition.entry_timestamp.desc())
            .limit(1)
        )
        result = await self._session.execute(stmt)
        return result.scalars().first()

    async def list_events(self, position_id: int) -> list[PaperPositionEvent]:
        stmt = (
            select(PaperPositionEvent)
            .where(PaperPositionEvent.position_id == position_id)
            .order_by(PaperPositionEvent.event_timestamp)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_latest_account(self) -> PaperAccountSnapshot | None:
        stmt = select(PaperAccountSnapshot).order_by(PaperAccountSnapshot.session_date.desc()).limit(1)
        result = await self._session.execute(stmt)
        return result.scalars().first()

    async def get_session(self, session_date: date) -> PaperSession | None:
        stmt = select(PaperSession).where(PaperSession.session_date == session_date).limit(1)
        result = await self._session.execute(stmt)
        return result.scalars().first()

    async def list_session_dates(self, limit: int = 30) -> list[date]:
        stmt = select(PaperSession.session_date).order_by(PaperSession.session_date).limit(limit)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_closed_positions(self, limit: int = 200) -> list[PaperPosition]:
        stmt = (
            select(PaperPosition)
            .where(PaperPosition.is_open.is_(False))
            .order_by(PaperPosition.exit_timestamp.desc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())
