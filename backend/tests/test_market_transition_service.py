import sys
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

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
from app.services.market_transition_service import MarketTransitionService


def _daily_row(
    session_date: date, outcome: str = "reversal", factors=None, p_reversal: float | None = 0.65, p_continuation: float | None = 0.35
) -> MtiDailyTransition:
    return MtiDailyTransition(
        symbol="NIFTY",
        session_date=session_date,
        profile_shape_1459="D",
        market_regime_1459="Trending",
        expiry_type=None,
        close_1459=100,
        close_1501=101,
        market_close=105,
        transition_move=1,
        transition_direction="up",
        post_transition_move=4,
        outcome=outcome,
        outcome_magnitude=4,
        transition_risk_score=65.0,
        probability_continuation=p_continuation,
        probability_reversal=p_reversal,
        expected_volatility=10.0,
        expected_direction="up",
        historical_similarity_score=0.8,
        top_contributing_factors=factors or [{"factor_name": "VWAP distance", "today_value": "0.2", "note": "n=30", "contribution": 0.5}],
        statistical_confidence="Moderate",
        explanation="Test explanation.",
        computed_at=datetime.now(timezone.utc),
    )


def _correlation_row(factor_name: str, target: str, p_value: float | None) -> MtiFactorCorrelation:
    return MtiFactorCorrelation(
        symbol="NIFTY",
        factor_name=factor_name,
        factor_type="continuous",
        target=target,
        n_days=50,
        statistic=0.3,
        p_value=p_value,
        confidence_label="Moderate" if p_value and p_value < 0.05 else "Not significant",
        direction_note="Higher values associate with reversal.",
        category_breakdown=None,
        computed_at=datetime.now(timezone.utc),
    )


def _cas_daily_row(
    session_date: date,
    transition_type: str = "NO_MATERIAL_TRANSITION",
    magnitude_tier: str | None = None,
    conclusion: str = "neutral",
    old_methodology_outcome: str | None = None,
) -> CasDailyTransition:
    return CasDailyTransition(
        symbol="NIFTY",
        session_date=session_date,
        close_1431=100, close_1459=100, close_1539=90,
        pre_direction="flat", post_direction="down",
        conclusion=conclusion,
        outcome_magnitude=10,
        pre_window_volume=1000, post_window_pre_auction_volume=2000, volume_ratio=2.0,
        pre_window_points_move=0, post_window_points_move=-10,
        pcr_1459=0.9, institutional_bias_label_1459="Neutral", institutional_bias_score_1459=0,
        expiry_type=None, day_of_week=session_date.weekday(),
        old_methodology_outcome=old_methodology_outcome, old_methodology_outcome_magnitude=None,
        data_quality_flag=None,
        transition_type=transition_type,
        magnitude_pct_return=-10.0, magnitude_atr_normalized=1.5, magnitude_tier=magnitude_tier,
        computed_at=datetime.now(timezone.utc),
    )


class _FakeRepo:
    def __init__(
        self, daily, correlations, cas_daily=None, cas_correlations=None,
        pretransition_windows=None, post_transition_minutes=None, transition_forecasts=None,
        cohort_feature_stats=None, cohort_categorical=None,
    ) -> None:
        self._daily = daily
        self._correlations = correlations
        self._cas_daily = cas_daily or []
        self._cas_correlations = cas_correlations or []
        self._pretransition_windows = pretransition_windows or []
        self._post_transition_minutes = post_transition_minutes or []
        self._transition_forecasts = transition_forecasts or []
        self._cohort_feature_stats = cohort_feature_stats or []
        self._cohort_categorical = cohort_categorical or []

    async def list_daily(self, symbol: str, limit: int = 200):
        return self._daily[:limit]

    async def list_correlations(self, symbol: str):
        return self._correlations

    async def list_cas_daily(self, symbol: str, limit: int = 60):
        return self._cas_daily[:limit]

    async def list_cas_correlations(self, symbol: str):
        return self._cas_correlations

    async def list_pretransition_windows(self, symbol: str, session_date: date):
        return self._pretransition_windows

    async def list_post_transition_minutes(self, symbol: str, session_date: date):
        return self._post_transition_minutes

    async def list_transition_forecasts(self, symbol: str, session_date: date):
        return self._transition_forecasts

    async def list_cohort_feature_stats(self, symbol: str):
        return self._cohort_feature_stats

    async def list_cohort_categorical(self, symbol: str):
        return self._cohort_categorical


