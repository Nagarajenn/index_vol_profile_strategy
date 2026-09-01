from datetime import datetime, time

import pandas as pd

from analytics.session_amd import SessionAmdPhases, compute_session_amd_phases
from app.core.config import settings
from app.exceptions import NoDataAvailableError, SymbolNotFoundError
from app.models import RawCandle
from app.repositories.protocols import CandleRepositoryProtocol
from app.schemas.session_amd import (
    AccumulationRangeDTO,
    DistributionPhaseDTO,
    ManipulationSweepDTO,
    SessionAmdDTO,
)
from config.instruments import INSTRUMENTS


class SessionAmdService:
    """Computes the Session AMD (Accumulation/Manipulation/Distribution)
    structure engine (analytics/session_amd.py) fresh from raw_candles on
    every request -- no pipeline or schema changes, no new DB table.
    Mirrors VolumeIntelligenceService's live-compute-only pattern, but
    only ever needs TODAY's candles (this is a same-session analysis, no
    multi-day history/baseline needed)."""

    def __init__(self, candle_repo: CandleRepositoryProtocol) -> None:
        self._candle_repo = candle_repo

    async def get_latest(self, symbol: str) -> SessionAmdDTO:
        if symbol not in INSTRUMENTS:
            raise SymbolNotFoundError(symbol)

        now = datetime.now(settings.ist)
        start_of_today = datetime.combine(now.date(), time.min, tzinfo=settings.ist)
        rows = await self._candle_repo.list_since(symbol, start_of_today)
        if not rows:
            raise NoDataAvailableError(symbol)

        today_df = self._to_dataframe(rows)
        result = compute_session_amd_phases(symbol, today_df)
        return self._to_dto(result)

    @staticmethod
    def _to_dataframe(rows: list[RawCandle]) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "timestamp": [r.timestamp for r in rows],
                "open": [r.open for r in rows],
                "high": [r.high for r in rows],
                "low": [r.low for r in rows],
                "close": [r.close for r in rows],
                "volume": [r.volume for r in rows],
            }
        ).sort_values("timestamp").reset_index(drop=True)

    @staticmethod
    def _to_dto(result: SessionAmdPhases) -> SessionAmdDTO:
        return SessionAmdDTO(
            symbol=result.symbol,
            as_of=result.as_of,
            accumulation=AccumulationRangeDTO(**vars(result.accumulation)) if result.accumulation else None,
            sweeps=[ManipulationSweepDTO(**vars(s)) for s in result.sweeps],
            latest_sweep=ManipulationSweepDTO(**vars(result.latest_sweep)) if result.latest_sweep else None,
            distribution=DistributionPhaseDTO(**vars(result.distribution)) if result.distribution else None,
            current_phase=result.current_phase,
            narrative=result.narrative,
        )
