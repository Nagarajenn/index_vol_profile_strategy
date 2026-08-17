import pandas as pd
import pytest

from analytics.volume_profile import compute_volume_profile
from quant_features.volume_profile_features import compute_volume_profile_feature_set
from tests.fixtures.synthetic_candles import flat_candle, make_candles

BIN_SIZE = 5.0


def _minute_time(i: int) -> str:
    minute = 15 + i
    hh = 9 + minute // 60
    mm = minute % 60
    return f"{hh:02d}:{mm:02d}"


def _flat_session(n_minutes: int, price: float = 110.0, volume: float = 1000.0) -> pd.DataFrame:
    rows = [flat_candle(_minute_time(i), price, volume) for i in range(n_minutes)]
    return make_candles(rows)


def test_today_poc_matches_direct_compute_volume_profile_call():
    candles = _flat_session(10)
    result = compute_volume_profile_feature_set(candles, {}, BIN_SIZE, close=110.0)
    expected = compute_volume_profile(candles, BIN_SIZE)
    assert result.today_poc == pytest.approx(expected.poc)
    assert result.today_vah == pytest.approx(expected.vah)
    assert result.today_val == pytest.approx(expected.val)


def test_poc_distance_pct():
    candles = _flat_session(10)
    result = compute_volume_profile_feature_set(candles, {}, BIN_SIZE, close=115.0)
    assert result.poc_distance_pct == pytest.approx((115.0 - result.today_poc) / result.today_poc)


def test_rotation_label_and_profile_shape_present_even_without_history():
    candles = _flat_session(10)
    result = compute_volume_profile_feature_set(candles, {}, BIN_SIZE, close=110.0)
    assert result.rotation_label is not None
    assert result.profile_shape is not None
    # No historical days supplied -> volume pace can't be computed.
    assert result.volume_pace_pct is None


def test_poc_migration_intraday_present_with_enough_developing_checkpoints():
    candles = _flat_session(35)  # >30 min -> at least 2 developing checkpoints (15, 30) plus the final point
    result = compute_volume_profile_feature_set(candles, {}, BIN_SIZE, close=110.0)
    assert result.poc_migration_intraday is not None


def test_poc_migration_intraday_none_with_thin_session():
    candles = _flat_session(5)  # under the first 15-minute checkpoint -> only the final developing point exists
    result = compute_volume_profile_feature_set(candles, {}, BIN_SIZE, close=110.0)
    assert result.poc_migration_intraday is None


def test_is_inside_initial_balance():
    # 70 flat one-minute candles all at 110 -> IB (first 60 min) is exactly [110, 110].
    candles = _flat_session(70)
    inside = compute_volume_profile_feature_set(candles, {}, BIN_SIZE, close=110.0)
    outside = compute_volume_profile_feature_set(candles, {}, BIN_SIZE, close=200.0)
    assert bool(inside.is_inside_initial_balance) is True
    assert bool(outside.is_inside_initial_balance) is False


def test_volume_pace_computed_when_historical_data_supplied():
    today = _flat_session(20)
    hist_rows = [flat_candle(_minute_time(i), 110.0, 1000.0, date="2026-06-30") for i in range(20)]
    historical = {pd.Timestamp("2026-06-30").date(): make_candles(hist_rows)}
    result = compute_volume_profile_feature_set(today, historical, BIN_SIZE, close=110.0)
    assert result.volume_pace_pct is not None