def _pretransition_window_row(window_index: int = 1, dominant_side: str = "balanced") -> CasPretransitionWindow:
    return CasPretransitionWindow(
        symbol="NIFTY", session_date=date(2026, 8, 27), window_index=window_index, window_label="14:30-14:34",
        open=100, close=101, high=102, low=99, net_point_change=1, pct_change=1.0,
        volume=1000, rvol_pct=110.0, volume_acceleration_ratio=1.1,
        buy_volume_estimate=550, sell_volume_estimate=450, dominance_ratio=0.55, dominant_side=dominant_side,
        vwap_at_window_end=100.5, price_distance_from_vwap=0.5, price_distance_from_vwap_pct=0.5, vwap_slope=0.1,
        poc_at_window_end=100.0, poc_change_during_window=0.5, poc_slope=0.5, vah=101.0, val=99.0,
        pcr=0.9, pcr_change=0.01, call_oi_change=100.0, put_oi_change=-50.0, iv_change=-0.5, option_pressure_score=0.2,
        market_regime="Trending", institutional_bias_label="Neutral", institutional_bias_score=0, news_risk_score=None,
        data_quality_flag=None, computed_at=datetime.now(timezone.utc),
    )


def _post_transition_minute_row(minute_offset: int = 0) -> CasPostTransitionMinute:
    return CasPostTransitionMinute(
        symbol="NIFTY", session_date=date(2026, 8, 27), minute_offset=minute_offset, minute_time="15:00",
        close=101, price_change=1.0, volume=500, rvol_pct=90.0,
        dominance_ratio=0.6, dominant_side="buy", poc_change=0.5, vwap_change=0.2,
        pcr_change=0.0, call_oi_change=0.0, put_oi_change=0.0, iv_change=0.0, option_pressure_score=0.1,
        range_expansion=1.2, transition_shock_score=35.0, is_closing_snapshot=False,
        data_quality_flag=None, computed_at=datetime.now(timezone.utc),
    )


def _transition_forecast_row(checkpoint_time: str = "14:59") -> CasTransitionForecast:
    return CasTransitionForecast(
        symbol="NIFTY", session_date=date(2026, 8, 27), checkpoint_time=checkpoint_time,
        probability_no_material_transition=0.5, probability_large_up=0.25, probability_large_down=0.25,
        probability_reversal=0.6, probability_continuation=0.4, n_analogs=8, confidence_label="Weak",
        top_contributing_factors=[{"factor_name": "PCR", "today_value": "0.9", "note": "n=8", "contribution": 0.2}],
        historical_similarity_score=0.7, computed_at=datetime.now(timezone.utc),
    )


def _cohort_feature_stat_row(cohort: str = "UP_CONTINUATION", feature_name: str = "Pre-window volume (14:55-14:59)", n: int = 4) -> CasCohortFeatureStat:
    return CasCohortFeatureStat(
        symbol="NIFTY", cohort=cohort, feature_name=feature_name, n=n,
        median=1000.0, mean=1010.0, percentile_within_full_sample=75.0, effect_size=0.8,
        statistic=2.0, p_value=0.03, confidence_label="Insufficient data",
        direction_note="Cohort median is higher than the rest of the sample.", computed_at=datetime.now(timezone.utc),
    )


