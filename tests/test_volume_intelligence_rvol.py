import pandas as pd
import pytest

from analytics.volume_intelligence.models import BaselineReading
from analytics.volume_intelligence.rvol import (
    compute_rvol,
    compute_volume_acceleration,
    compute_volume_dryup,
    compute_volume_spike,
)
from tests.fixtures.synthetic_candles import make_candles


def _candles_with_volumes(volumes: list[float]) -> pd.DataFrame:
    rows = []
    for i, v in enumerate(volumes):
        minute = 15 + i
        hh = 9 + minute // 60
        mm = minute % 60
        rows.append({"time": f"{hh:02d}:{mm:02d}", "o": 100, "h": 100, "l": 100, "c": 100, "v": v})
    return make_candles(rows)


def test_compute_rvol_interval_and_cumulative():
    candles = _candles_with_volumes([500, 600])
    baseline = BaselineReading(
        group="last_20_days", elapsed_minutes=1, interval_avg_volume=300.0, cumulative_avg_volume=800.0, sample_days=5
    )

    reading = compute_rvol(candles, {"last_20_days": baseline})
    result = reading.by_baseline["last_20_days"]

    assert result.interval_rvol_pct == pytest.approx(200.0)  # 600/300*100
    assert result.cumulative_rvol_pct == pytest.approx(137.5)  # 1100/800*100
    assert result.label == "Above Average"
    assert reading.primary is result


def test_compute_rvol_empty_when_no_baselines():
    candles = _candles_with_volumes([500])
    reading = compute_rvol(candles, {})
    assert reading.by_baseline == {}
    assert reading.primary is None


def test_compute_rvol_label_thresholds():
    baseline = BaselineReading(
        group="last_20_days", elapsed_minutes=0, interval_avg_volume=100.0, cumulative_avg_volume=100.0, sample_days=5
    )

    below = compute_rvol(_candles_with_volumes([80]), {"last_20_days": baseline})
    assert below.by_baseline["last_20_days"].label == "Below Average"

    average = compute_rvol(_candles_with_volumes([100]), {"last_20_days": baseline})
    assert average.by_baseline["last_20_days"].label == "Average"


def test_compute_volume_acceleration_accelerating():
    candles = _candles_with_volumes([100] * 5 + [150] * 5)
    result = compute_volume_acceleration(candles)
    assert result is not None
    assert result.ratio == pytest.approx(1.5)
    assert result.label == "Accelerating"


def test_compute_volume_acceleration_decelerating():
    candles = _candles_with_volumes([200] * 5 + [100] * 5)
    result = compute_volume_acceleration(candles)
    assert result.label == "Decelerating"


def test_compute_volume_acceleration_stable():
    candles = _candles_with_volumes([100] * 5 + [105] * 5)
    result = compute_volume_acceleration(candles)
    assert result.label == "Stable"


def test_compute_volume_acceleration_insufficient_data():
    candles = _candles_with_volumes([100] * 5)
    result = compute_volume_acceleration(candles)
    assert result is None


def test_compute_volume_spike_detected_with_historical_baseline():
    candles = _candles_with_volumes([100] * 5 + [300])
    baseline = BaselineReading(
        group="last_20_days", elapsed_minutes=5, interval_avg_volume=100.0, cumulative_avg_volume=600.0, sample_days=10
    )
    result = compute_volume_spike(candles, baseline)
    assert result.is_spike is True
    assert result.baseline_source == "historical_20d"
    assert result.multiple == pytest.approx(3.0)


def test_compute_volume_spike_not_detected():
    candles = _candles_with_volumes([100] * 5 + [150])
    baseline = BaselineReading(
        group="last_20_days", elapsed_minutes=5, interval_avg_volume=100.0, cumulative_avg_volume=600.0, sample_days=10
    )
    result = compute_volume_spike(candles, baseline)
    assert result.is_spike is False


def test_compute_volume_spike_falls_back_to_intraday_rolling_when_no_baseline():
    candles = _candles_with_volumes([100] * 20 + [300])
    result = compute_volume_spike(candles, None)
    assert result.baseline_source == "intraday_rolling"
    assert result.is_spike is True


def test_compute_volume_dryup_detected():
    candles = _candles_with_volumes([100] * 5 + [30])
    baseline = BaselineReading(
        group="last_20_days", elapsed_minutes=5, interval_avg_volume=100.0, cumulative_avg_volume=600.0, sample_days=10
    )
    result = compute_volume_dryup(candles, baseline)
    assert result.is_dryup is True
    assert result.fraction == pytest.approx(0.3)


def test_compute_volume_dryup_not_detected():
    candles = _candles_with_volumes([100] * 5 + [60])
    baseline = BaselineReading(
        group="last_20_days", elapsed_minutes=5, interval_avg_volume=100.0, cumulative_avg_volume=600.0, sample_days=10
    )
    result = compute_volume_dryup(candles, baseline)
    assert result.is_dryup is False
