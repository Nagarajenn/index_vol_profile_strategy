from datetime import date, datetime, time, timedelta

import pandas as pd

from analytics.resample import resample_to_interval
from app.core.config import settings
from app.exceptions import NoDataAvailableError, SymbolNotFoundError
from app.models import LevelsSnapshot, OptionChainSummary, RawCandle
from app.repositories.protocols import (
    CandleRepositoryProtocol,
    LevelsSnapshotRepositoryProtocol,
    OptionChainRepositoryProtocol,
)
from app.schemas.candle import CandleDTO
from app.schemas.dashboard import DashboardResponseDTO, LevelsSummaryDTO
from app.schemas.levels_detail import BreakoutBoxDTO, LevelsDetailDTO, SwingPointDTO, TrendlineDTO
from app.schemas.option_chain import OptionChainSummaryDTO
from app.services.interpretation import build_interpretation
from config.instruments import INSTRUMENTS

CHART_RESAMPLE_MINUTES = 5
# How far back to look for "the previous session" -- wide enough to cross a
# weekend or a short holiday cluster, trimmed down to exactly one prior
# session's worth of candles in _trim_to_prev_and_current_session below.
PREVIOUS_SESSION_LOOKBACK_DAYS = 6


class DashboardService:
    """Owns every 'what does this mean' decision for the dashboard: symbol
    validity, staleness/no-data status, market-hours framing, and resampling
    raw 1-min candles into the chart's 5-min bars. Repositories below it are
    query-only; this is where that logic actually lives (see backend/README
    and the Phase 3 plan's Repository/Service rule).
    """

    def __init__(
        self,
        levels_repo: LevelsSnapshotRepositoryProtocol,
        candle_repo: CandleRepositoryProtocol,
        option_chain_repo: OptionChainRepositoryProtocol,
    ) -> None:
        self._levels_repo = levels_repo
        self._candle_repo = candle_repo
        self._option_chain_repo = option_chain_repo

    async def get_latest(self, symbol: str) -> DashboardResponseDTO:
        if symbol not in INSTRUMENTS:
            raise SymbolNotFoundError(symbol)

        now = datetime.now(settings.ist)
        is_market_hours = self._is_market_hours(now)

        levels_row = await self._levels_repo.get_latest(symbol, mode="live")
        if levels_row is None:
            return DashboardResponseDTO(
                symbol=symbol,
                status="no_data",
                as_of=None,
                staleness_seconds=None,
                is_market_hours=is_market_hours,
                levels=None,
                candles=[],
                option_chain=None,
            )

        staleness_seconds = (now - levels_row.as_of).total_seconds()
        stale_threshold_seconds = 2 * settings.live_loop_interval_min * 60
        status = "stale" if staleness_seconds > stale_threshold_seconds else "live"

        today = levels_row.as_of.date()
        lookback_start = datetime.combine(
            today - timedelta(days=PREVIOUS_SESSION_LOOKBACK_DAYS), time.min, tzinfo=settings.ist
        )
        candle_rows = await self._candle_repo.list_since(symbol, lookback_start)
        candle_rows = self._trim_to_prev_and_current_session(candle_rows, today)
        option_chain_row = await self._option_chain_repo.get_latest_summary(symbol)

        return DashboardResponseDTO(
            symbol=symbol,
            status=status,
            as_of=levels_row.as_of,
            staleness_seconds=staleness_seconds,
            is_market_hours=is_market_hours,
            levels=self._to_levels_summary(levels_row),
            candles=self._resample_candles(candle_rows),
            option_chain=self._to_option_chain_summary(option_chain_row) if option_chain_row else None,
        )

    async def get_latest_detail(self, symbol: str) -> LevelsDetailDTO:
        """Everything in get_latest()'s levels summary plus the JSONB detail
        arrays -- reserved for v1.1's overlay rendering, not called by any
        V1 screen yet (see backend/app/schemas/levels_detail.py).
        """
        if symbol not in INSTRUMENTS:
            raise SymbolNotFoundError(symbol)

        row = await self._levels_repo.get_latest(symbol, mode="live")
        if row is None:
            raise NoDataAvailableError(symbol)

        return LevelsDetailDTO(
            **self._to_levels_summary(row).model_dump(),
            today_vp_bins=row.today_vp_bins,
            swings=[SwingPointDTO(**s) for s in (row.swings or [])],
            trendlines=[TrendlineDTO(**t) for t in (row.trendlines or [])],
            breakout_boxes=[BreakoutBoxDTO(**b) for b in (row.breakout_boxes or [])],
        )

    @staticmethod
    def _is_market_hours(now: datetime) -> bool:
        open_t = datetime.strptime(settings.session_open, "%H:%M").time()
        close_t = datetime.strptime(settings.session_close, "%H:%M").time()
        return now.weekday() < 5 and open_t <= now.time() <= close_t

    @staticmethod
    def _trim_to_prev_and_current_session(rows: list[RawCandle], today: date) -> list[RawCandle]:
        """Keep only today's candles plus the single most recent prior
        session that actually has data -- so the chart shows yesterday's
        session in continuation with today's live one, without needing a
        holiday calendar here: whatever the most recent date with candles
        before today is, that's "the previous session", weekend/holiday
        gaps included automatically.
        """
        prior_dates = {r.timestamp.date() for r in rows if r.timestamp.date() < today}
        if not prior_dates:
            return [r for r in rows if r.timestamp.date() == today]
        prev_session_date = max(prior_dates)
        return [r for r in rows if r.timestamp.date() in (prev_session_date, today)]

    @staticmethod
    def _resample_candles(candle_rows: list[RawCandle]) -> list[CandleDTO]:
        if not candle_rows:
            return []
        df = pd.DataFrame(
            {
                "timestamp": [c.timestamp for c in candle_rows],
                "open": [c.open for c in candle_rows],
                "high": [c.high for c in candle_rows],
                "low": [c.low for c in candle_rows],
                "close": [c.close for c in candle_rows],
                "volume": [c.volume for c in candle_rows],
            }
        )
        resampled = resample_to_interval(df, CHART_RESAMPLE_MINUTES)
        return [
            CandleDTO(
                timestamp=row.timestamp, open=row.open, high=row.high, low=row.low, close=row.close, volume=row.volume
            )
            for row in resampled.itertuples(index=False)
        ]

    @staticmethod
    def _to_levels_summary(row: LevelsSnapshot) -> LevelsSummaryDTO:
        return LevelsSummaryDTO(
            close=row.close,
            vwap_now=row.vwap_now,
            today_poc=row.today_poc,
            today_vah=row.today_vah,
            today_val=row.today_val,
            support_low=row.support_low,
            support_high=row.support_high,
            resistance_low=row.resistance_low,
            resistance_high=row.resistance_high,
            trend_label=row.trend_label,
            trend_score=row.trend_score,
            institutional_bias_label=row.institutional_bias_label,
            confidence_score=row.confidence_score,
            action_text=row.action_text,
            interpretation=build_interpretation(row),
        )

    @staticmethod
    def _to_option_chain_summary(row: OptionChainSummary) -> OptionChainSummaryDTO:
        return OptionChainSummaryDTO(
            pcr=row.pcr, atm_strike=row.atm_strike, atm_iv_call=row.atm_iv_call, atm_iv_put=row.atm_iv_put
        )
