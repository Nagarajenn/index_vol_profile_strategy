import pytest

from analytics.volume_intelligence.forecast import compute_next_interval_forecast
from analytics.volume_intelligence.models import (
    HistoricalSimilarity,
    InstitutionalParticipation,
    SimilarDay,
    VolumeCharacter,
    VolumeMomentum,
    VolumeTrend,
)
from analytics.volume_intelligence.proxy import attach_buy_sell_columns
from datetime import date
from tests.fixtures.synthetic_candles import make_candles


def _price_candles(prices: list[float]) -> "object":
    rows = [{"time": f"09:{15+i:02d}", "o": p, "h": p, "l": p, "c": p, "v": 100} for i, p in enumerate(prices)]
    return attach_buy_sell_columns(make_candles(rows))


def test_forecast_bullish_composite_gives_high_continuation_and_confidence():
    enriched = _price_candles([100 + i * 0.5 for i in range(20)])  # clear up-move, 20 candles
    trend = VolumeTrend(window_minutes=20, pct_change=40.0, label="Strong Increasing")
    momentum = VolumeMomentum(ema_signed_volume=80.0, normalized_score=0.8, streak_minutes=8, label="Strong Buy Momentum")
    character = VolumeCharacter(label="Markup", rationale="price advancing on buy-dominant volume")
    institutional = InstitutionalParticipation(score=80, label="Very High", rvol_component=1.0, blockiness_component=0.5, dominance_component=1.0)
    similarity = HistoricalSimilarity(
        top_days=[SimilarDay(session_date=date(2026, 7, 1), distance=0.1, similarity=0.9, dominant_side="buy", total_volume_ratio=1.1)],
        resemblance_label="accumulation-like sessions",
        n_days_compared=10,
    )

    result = compute_next_interval_forecast(trend, momentum, character, institutional, similarity, enriched)

    assert result.composite_score == pytest.approx(0.77, abs=0.01)
    assert result.probability_continuation == pytest.approx(0.808, abs=0.01)
    assert result.probability_reversal == pytest.approx(1 - result.probability_continuation)
    assert result.confidence == "High"
    assert result.horizon_minutes == 10


def test_forecast_confidence_low_with_thin_data():
    enriched = _price_candles([100, 100, 100])
    momentum = VolumeMomentum(ema_signed_volume=0.0, normalized_score=0.0, streak_minutes=0, label="Neutral")
    character = VolumeCharacter(label="Quiet-Consolidation", rationale="no clear signal")
    institutional = InstitutionalParticipation(score=0, label="Minimal", rvol_component=0.5, blockiness_component=0.0, dominance_component=0.0)
    similarity = HistoricalSimilarity()

    result = compute_next_interval_forecast(None, momentum, character, institutional, similarity, enriched)

    assert result.confidence == "Low"


def test_forecast_probabilities_stay_within_bounds():
    enriched = _price_candles([100 - i * 0.5 for i in range(20)])  # down-move
    trend = VolumeTrend(window_minutes=20, pct_change=-40.0, label="Strong Decreasing")
    momentum = VolumeMomentum(ema_signed_volume=-80.0, normalized_score=-0.9, streak_minutes=9, label="Strong Sell Momentum")
    character = VolumeCharacter(label="Climactic", rationale="exhaustion detected")
    institutional = InstitutionalParticipation(score=90, label="Very High", rvol_component=1.0, blockiness_component=0.6, dominance_component=1.0)
    similarity = HistoricalSimilarity(
        top_days=[SimilarDay(session_date=date(2026, 7, 1), distance=0.1, similarity=0.9, dominant_side="sell", total_volume_ratio=1.5)],
        resemblance_label="climactic/high-volume sessions",
        n_days_compared=10,
    )

    result = compute_next_interval_forecast(trend, momentum, character, institutional, similarity, enriched)

    assert 0.1 <= result.probability_continuation <= 0.9
    assert 0.1 <= result.probability_reversal <= 0.9


def test_forecast_supporting_factors_capped_and_sorted():
    enriched = _price_candles([100 + i * 0.5 for i in range(20)])
    trend = VolumeTrend(window_minutes=20, pct_change=40.0, label="Strong Increasing")
    momentum = VolumeMomentum(ema_signed_volume=80.0, normalized_score=0.8, streak_minutes=8, label="Strong Buy Momentum")
    character = VolumeCharacter(label="Markup", rationale="price advancing on buy-dominant volume")
    institutional = InstitutionalParticipation(score=80, label="Very High", rvol_component=1.0, blockiness_component=0.5, dominance_component=1.0)
    # similarity's 0.10-weighted 0.3 contribution = 0.03, below MIN_FACTOR_CONTRIBUTION -- should be excluded.
    similarity = HistoricalSimilarity(
        top_days=[SimilarDay(session_date=date(2026, 7, 1), distance=0.1, similarity=0.9, dominant_side="buy", total_volume_ratio=1.1)],
        resemblance_label="accumulation-like sessions",
        n_days_compared=10,
    )

    result = compute_next_interval_forecast(trend, momentum, character, institutional, similarity, enriched)

    assert len(result.supporting_factors) == 4
    assert result.supporting_factors[0].startswith("Volume trend")
    assert result.supporting_factors[1].startswith("Volume momentum")
    assert not any("Resembles" in f for f in result.supporting_factors)
