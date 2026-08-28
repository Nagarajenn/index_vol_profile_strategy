from datetime import date

from app.models import (
    CasCohortCategorical,
    CasCohortFeatureStat,
    CasDailyTransition,
    CasPostTransitionMinute,
    CasPretransitionWindow,
    CasTransitionForecast,
    MtiDailyTransition,
    MtiFactorCorrelation,
)
from app.repositories.protocols import MarketTransitionRepositoryProtocol
from app.schemas.market_transition import (
    CasCohortAnalysisResponseDTO,
    CasDailyResultDTO,
    CasIntelligenceResponseDTO,
    CasWindowedDetailResponseDTO,
    CohortCategoricalDTO,
    CohortFeatureStatDTO,
    CohortResultDTO,
    ContributingFactorDTO,
    MtiDailyResultDTO,
    MtiFactorCorrelationDTO,
    MtiResearchResponseDTO,
    PostTransitionMinuteDTO,
    PreTransitionWindowDTO,
    TransitionForecastDTO,
)

_COHORT_ORDER = [
    "FLAT_LARGE_UP", "FLAT_LARGE_DOWN", "UP_REVERSAL_DOWN", "DOWN_REVERSAL_UP",
    "UP_CONTINUATION", "DOWN_CONTINUATION", "FLAT_NO_MATERIAL_MOVE",
]


