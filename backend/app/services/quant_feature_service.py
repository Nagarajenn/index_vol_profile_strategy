from datetime import datetime

from app.exceptions import NoDataAvailableError, SymbolNotFoundError
from app.repositories.quant_feature_repository import QuantFeatureRepository
from config.instruments import INSTRUMENTS


class QuantFeatureService:
    """Thin read-through over the already-computed quant_market_features
    table -- unlike VolumeIntelligenceService/VolumeProfileIntelligenceService,
    there is no live computation here: the whole point of the feature store
    is that rows are precomputed once by the batch backfill / live loop
    (quant_features/), not recomputed per request."""

    def __init__(self, repo: QuantFeatureRepository) -> None:
        self._repo = repo

    async def get_latest(self, symbol: str) -> dict:
        if symbol not in INSTRUMENTS:
            raise SymbolNotFoundError(symbol)
        row = await self._repo.get_latest_market_features(symbol)
        if row is None:
            raise NoDataAvailableError(symbol)
        return row

    async def get_history(self, symbol: str, start: datetime, end: datetime) -> list[dict]:
        if symbol not in INSTRUMENTS:
            raise SymbolNotFoundError(symbol)
        return await self._repo.list_market_features(symbol, start, end)
