import json
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


def _normalize(row: dict) -> dict:
    """Raw text() queries don't apply JSONB decoding the way a typed ORM
    column would -- normalize the one JSONB column by hand rather than
    declaring a full 83-column ORM model that would just re-transcribe
    quant_features/models.py's field list a third time (db/schema.sql,
    db/writer.py's column derivation, and this would be the third)."""
    flags = row.get("data_quality_flags")
    if isinstance(flags, str):
        row["data_quality_flags"] = json.loads(flags)
    return row


class QuantFeatureRepository:
    """Thin, read-only access to quant_market_features -- deliberately not
    a full SQLAlchemy ORM repository (see _normalize's docstring). No
    business logic here beyond query construction, same rule every other
    repository in this backend follows.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_latest_market_features(self, symbol: str) -> dict | None:
        result = await self._session.execute(
            text("SELECT * FROM quant_market_features WHERE symbol = :symbol ORDER BY timestamp DESC LIMIT 1"),
            {"symbol": symbol},
        )
        row = result.mappings().first()
        return _normalize(dict(row)) if row else None

    async def list_market_features(self, symbol: str, start: datetime, end: datetime) -> list[dict]:
        result = await self._session.execute(
            text(
                "SELECT * FROM quant_market_features "
                "WHERE symbol = :symbol AND timestamp >= :start AND timestamp <= :end "
                "ORDER BY timestamp"
            ),
            {"symbol": symbol, "start": start, "end": end},
        )
        return [_normalize(dict(r)) for r in result.mappings().all()]