class MarketTransitionService:
    """Read-only assembly of the Market Transition Intelligence research
    view. All the actual statistical work happens offline in
    market_transition/ (run via scripts/run_market_transition_research.py)
    -- this service just fetches the persisted results and maps them to
    DTOs, entirely independent of the trading decision engine.
    """

    def __init__(self, repo: MarketTransitionRepositoryProtocol) -> None:
        self._repo = repo

    async def get_research(self, symbol: str, limit: int = 200) -> MtiResearchResponseDTO:
        daily_rows = await self._repo.list_daily(symbol, limit)
        correlation_rows = await self._repo.list_correlations(symbol)

        correlations = [self._to_correlation_dto(r) for r in correlation_rows]
        correlations.sort(key=lambda c: (c.p_value is None, c.p_value if c.p_value is not None else 1.0))

        daily_results = [self._to_daily_dto(r) for r in daily_rows]

        gradable = [d.forecast_correct for d in daily_results if d.forecast_correct is not None]
        hit_count = sum(1 for correct in gradable if correct)
        evaluable = len(gradable)

        return MtiResearchResponseDTO(
            symbol=symbol,
            total_days_analyzed=len(daily_results),
            correlations=correlations,
            daily_results=daily_results,
            forecast_evaluable_days=evaluable,
            forecast_hit_count=hit_count,
            forecast_accuracy_pct=round(hit_count / evaluable * 100, 1) if evaluable else None,
        )

    @staticmethod
    def _to_correlation_dto(row: MtiFactorCorrelation | CasFactorCorrelation) -> MtiFactorCorrelationDTO:
        return MtiFactorCorrelationDTO(
            factor_name=row.factor_name,
            factor_type=row.factor_type,
            target=row.target,
            n_days=row.n_days,
            statistic=row.statistic,
            p_value=row.p_value,
            confidence_label=row.confidence_label,
            direction_note=row.direction_note,
            category_breakdown=row.category_breakdown,
        )

    @staticmethod
    def _to_daily_dto(row: MtiDailyTransition) -> MtiDailyResultDTO:
        factors = [ContributingFactorDTO(**f) for f in (row.top_contributing_factors or [])]
        predicted_outcome = MarketTransitionService._predicted_outcome(row.probability_reversal, row.probability_continuation)
        forecast_correct = MarketTransitionService._forecast_correct(predicted_outcome, row.outcome)
        return MtiDailyResultDTO(
            session_date=row.session_date,
            profile_shape_1459=row.profile_shape_1459,
            market_regime_1459=row.market_regime_1459,
            expiry_type=row.expiry_type,
            transition_direction=row.transition_direction,
            transition_move=row.transition_move,
            post_transition_move=row.post_transition_move,
            outcome=row.outcome,
            outcome_magnitude=row.outcome_magnitude,
            transition_risk_score=row.transition_risk_score,
            probability_continuation=row.probability_continuation,
            probability_reversal=row.probability_reversal,
            expected_volatility=row.expected_volatility,
            expected_direction=row.expected_direction,
            historical_similarity_score=row.historical_similarity_score,
            top_contributing_factors=factors,
            statistical_confidence=row.statistical_confidence,
            explanation=row.explanation,
            computed_at=row.computed_at,
            predicted_outcome=predicted_outcome,
            forecast_correct=forecast_correct,
        )

    async def get_cas_intelligence(self, symbol: str, limit: int = 60) -> CasIntelligenceResponseDTO:
        rows = await self._repo.list_cas_daily(symbol, limit)
        daily_results = [self._to_cas_dto(r) for r in rows]

        comparable = [d for d in daily_results if d.old_methodology_outcome is not None]
        agreement_count = sum(1 for d in comparable if d.conclusion == d.old_methodology_outcome)

        correlation_rows = await self._repo.list_cas_correlations(symbol)
        correlations = [self._to_correlation_dto(r) for r in correlation_rows]
        correlations.sort(key=lambda c: (c.p_value is None, c.p_value if c.p_value is not None else 1.0))

        return CasIntelligenceResponseDTO(
            symbol=symbol,
            total_days_analyzed=len(daily_results),
            agreement_count=agreement_count,
            agreement_pct=round(agreement_count / len(comparable) * 100, 1) if comparable else None,
            daily_results=daily_results,
            correlations=correlations,
        )

    @staticmethod
    def _to_cas_dto(row: CasDailyTransition) -> CasDailyResultDTO:
        return CasDailyResultDTO(
            session_date=row.session_date,
            close_1431=row.close_1431,
            close_1459=row.close_1459,
            close_1539=row.close_1539,
            pre_direction=row.pre_direction,
            post_direction=row.post_direction,
            conclusion=row.conclusion,
            outcome_magnitude=row.outcome_magnitude,
            pre_window_volume=row.pre_window_volume,
            post_window_pre_auction_volume=row.post_window_pre_auction_volume,
            volume_ratio=row.volume_ratio,
            pre_window_points_move=row.pre_window_points_move,
            post_window_points_move=row.post_window_points_move,
            pcr_1459=row.pcr_1459,
            institutional_bias_label_1459=row.institutional_bias_label_1459,
            institutional_bias_score_1459=row.institutional_bias_score_1459,
            expiry_type=row.expiry_type,
            day_of_week=row.day_of_week,
            old_methodology_outcome=row.old_methodology_outcome,
            old_methodology_outcome_magnitude=row.old_methodology_outcome_magnitude,
            data_quality_flag=row.data_quality_flag,
            transition_type=row.transition_type,
            magnitude_pct_return=row.magnitude_pct_return,
            magnitude_atr_normalized=row.magnitude_atr_normalized,
            magnitude_tier=row.magnitude_tier,
            computed_at=row.computed_at,
        )

    async def get_cas_windowed_detail(self, symbol: str, session_date: date) -> CasWindowedDetailResponseDTO:
        """Phase 7B: lazy-loaded per-day detail -- pre_transition_windows is
        FORECAST INFORMATION (14:30-14:59), post_transition_minutes is
        ACTUAL OUTCOME (15:00-15:15). Never merged/compared server-side --
        the caller (UI) is responsible for keeping the two visually
        separate, per the explicit design requirement."""
        window_rows = await self._repo.list_pretransition_windows(symbol, session_date)
        minute_rows = await self._repo.list_post_transition_minutes(symbol, session_date)
        forecast_rows = await self._repo.list_transition_forecasts(symbol, session_date)

        return CasWindowedDetailResponseDTO(
            symbol=symbol,
            session_date=session_date,
            pre_transition_windows=[self._to_pretransition_window_dto(r) for r in window_rows],
            post_transition_minutes=[self._to_post_transition_minute_dto(r) for r in minute_rows],
            forecasts=[self._to_forecast_dto(r) for r in forecast_rows],
        )

    async def get_cas_cohort_analysis(self, symbol: str) -> CasCohortAnalysisResponseDTO:
        """Phase 7C: cohort-vs-rest pre-3pm feature comparison, grouped
        server-side by cohort (not a flat row list the frontend has to
        re-group). Every one of the 7 named cohorts is always present in
        the response, even with n_days=0 and every feature "Insufficient
        data" -- an absent cohort is a UI implementation detail this
        service never introduces; a genuinely-empty cohort is itself
        useful information (e.g. no LARGE/EXTREME days have occurred yet)."""
        feature_rows = await self._repo.list_cohort_feature_stats(symbol)
        categorical_rows = await self._repo.list_cohort_categorical(symbol)

        features_by_cohort: dict[str, list[CohortFeatureStatDTO]] = {c: [] for c in _COHORT_ORDER}
        n_days_by_cohort: dict[str, int] = {c: 0 for c in _COHORT_ORDER}
        for row in feature_rows:
            features_by_cohort.setdefault(row.cohort, []).append(self._to_cohort_feature_dto(row))
            n_days_by_cohort[row.cohort] = max(n_days_by_cohort.get(row.cohort, 0), row.n)

        categorical_by_cohort: dict[str, list[CohortCategoricalDTO]] = {c: [] for c in _COHORT_ORDER}
        for row in categorical_rows:
            categorical_by_cohort.setdefault(row.cohort, []).append(self._to_cohort_categorical_dto(row))

        cohorts = [
            CohortResultDTO(
                cohort=cohort,
                n_days=n_days_by_cohort.get(cohort, 0),
                features=features_by_cohort.get(cohort, []),
                categorical=categorical_by_cohort.get(cohort, []),
            )
            for cohort in _COHORT_ORDER
        ]
        return CasCohortAnalysisResponseDTO(symbol=symbol, cohorts=cohorts)

    @staticmethod
    def _to_cohort_feature_dto(row: CasCohortFeatureStat) -> CohortFeatureStatDTO:
        return CohortFeatureStatDTO(
            feature_name=row.feature_name, n=row.n, median=row.median, mean=row.mean,
            percentile_within_full_sample=row.percentile_within_full_sample, effect_size=row.effect_size,
            statistic=row.statistic, p_value=row.p_value, confidence_label=row.confidence_label,
            direction_note=row.direction_note,
        )

    @staticmethod
    def _to_cohort_categorical_dto(row: CasCohortCategorical) -> CohortCategoricalDTO:
        return CohortCategoricalDTO(
            feature_name=row.feature_name, n=row.n,
            category_counts=row.category_counts or {}, full_sample_category_counts=row.full_sample_category_counts or {},
        )

    @staticmethod
    def _to_pretransition_window_dto(row: CasPretransitionWindow) -> PreTransitionWindowDTO:
        return PreTransitionWindowDTO(
            window_index=row.window_index, window_label=row.window_label,
            open=row.open, close=row.close, high=row.high, low=row.low,
            net_point_change=row.net_point_change, pct_change=row.pct_change,
            volume=row.volume, rvol_pct=row.rvol_pct, volume_acceleration_ratio=row.volume_acceleration_ratio,
            buy_volume_estimate=row.buy_volume_estimate, sell_volume_estimate=row.sell_volume_estimate,
            dominance_ratio=row.dominance_ratio, dominant_side=row.dominant_side,
            vwap_at_window_end=row.vwap_at_window_end, price_distance_from_vwap=row.price_distance_from_vwap,
            price_distance_from_vwap_pct=row.price_distance_from_vwap_pct, vwap_slope=row.vwap_slope,
            poc_at_window_end=row.poc_at_window_end, poc_change_during_window=row.poc_change_during_window,
            poc_slope=row.poc_slope, vah=row.vah, val=row.val,
            pcr=row.pcr, pcr_change=row.pcr_change, call_oi_change=row.call_oi_change, put_oi_change=row.put_oi_change,
            iv_change=row.iv_change, option_pressure_score=row.option_pressure_score,
            market_regime=row.market_regime, institutional_bias_label=row.institutional_bias_label,
            institutional_bias_score=row.institutional_bias_score, news_risk_score=row.news_risk_score,
            data_quality_flag=row.data_quality_flag,
        )

    @staticmethod
    def _to_post_transition_minute_dto(row: CasPostTransitionMinute) -> PostTransitionMinuteDTO:
        return PostTransitionMinuteDTO(
            minute_offset=row.minute_offset, minute_time=row.minute_time,
            close=row.close, price_change=row.price_change, volume=row.volume, rvol_pct=row.rvol_pct,
            dominance_ratio=row.dominance_ratio, dominant_side=row.dominant_side,
            poc_change=row.poc_change, vwap_change=row.vwap_change,
            pcr_change=row.pcr_change, call_oi_change=row.call_oi_change, put_oi_change=row.put_oi_change,
            iv_change=row.iv_change, option_pressure_score=row.option_pressure_score,
            range_expansion=row.range_expansion, transition_shock_score=row.transition_shock_score,
            data_quality_flag=row.data_quality_flag,
        )

    @staticmethod
    def _to_forecast_dto(row: CasTransitionForecast) -> TransitionForecastDTO:
        factors = [ContributingFactorDTO(**f) for f in (row.top_contributing_factors or [])]
        return TransitionForecastDTO(
            checkpoint_time=row.checkpoint_time,
            probability_no_material_transition=row.probability_no_material_transition,
            probability_large_up=row.probability_large_up, probability_large_down=row.probability_large_down,
            probability_reversal=row.probability_reversal, probability_continuation=row.probability_continuation,
            n_analogs=row.n_analogs, confidence_label=row.confidence_label,
            top_contributing_factors=factors, historical_similarity_score=row.historical_similarity_score,
        )

    @staticmethod
    def _predicted_outcome(p_reversal: float | None, p_continuation: float | None) -> str | None:
        if p_reversal is None or p_continuation is None or p_reversal == p_continuation:
            return None
        return "reversal" if p_reversal > p_continuation else "continuation"

    @staticmethod
    def _forecast_correct(predicted_outcome: str | None, actual_outcome: str) -> bool | None:
        if predicted_outcome is None or actual_outcome == "neutral":
            return None
        return predicted_outcome == actual_outcome
