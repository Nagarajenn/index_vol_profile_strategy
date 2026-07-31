"""Backend composition for the Live Market Transition Advisor. All the
actual comparison/similarity/scoring logic lives in market_transition/
(shared with the pipeline via the root pyproject.toml editable install,
same pattern as VolumeProfileIntelligenceService) -- this service's job is
purely fetching today's live candles, the stored historical MTI database,
and secondary context (institutional bias, news risk), converting
everything to the plain dataclasses/DataFrames those pure functions expect,
and mapping the result to the API DTO.

Never writes anything -- read-only composition, entirely independent of
the trading decision engine.
"""

from datetime import date, datetime, time, timedelta

import pandas as pd

from app.core.config import settings
from app.exceptions import SymbolNotFoundError
from app.models import MtiDailyTransition, MtiFactorCorrelation, RawCandle
from app.repositories.protocols import (
    CandleRepositoryProtocol,
    LevelsSnapshotRepositoryProtocol,
    MarketTransitionRepositoryProtocol,
)
from app.schemas.market_transition import ContributingFactorDTO, LiveAdvisoryDTO, MostSimilarDayDTO, TransitionTimingEstimateDTO
from app.services.market_intelligence_service import MarketIntelligenceService
from config.instruments import INSTRUMENTS
from market_transition.expiry_calendar import classify_expiry_day
from market_transition.live_advisor import build_live_advisory, build_live_query, determine_transition_stage, find_analogs, is_advisor_active
from market_transition.models import DailyTransitionRecord, FactorCorrelationResult, PreWindowFeatures, TransitionOutcome
from market_transition.scoring import DEFAULT_K

REGIME_HISTORY_LOOKBACK_DAYS = 20
ANALOG_WINDOW_START = time(14, 50)
ANALOG_WINDOW_END = time(15, 10)


def _candles_to_df(rows: list[RawCandle]) -> pd.DataFrame:
    """asyncpg (this service's driver) returns TIMESTAMPTZ columns tagged
    as UTC regardless of the session/column's actual timezone -- unlike
    psycopg (the sync pipeline's driver), which correctly tags them IST.
    The underlying instant is right either way, but market_transition's
    pure functions compare .dt.time against clock constants like 14:00,
    so they need the wall-clock value to actually BE IST, not UTC-labeled.
    Converting here, once, at the ORM->DataFrame boundary, keeps every
    downstream pure function correct without needing IST awareness itself.
    """
    if not rows:
        return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])
    return pd.DataFrame(
        {
            "timestamp": [r.timestamp.astimezone(settings.ist) for r in rows],
            "open": [r.open for r in rows],
            "high": [r.high for r in rows],
            "low": [r.low for r in rows],
            "close": [r.close for r in rows],
            "volume": [r.volume for r in rows],
        }
    )


def _group_by_date(df: pd.DataFrame) -> dict[date, pd.DataFrame]:
    if df.empty:
        return {}
    return {d: g.reset_index(drop=True) for d, g in df.groupby(df["timestamp"].dt.date)}


def _to_pre_window_features(row: MtiDailyTransition) -> PreWindowFeatures:
    return PreWindowFeatures(
        poc_migration_1400_1459=row.poc_migration_1400_1459,
        vwap_distance_1459=row.vwap_distance_1459,
        vwap_distance_1459_pct=row.vwap_distance_1459_pct,
        volume_slope_1400_1459=row.volume_slope_1400_1459,
        realized_range_1400_1459=row.realized_range_1400_1459,
        profile_shape_1459=row.profile_shape_1459,
        rotation_label_1459=row.rotation_label_1459,
        market_regime_1459=row.market_regime_1459,
        is_inside_initial_balance_1459=row.is_inside_initial_balance_1459,
        day_of_week=row.day_of_week,
        expiry_type=row.expiry_type,
        prior_day_profile_shape=row.prior_day_profile_shape,
        prior_day_close_vs_poc=row.prior_day_close_vs_poc,
    )


def _to_transition_outcome(row: MtiDailyTransition) -> TransitionOutcome:
    return TransitionOutcome(
        close_1459=row.close_1459,
        close_1501=row.close_1501,
        market_close=row.market_close,
        transition_move=row.transition_move,
        transition_direction=row.transition_direction,
        post_transition_move=row.post_transition_move,
        outcome=row.outcome,
        outcome_magnitude=row.outcome_magnitude,
    )


def _to_daily_transition_record(row: MtiDailyTransition) -> DailyTransitionRecord:
    return DailyTransitionRecord(
        symbol=row.symbol, session_date=row.session_date, features=_to_pre_window_features(row), outcome=_to_transition_outcome(row)
    )


def _to_factor_correlation_result(row: MtiFactorCorrelation) -> FactorCorrelationResult:
    return FactorCorrelationResult(
        factor_name=row.factor_name,
        factor_type=row.factor_type,
        target=row.target,
        n=row.n_days,
        statistic=row.statistic,
        p_value=row.p_value,
        confidence_label=row.confidence_label,
        direction_note=row.direction_note or "",
        category_breakdown=row.category_breakdown,
    )


def _format_time_str(t) -> str | None:
    if t is None:
        return None
    return t.strftime("%I:%M %p").lstrip("0")