def _cohort_categorical_row(cohort: str = "UP_CONTINUATION", feature_name: str = "Institutional bias label (14:59)") -> CasCohortCategorical:
    return CasCohortCategorical(
        symbol="NIFTY", cohort=cohort, feature_name=feature_name, n=4,
        category_counts={"Neutral": 4}, full_sample_category_counts={"Neutral": 8},
        computed_at=datetime.now(timezone.utc),
    )


@pytest.mark.asyncio
async def test_get_research_maps_daily_and_correlation_rows():
    daily = [_daily_row(date(2026, 7, 30)), _daily_row(date(2026, 7, 29), outcome="continuation")]
    correlations = [_correlation_row("VWAP distance", "reversal", 0.02)]
    service = MarketTransitionService(_FakeRepo(daily, correlations))

    result = await service.get_research("NIFTY")

    assert result.symbol == "NIFTY"
    assert result.total_days_analyzed == 2
    assert len(result.daily_results) == 2
    assert result.daily_results[0].session_date == date(2026, 7, 30)
    assert result.daily_results[0].top_contributing_factors[0].factor_name == "VWAP distance"
    assert len(result.correlations) == 1
    assert result.correlations[0].confidence_label == "Moderate"


@pytest.mark.asyncio
async def test_get_research_sorts_correlations_by_p_value_nulls_last():
    correlations = [
        _correlation_row("Factor A", "reversal", None),
        _correlation_row("Factor B", "reversal", 0.01),
        _correlation_row("Factor C", "magnitude", 0.2),
    ]
    service = MarketTransitionService(_FakeRepo([], correlations))

    result = await service.get_research("SENSEX")

    assert [c.factor_name for c in result.correlations] == ["Factor B", "Factor C", "Factor A"]


@pytest.mark.asyncio
async def test_get_research_empty_when_no_data():
    service = MarketTransitionService(_FakeRepo([], []))
    result = await service.get_research("NIFTY")

    assert result.total_days_analyzed == 0
    assert result.daily_results == []
    assert result.correlations == []


@pytest.mark.asyncio
async def test_daily_result_handles_missing_top_contributing_factors():
    daily = [_daily_row(date(2026, 7, 30), factors=None)]
    daily[0].top_contributing_factors = None
    service = MarketTransitionService(_FakeRepo(daily, []))

    result = await service.get_research("NIFTY")
    assert result.daily_results[0].top_contributing_factors == []


@pytest.mark.asyncio
async def test_forecast_correct_when_predicted_reversal_and_actual_reversal():
    daily = [_daily_row(date(2026, 7, 30), outcome="reversal", p_reversal=0.65, p_continuation=0.35)]
    service = MarketTransitionService(_FakeRepo(daily, []))

    result = await service.get_research("NIFTY")

    dto = result.daily_results[0]
    assert dto.predicted_outcome == "reversal"
    assert dto.forecast_correct is True
    assert result.forecast_evaluable_days == 1
    assert result.forecast_hit_count == 1
    assert result.forecast_accuracy_pct == 100.0


@pytest.mark.asyncio
async def test_forecast_incorrect_when_predicted_reversal_but_actual_continuation():
    daily = [_daily_row(date(2026, 7, 30), outcome="continuation", p_reversal=0.65, p_continuation=0.35)]
    service = MarketTransitionService(_FakeRepo(daily, []))

    result = await service.get_research("NIFTY")

    dto = result.daily_results[0]
    assert dto.predicted_outcome == "reversal"
    assert dto.forecast_correct is False
    assert result.forecast_evaluable_days == 1
    assert result.forecast_hit_count == 0
    assert result.forecast_accuracy_pct == 0.0


@pytest.mark.asyncio
async def test_forecast_not_graded_when_actual_outcome_is_neutral():
    daily = [_daily_row(date(2026, 7, 30), outcome="neutral", p_reversal=0.65, p_continuation=0.35)]
    service = MarketTransitionService(_FakeRepo(daily, []))

    result = await service.get_research("NIFTY")

    dto = result.daily_results[0]
    assert dto.predicted_outcome == "reversal"
    assert dto.forecast_correct is None
    assert result.forecast_evaluable_days == 0
    assert result.forecast_accuracy_pct is None


