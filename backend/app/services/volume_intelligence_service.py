from datetime import date, datetime, time, timedelta

import pandas as pd

from analytics.volume_intelligence.engine import compute_volume_intelligence
from analytics.volume_intelligence.models import VolumeIntelligence
from app.core.config import settings
from app.exceptions import NoDataAvailableError, SymbolNotFoundError
from app.models import RawCandle
from app.repositories.protocols import CandleRepositoryProtocol
from app.schemas.volume_intelligence import (
    AbsorptionSignalDTO,
    BuySellDominanceDTO,
    CumulativePressureDTO,
    DailyVolumeComparisonDTO,
    DailyVolumeTrendDTO,
    ExhaustionSignalDTO,
    HistoricalSimilarityDTO,
    InstitutionalParticipationDTO,
    NextIntervalForecastDTO,
    RvolBaselineResultDTO,
    RvolReadingDTO,
    SignificantIntervalDTO,
    SimilarDayDTO,
    VolumeAccelerationDTO,
    VolumeCharacterDTO,
    VolumeDryUpDTO,
    VolumeIntelligenceDTO,
    VolumeMomentumDTO,
    VolumeNarrativeDTO,
    VolumeSpikeDTO,
    VolumeTrendDTO,
)
from config.instruments import INSTRUMENTS
from market_transition.expiry_calendar import build_expiry_calendar

# Full BACKFILL_LOOKBACK_DAYS ceiling -- multi-baseline grouping (especially
# monthly_expiry_day, which occurs only ~2-3 times per 60 trading days)
# needs the maximum available history, unlike VolumeProfileIntelligenceService's
# 10-day window.
HISTORY_LOOKBACK_DAYS = 60


class VolumeIntelligenceService:
    """Computes the Volume Intelligence Engine (analytics/volume_intelligence/)
    fresh from raw_candles on every request -- no pipeline or schema
    changes, no new DB tables, no dependency on anything the strategy
    engine writes. Mirrors VolumeProfileIntelligenceService's pattern
    exactly (same live-compute-only architecture, no caching)."""

    def __init__(self, candle_repo: CandleRepositoryProtocol) -> None:
        self._candle_repo = candle_repo

    async def get_latest(self, symbol: str) -> VolumeIntelligenceDTO:
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

        calendar = build_expiry_calendar(symbol, min(by_date), today) if by_date else None
        result = compute_volume_intelligence(symbol, today_df, by_date, calendar)

        return self._to_dto(result)

    @staticmethod
    def _group_by_date(rows: list[RawCandle]) -> dict[date, pd.DataFrame]:
        by_date: dict[date, list[RawCandle]] = {}
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
    def _to_dto(result: VolumeIntelligence) -> VolumeIntelligenceDTO:
        return VolumeIntelligenceDTO(
            symbol=result.symbol,
            as_of=result.as_of,
            rvol=RvolReadingDTO(
                by_baseline={k: RvolBaselineResultDTO(**vars(v)) for k, v in result.rvol.by_baseline.items()},
                primary=RvolBaselineResultDTO(**vars(result.rvol.primary)) if result.rvol.primary else None,
            )
            if result.rvol
            else None,
            acceleration=VolumeAccelerationDTO(**vars(result.acceleration)) if result.acceleration else None,
            dominance=BuySellDominanceDTO(**vars(result.dominance)) if result.dominance else None,
            cumulative_pressure=CumulativePressureDTO(**vars(result.cumulative_pressure)) if result.cumulative_pressure else None,
            momentum=VolumeMomentumDTO(**vars(result.momentum)) if result.momentum else None,
            institutional=InstitutionalParticipationDTO(**vars(result.institutional)) if result.institutional else None,
            spike=VolumeSpikeDTO(**vars(result.spike)) if result.spike else None,
            dryup=VolumeDryUpDTO(**vars(result.dryup)) if result.dryup else None,
            absorption=AbsorptionSignalDTO(**vars(result.absorption)) if result.absorption else None,
            exhaustion=ExhaustionSignalDTO(**vars(result.exhaustion)) if result.exhaustion else None,
            trend=VolumeTrendDTO(**vars(result.trend)) if result.trend else None,
            character=VolumeCharacterDTO(**vars(result.character)) if result.character else None,
            similarity=HistoricalSimilarityDTO(
                top_days=[SimilarDayDTO(**vars(d)) for d in result.similarity.top_days],
                resemblance_label=result.similarity.resemblance_label,
                n_days_compared=result.similarity.n_days_compared,
            )
            if result.similarity
            else None,
            forecast=NextIntervalForecastDTO(**vars(result.forecast)) if result.forecast else None,
            narrative=VolumeNarrativeDTO(**vars(result.narrative)) if result.narrative else None,
            daily_volume_trend=DailyVolumeTrendDTO(
                elapsed_minutes=result.daily_volume_trend.elapsed_minutes,
                days=[DailyVolumeComparisonDTO(**vars(d)) for d in result.daily_volume_trend.days],
            )
            if result.daily_volume_trend
            else None,
            significant_intervals=[SignificantIntervalDTO(**vars(i)) for i in result.significant_intervals],
        )
