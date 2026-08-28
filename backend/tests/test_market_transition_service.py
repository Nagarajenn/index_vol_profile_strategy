import sys
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from app.models import CasDailyTransition, MtiDailyTransition, MtiFactorCorrelation
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
    def __init__(self, daily, correlations, cas_daily=None, cas_correlations=None) -> None:
        self._daily = daily
        self._correlations = correlations
        self._cas_daily = cas_daily or []
        self._cas_correlations = cas_correlations or []

    async def list_daily(self, symbol: str, limit: int = 200):
        return self._daily[:limit]

    async def list_correlations(self, symbol: str):
        return self._correlations

    async def list_cas_daily(self, symbol: str, limit: int = 60):
        return self._cas_daily[:limit]

    async def list_cas_correlations(self, symbol: str):
        return self._cas_correlations


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