@pytest.mark.asyncio
async def test_forecast_not_graded_on_tied_probabilities():
    daily = [_daily_row(date(2026, 7, 30), outcome="reversal", p_reversal=0.5, p_continuation=0.5)]
    service = MarketTransitionService(_FakeRepo(daily, []))

    result = await service.get_research("NIFTY")

    dto = result.daily_results[0]
    assert dto.predicted_outcome is None
    assert dto.forecast_correct is None
    assert result.forecast_evaluable_days == 0


@pytest.mark.asyncio
async def test_forecast_not_graded_when_probabilities_missing():
    daily = [_daily_row(date(2026, 7, 30), outcome="reversal", p_reversal=None, p_continuation=None)]
    service = MarketTransitionService(_FakeRepo(daily, []))

    result = await service.get_research("NIFTY")

    dto = result.daily_results[0]
    assert dto.predicted_outcome is None
    assert dto.forecast_correct is None


@pytest.mark.asyncio
async def test_forecast_accuracy_aggregates_across_multiple_days():
    daily = [
        _daily_row(date(2026, 7, 30), outcome="reversal", p_reversal=0.65, p_continuation=0.35),  # hit
        _daily_row(date(2026, 7, 29), outcome="continuation", p_reversal=0.65, p_continuation=0.35),  # miss
        _daily_row(date(2026, 7, 28), outcome="continuation", p_reversal=0.3, p_continuation=0.7),  # hit
        _daily_row(date(2026, 7, 27), outcome="neutral", p_reversal=0.65, p_continuation=0.35),  # ungraded
    ]
    service = MarketTransitionService(_FakeRepo(daily, []))

    result = await service.get_research("NIFTY")

    assert result.forecast_evaluable_days == 3
    assert result.forecast_hit_count == 2
    assert result.forecast_accuracy_pct == pytest.approx(66.7, abs=0.1)


@pytest.mark.asyncio
async def test_get_cas_intelligence_maps_transition_type_and_magnitude_fields():
    # The regression this reclassification fixes: a flat-pre/large-post day
    # keeps `conclusion="neutral"` (untouched) but must surface the richer
    # transition_type/magnitude fields through the DTO unchanged.
    cas_daily = [
        _cas_daily_row(
            date(2026, 8, 27), transition_type="POST_WINDOW_INITIATION_DOWN", magnitude_tier="MODERATE",
            conclusion="neutral", old_methodology_outcome="reversal",
        )
    ]
    service = MarketTransitionService(_FakeRepo([], [], cas_daily=cas_daily))

    result = await service.get_cas_intelligence("NIFTY")

    assert result.total_days_analyzed == 1
    dto = result.daily_results[0]
    assert dto.conclusion == "neutral"
    assert dto.transition_type == "POST_WINDOW_INITIATION_DOWN"
    assert dto.magnitude_tier == "MODERATE"
    assert dto.magnitude_pct_return == pytest.approx(-10.0)
    assert dto.magnitude_atr_normalized == pytest.approx(1.5)
    # agreement comparison (unrelated to this phase) still works off `conclusion`/`old_methodology_outcome`
    assert result.agreement_count == 0  # neutral != reversal


@pytest.mark.asyncio
async def test_get_cas_intelligence_magnitude_tier_none_when_atr_unavailable():
    cas_daily = [_cas_daily_row(date(2026, 8, 27), magnitude_tier=None)]
    service = MarketTransitionService(_FakeRepo([], [], cas_daily=cas_daily))

    result = await service.get_cas_intelligence("NIFTY")

    assert result.daily_results[0].magnitude_tier is None


