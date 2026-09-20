"""Read-only queries for the 12B option risk & closing-state view.

Query construction only -- no business logic, no writes. Reads option_chain_raw,
raw_candles and paper_positions for one symbol-day's 14:50-15:40 IST window.
"""

from datetime import date, datetime, time

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import OptionChainRaw, PaperPosition, RawCandle


class OptionRiskRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def latest_session_date(self, symbol: str) -> date | None:
        stmt = select(func.max(OptionChainRaw.fetched_at)).where(OptionChainRaw.symbol == symbol)
        ts = (await self._session.execute(stmt)).scalar()
        return ts.date() if ts is not None else None

    async def list_snapshots(self, symbol: str, start: datetime, end: datetime) -> list[OptionChainRaw]:
        stmt = (select(OptionChainRaw).where(OptionChainRaw.symbol == symbol, OptionChainRaw.fetched_at >= start,
                                             OptionChainRaw.fetched_at < end).order_by(OptionChainRaw.fetched_at))
        return list((await self._session.execute(stmt)).scalars().all())

    async def list_candles(self, symbol: str, start: datetime, end: datetime) -> list[RawCandle]:
        stmt = (select(RawCandle).where(RawCandle.symbol == symbol, RawCandle.timestamp >= start, RawCandle.timestamp < end)
                .order_by(RawCandle.timestamp))
        return list((await self._session.execute(stmt)).scalars().all())

    async def list_positions(self, symbol: str, session_date: date) -> list[PaperPosition]:
        stmt = (select(PaperPosition).where(PaperPosition.symbol == symbol, PaperPosition.session_date == session_date)
                .order_by(PaperPosition.entry_timestamp))
        return list((await self._session.execute(stmt)).scalars().all())
