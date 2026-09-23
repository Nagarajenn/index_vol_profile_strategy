"""Read-only queries for the 12C scalping decision panel (levels context).

Query construction only -- no business logic, no writes. Option snapshots, candles and
paper positions come from OptionRiskRepository, which already reads exactly that window.
"""

from datetime import datetime

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import LevelsSnapshot
from position_sim_12c.history import COLUMNS as SIM_COLUMNS


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

    async def simulated_positions(self, symbol: str, session_date=None, limit: int = 200) -> list[dict]:
        """Closed hypothetical 12C positions from sim12c_positions (written by
        scripts/run_12c_position_history.py). Read-only, and simulation only: these are not orders
        and not paper-account trades."""
        cols = ", ".join(SIM_COLUMNS)
        where = ["symbol = :symbol"] + (["session_date = :d"] if session_date else [])
        sql = text(f"SELECT {cols} FROM sim12c_positions WHERE {' AND '.join(where)} "
                   f"ORDER BY session_date DESC, signal_minute DESC LIMIT :limit")
        args = dict(symbol=symbol, limit=limit)
        if session_date:
            args["d"] = session_date
        rows = (await self._session.execute(sql, args)).fetchall()
        return [dict(zip(SIM_COLUMNS, r)) for r in rows]