@pytest.mark.asyncio
async def test_get_cas_windowed_detail_maps_all_three_row_types():
    repo = _FakeRepo(
        [], [],
        pretransition_windows=[_pretransition_window_row(1), _pretransition_window_row(2)],
        post_transition_minutes=[_post_transition_minute_row(0), _post_transition_minute_row(1)],
        transition_forecasts=[_transition_forecast_row("14:30"), _transition_forecast_row("14:59")],
    )
    service = MarketTransitionService(repo)

    result = await service.get_cas_windowed_detail("NIFTY", date(2026, 8, 27))

    assert result.symbol == "NIFTY"
    assert result.session_date == date(2026, 8, 27)
    assert len(result.pre_transition_windows) == 2
    assert len(result.post_transition_minutes) == 2
    assert len(result.forecasts) == 2
    assert result.pre_transition_windows[0].dominant_side == "balanced"
    assert result.post_transition_minutes[0].transition_shock_score == pytest.approx(35.0)
    assert result.forecasts[1].checkpoint_time == "14:59"
    assert result.forecasts[1].top_contributing_factors[0].factor_name == "PCR"


@pytest.mark.asyncio
async def test_get_cas_windowed_detail_empty_when_nothing_computed_yet():
    service = MarketTransitionService(_FakeRepo([], []))

    result = await service.get_cas_windowed_detail("NIFTY", date(2026, 8, 27))

    assert result.pre_transition_windows == []
    assert result.post_transition_minutes == []
    assert result.forecasts == []


@pytest.mark.asyncio
async def test_get_cas_cohort_analysis_always_returns_all_seven_cohorts():
    service = MarketTransitionService(_FakeRepo([], []))

    result = await service.get_cas_cohort_analysis("NIFTY")

    assert result.symbol == "NIFTY"
    assert len(result.cohorts) == 7
    assert {c.cohort for c in result.cohorts} == {
        "FLAT_LARGE_UP", "FLAT_LARGE_DOWN", "UP_REVERSAL_DOWN", "DOWN_REVERSAL_UP",
        "UP_CONTINUATION", "DOWN_CONTINUATION", "FLAT_NO_MATERIAL_MOVE",
    }
    # every cohort present even with zero data -- not silently dropped
    for c in result.cohorts:
        assert c.n_days == 0
        assert c.features == []
        assert c.categorical == []


@pytest.mark.asyncio
async def test_get_cas_cohort_analysis_groups_features_and_categorical_by_cohort():
    repo = _FakeRepo(
        [], [],
        cohort_feature_stats=[
            _cohort_feature_stat_row(cohort="UP_CONTINUATION", feature_name="Pre-window volume (14:55-14:59)", n=6),
            _cohort_feature_stat_row(cohort="UP_CONTINUATION", feature_name="PCR (14:59)", n=5),
            _cohort_feature_stat_row(cohort="DOWN_CONTINUATION", feature_name="Pre-window volume (14:55-14:59)", n=3),
        ],
        cohort_categorical=[_cohort_categorical_row(cohort="UP_CONTINUATION")],
    )
    service = MarketTransitionService(repo)

    result = await service.get_cas_cohort_analysis("NIFTY")

    up_continuation = next(c for c in result.cohorts if c.cohort == "UP_CONTINUATION")
    down_continuation = next(c for c in result.cohorts if c.cohort == "DOWN_CONTINUATION")
    flat_no_material = next(c for c in result.cohorts if c.cohort == "FLAT_NO_MATERIAL_MOVE")

    assert len(up_continuation.features) == 2
    assert up_continuation.n_days == 6  # max n across this cohort's features
    assert len(up_continuation.categorical) == 1
    assert up_continuation.categorical[0].category_counts == {"Neutral": 4}

    assert len(down_continuation.features) == 1
    assert down_continuation.n_days == 3

    # cohorts with no rows at all still present, empty
    assert flat_no_material.features == []
    assert flat_no_material.n_days == 0
