import pytest

from analytics.volume_intelligence.institutional import _compute_blockiness, compute_institutional_participation
from analytics.volume_intelligence.models import BuySellDominance, RvolBaselineResult, RvolReading
from analytics.volume_intelligence.proxy import attach_buy_sell_columns
from tests.fixtures.synthetic_candles import make_candles


def _enriched_with_volumes(volumes: list[float]):
    rows = []
    for i, v in enumerate(volumes):
        rows.append({"time": f"09:{15+i:02d}", "o": 100, "h": 100, "l": 100, "c": 100, "v": v})
    return attach_buy_sell_columns(make_candles(rows))


def test_institutional_participation_normal_composite():
    rvol = RvolReading(
        primary=RvolBaselineResult(group="last_20_days", interval_rvol_pct=100.0, cumulative_rvol_pct=100.0, label="Average", sample_days=10)
    )
    dominance = BuySellDominance(window_minutes=8, buy_volume=400, sell_volume=400, dominance_ratio=0.5, dominant_side="balanced", consecutive_dominant_minutes=4)
    enriched = _enriched_with_volumes([100] * 9 + [300])  # 1/10 candles >= 1.5x median -> blockiness 0.1

    result = compute_institutional_participation(rvol, dominance, enriched)

    assert result.rvol_component == pytest.approx(0.5)
    assert result.blockiness_component == pytest.approx(0.1)
    assert result.dominance_component == pytest.approx(0.5)
    assert result.score == 36  # round(100*(0.4*0.5 + 0.35*0.1 + 0.25*0.5))
    assert result.label == "Low"


def test_institutional_participation_all_low_is_minimal():
    rvol = RvolReading(
        primary=RvolBaselineResult(group="last_20_days", interval_rvol_pct=0.0, cumulative_rvol_pct=0.0, label="Below Average", sample_days=10)
    )
    dominance = BuySellDominance(window_minutes=8, buy_volume=0, sell_volume=0, dominance_ratio=0.5, dominant_side="balanced", consecutive_dominant_minutes=0)
    enriched = _enriched_with_volumes([100] * 10)

    result = compute_institutional_participation(rvol, dominance, enriched)

    assert result.score == 0
    assert result.label == "Minimal"


def test_institutional_participation_high_signals_is_very_high():
    rvol = RvolReading(
        primary=RvolBaselineResult(group="last_20_days", interval_rvol_pct=300.0, cumulative_rvol_pct=300.0, label="Above Average", sample_days=10)
    )
    dominance = BuySellDominance(window_minutes=8, buy_volume=800, sell_volume=0, dominance_ratio=1.0, dominant_side="buy", consecutive_dominant_minutes=8)
    enriched = _enriched_with_volumes([100] * 5 + [1000] * 5)  # 5/10 candles >= 1.5x median -> blockiness 0.5

    result = compute_institutional_participation(rvol, dominance, enriched)

    assert result.rvol_component == pytest.approx(1.0)
    assert result.blockiness_component == pytest.approx(0.5)
    assert result.score >= 80
    assert result.label == "Very High"


def test_institutional_participation_missing_rvol_defaults_neutral():
    rvol = RvolReading()  # primary is None
    dominance = BuySellDominance(window_minutes=8, buy_volume=0, sell_volume=0, dominance_ratio=0.5, dominant_side="balanced", consecutive_dominant_minutes=0)
    enriched = _enriched_with_volumes([100] * 10)

    result = compute_institutional_participation(rvol, dominance, enriched)

    assert result.rvol_component == pytest.approx(0.5)


def test_blockiness_detects_outlier_candles():
    enriched = _enriched_with_volumes([100] * 9 + [300])
    assert _compute_blockiness(enriched) == pytest.approx(0.1)