class LiveTransitionAdvisorService:
    def __init__(
        self,
        candle_repo: CandleRepositoryProtocol,
        mti_repo: MarketTransitionRepositoryProtocol,
        levels_repo: LevelsSnapshotRepositoryProtocol,
        market_intelligence_service: MarketIntelligenceService,
    ) -> None:
        self._candle_repo = candle_repo
        self._mti_repo = mti_repo
        self._levels_repo = levels_repo
        self._mi_service = market_intelligence_service

    async def get_live_advisory(self, symbol: str) -> LiveAdvisoryDTO:
        if symbol not in INSTRUMENTS:
            raise SymbolNotFoundError(symbol)

        now = datetime.now(settings.ist)
        today = now.date()
        stage = determine_transition_stage(now.time())

        history_rows = await self._mti_repo.list_daily(symbol, limit=500)
        history = [_to_daily_transition_record(r) for r in history_rows]
        correlation_rows = await self._mti_repo.list_correlations(symbol)
        correlations = [_to_factor_correlation_result(r) for r in correlation_rows]

        lookback_start = datetime.combine(today - timedelta(days=REGIME_HISTORY_LOOKBACK_DAYS), time.min, tzinfo=settings.ist)
        candle_rows = await self._candle_repo.list_since(symbol, lookback_start)
        candles_df = _candles_to_df(candle_rows)
        by_date = _group_by_date(candles_df)
        today_candles = by_date.pop(today, pd.DataFrame(columns=candles_df.columns))
        prior_day_candles = by_date[max(by_date)] if by_date else None
        historical_by_date = by_date

        bin_size = INSTRUMENTS[symbol]["volume_profile_bin_size"]
        expiry_type = classify_expiry_day(symbol, today)

        institutional_bias_label = None
        levels = await self._levels_repo.get_latest(symbol, mode="live")
        if levels is not None:
            institutional_bias_label = levels.institutional_bias_label

        news_risk_score = None
        news_sentiment = None
        try:
            mi_summary = await self._mi_service.get_latest()
            news_risk_score = mi_summary.news_risk_score
            news_sentiment = mi_summary.overall_sentiment
        except Exception:  # noqa: BLE001 -- news context is advisory-only, never block the advisory on it
            pass

        query = build_live_query(symbol, today, today_candles, prior_day_candles, historical_by_date, bin_size, expiry_type, now.time())

        if query is None or not is_advisor_active(now.time()):
            return LiveAdvisoryDTO(
                symbol=symbol, session_date=today, as_of=now, stage=stage, is_active=False,
                historical_similarity_score=0.0, most_similar_days=[], expected_direction="flat",
                probability_continuation=0.5, probability_reversal=0.5, expected_volatility=0.0,
                expected_timing=None, estimated_move=0.0, risk_level="Observe", statistical_confidence="Insufficient data",
                top_contributing_factors=[], institutional_bias_label=institutional_bias_label,
                news_risk_score=news_risk_score, news_sentiment=news_sentiment,
                explanation="The Live Advisor only produces a read between 2:00 PM and 3:01 PM." if query is None
                else "Not enough data yet to produce a reliable read.",
            )

        analogs = find_analogs(query, history, correlations, k=DEFAULT_K)
        analog_candles: dict[date, pd.DataFrame] = {}
        for record, _ in analogs:
            start = datetime.combine(record.session_date, ANALOG_WINDOW_START, tzinfo=settings.ist)
            end = datetime.combine(record.session_date, ANALOG_WINDOW_END, tzinfo=settings.ist)
            rows = await self._candle_repo.list_between(symbol, start, end)
            if rows:
                analog_candles[record.session_date] = _candles_to_df(rows)

        advisory = build_live_advisory(
            query, history, correlations, now, analog_candles=analog_candles,
            institutional_bias_label=institutional_bias_label, news_risk_score=news_risk_score, news_sentiment=news_sentiment,
        )

        return LiveAdvisoryDTO(
            symbol=advisory.symbol,
            session_date=advisory.session_date,
            as_of=advisory.as_of,
            stage=advisory.stage,
            is_active=True,
            historical_similarity_score=advisory.historical_similarity_score,
            most_similar_days=[
                MostSimilarDayDTO(
                    session_date=m.session_date, distance=m.distance, similarity=m.similarity,
                    outcome=m.outcome, transition_direction=m.transition_direction,
                )
                for m in advisory.most_similar_days
            ],
            expected_direction=advisory.expected_direction,
            probability_continuation=advisory.probability_continuation,
            probability_reversal=advisory.probability_reversal,
            expected_volatility=advisory.expected_volatility,
            expected_timing=(
                TransitionTimingEstimateDTO(
                    earliest=_format_time_str(advisory.expected_timing.earliest),
                    latest=_format_time_str(advisory.expected_timing.latest),
                    n_analogs_with_onset=advisory.expected_timing.n_analogs_with_onset,
                    note=advisory.expected_timing.note,
                )
                if advisory.expected_timing
                else None
            ),
            estimated_move=advisory.estimated_move,
            risk_level=advisory.risk_level,
            statistical_confidence=advisory.statistical_confidence,
            top_contributing_factors=[
                ContributingFactorDTO(factor_name=f.factor_name, today_value=f.today_value, note=f.note, contribution=f.contribution)
                for f in advisory.top_contributing_factors
            ],
            institutional_bias_label=advisory.institutional_bias_label,
            news_risk_score=advisory.news_risk_score,
            news_sentiment=advisory.news_sentiment,
            explanation=advisory.explanation,
        )
