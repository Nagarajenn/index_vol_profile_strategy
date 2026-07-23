from datetime import datetime, time, timedelta

import pandas as pd

from analytics.volume_profile_intelligence import (
    VolumeProfileIntelligence,
    compute_volume_profile_intelligence,
)
from app.core.config import settings
from app.exceptions import NoDataAvailableError, SymbolNotFoundError
from app.models import RawCandle
from app.repositories.protocols import CandleRepositoryProtocol
from app.schemas.volume_profile_intelligence import (
    DevelopingPointDTO,
    InitialBalanceDTO,
    LevelTestDTO,
    OpeningTypeDTO,
    ProfileShapeDTO,
    RotationFactorDTO,
    ValueMigrationDTO,
    VolumeNodeDTO,
    VolumePaceDTO,
    VolumeProfileIntelligenceDTO,
)
from config.instruments import INSTRUMENTS

# Wide enough window to give the volume-pace reference curve a handful of
# prior trading days even across a weekend/short holiday cluster.
HISTORY_LOOKBACK_DAYS = 10


class VolumeProfileIntelligenceService:
    """Computes advanced volume-profile metrics (analytics/volume_profile_intelligence.py)
    fresh from raw_candles on every request -- no pipeline or schema changes,
    no dependency on anything the strategy engine writes. Owns the "which
    candles count as today vs. history" and DataFrame-shaping decisions;
    the actual metric math lives in the shared analytics module.
    """

    def __init__(self, candle_repo: CandleRepositoryProtocol) -> None:
        self._candle_repo = candle_repo

    async def get_latest(self, symbol: str) -> VolumeProfileIntelligenceDTO:
        if symbol not in INSTRUMENTS:
            raise SymbolNotFoundError(symbol)

        now = datetime.now(settings.ist)
        lookback_start = datetime.combine(now.date() - timedelta(days=HISTORY_LOOKBACK_DAYS), time.min, tzinfo=settings.ist)
        rows = await self._candle_repo.list_since(symbol, lookback_start)
        if not rows:
            raise NoDataAvailableError(symbol)

        by_date = self._group_by_date(rows)
        today = max(by_date)
        today_df = by_date.pop(today)

        bin_size = INSTRUMENTS[symbol]["volume_profile_bin_size"]
        result = compute_volume_profile_intelligence(today_df, by_date, bin_size)

        as_of = today_df["timestamp"].iloc[-1] if not today_df.empty else None
        return self._to_dto(symbol, as_of, result)

    @staticmethod
    def _group_by_date(rows: list[RawCandle]) -> dict:
        by_date: dict = {}
        for r in rows:
            by_date.setdefault(r.timestamp.date(), []).append(r)
        return {
            d: pd.DataFrame(
                {
                    "timestamp": [r.timestamp for r in day_rows],
                    "open": [r.open for r in day_rows],
                    "high": [r.high for r in day_rows],
                    "low": [r.low for r in day_rows],
                    "close": [r.close for r in day_rows],
                    "volume": [r.volume for r in day_rows],
                }
            )
            for d, day_rows in by_date.items()
        }

    @staticmethod
    def _to_dto(symbol: str, as_of: datetime | None, result: VolumeProfileIntelligence) -> VolumeProfileIntelligenceDTO:
        return VolumeProfileIntelligenceDTO(
            symbol=symbol,
            as_of=as_of,
            developing=[DevelopingPointDTO(**vars(p)) for p in result.developing],
            hvns=[VolumeNodeDTO(**vars(n)) for n in result.hvns],
            lvns=[VolumeNodeDTO(**vars(n)) for n in result.lvns],
            migration=ValueMigrationDTO(**vars(result.migration)) if result.migration else None,
            level_tests=[LevelTestDTO(**vars(t)) for t in result.level_tests],
            profile_shape=ProfileShapeDTO(**vars(result.profile_shape)) if result.profile_shape else None,
            initial_balance=InitialBalanceDTO(**vars(result.initial_balance)) if result.initial_balance else None,
            opening_type=OpeningTypeDTO(**vars(result.opening_type)) if result.opening_type else None,
            rotation_factor=RotationFactorDTO(**vars(result.rotation_factor)) if result.rotation_factor else None,
            volume_pace=VolumePaceDTO(**vars(result.volume_pace)) if result.volume_pace else None,
        )
