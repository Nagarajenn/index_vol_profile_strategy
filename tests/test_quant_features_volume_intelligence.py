import pandas as pd
import pytest

from analytics.volume_intelligence.engine import compute_volume_intelligence
from quant_features.volume_intelligence_features import compute_volume_intelligence_feature_set
from tests.fixtures.synthetic_candles import make_candles


def _minute_time(i: int) -> str:
    minute = 15 + i
    hh = 9 + minute // 60
    mm = minute % 60
    return f"{hh:02d}:{mm:02d}"


def _session(n_minutes: int, date: str, base_price: float = 100.0) -> pd.DataFrame:
    rows = []
    price = base_price
    for i in range(n_minutes):
        price += 0.5 if i % 3 != 0 else -0.2
        rows.append(
            {
                "time": _minute_time(i),
                "date": date,
                "o": price - 0.3,
                "h": price + 0.5,
                "l": price - 0.5,
                "c": price,
                "v": 500 + (i % 5) * 50,
            }
        )
    return make_candles(rows)


def test_empty_candles_returns_all_none():
    empty = make_candles([])
    result = compute_volume_intelligence_feature_set("NIFTY", empty, {})
    assert result.rvol_interval_pct is None
    assert result.dominance_ratio is None
    assert result.institutional_participation_score is None
    assert result.forecast_probability_continuation is None


def test_flatten_matches_direct_engine_call():
    today = _session(25, "2026-07-10")
    historical = {pd.Timestamp(f"2026-07-{d:02d}").date(): _session(60, f"2026-07-{d:02d}") for d in range(1, 8)}

    result = compute_volume_intelligence_feature_set("NIFTY", today, historical)
    direct = compute_volume_intelligence("NIFTY", today, historical)

    assert result.dominance_ratio == pytest.approx(direct.dominance.dominance_ratio)
    assert result.dominant_side == direct.dominance.dominant_side
    assert result.cumulative_pressure_ratio == pytest.approx(direct.cumulative_pressure.pressure_ratio)
    assert result.momentum_score == pytest.approx(direct.momentum.normalized_score)
    assert result.institutional_participation_score == direct.institutional.score
    assert result.is_volume_spike == direct.spike.is_spike
    assert result.is_volume_dryup == direct.dryup.is_dryup
    assert result.volume_trend_label == direct.trend.label
    assert result.volume_character_label == direct.character.label
    assert result.forecast_probability_continuation == pytest.approx(direct.forecast.probability_continuation)
    assert result.forecast_confidence == direct.forecast.confidence

    if direct.rvol.primary:
        assert result.rvol_interval_pct == pytest.approx(direct.rvol.primary.interval_rvol_pct)
        assert result.rvol_label == direct.rvol.primary.label
    else:
        assert result.rvol_interval_pct is None

    if direct.similarity and direct.similarity.top_days:
        assert result.historical_similarity_top1_score == pytest.approx(direct.similarity.top_days[0].similarity)
    else:
        assert result.historical_similarity_top1_score is None
