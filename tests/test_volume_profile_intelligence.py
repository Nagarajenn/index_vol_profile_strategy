import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from analytics.volume_profile import compute_volume_profile
from analytics.volume_profile_intelligence import (
    classify_level_test,
    classify_opening_type,
    classify_profile_shape,
    compute_developing_levels,
    compute_initial_balance,
    compute_rotation_factor,
    compute_value_migration,
    compute_volume_nodes,
    compute_volume_pace,
    compute_volume_profile_intelligence,
)
from tests.fixtures.synthetic_candles import flat_candle, make_candles


def test_developing_levels_track_poc_shift_through_session():
    # Heavy volume at 100 early, heavy volume at 110 later -> developing POC
    # should start near 100 and end near 110.
    candles = make_candles(
        [
            flat_candle("09:15", 100, 50),
            flat_candle("09:20", 100, 50),
            flat_candle("09:45", 110, 5),
            flat_candle("10:15", 110, 80),
            flat_candle("10:20", 110, 80),
        ]
    )
    points = compute_developing_levels(candles, bin_size=1, checkpoint_minutes=15)
    assert len(points) >= 2
    assert points[0].poc == pytest.approx(100.5)
    assert points[-1].poc == pytest.approx(110.5)


def test_developing_levels_empty_input():
    assert compute_developing_levels(make_candles([]), bin_size=1) == []


def test_hvn_lvn_detect_peaks_and_troughs():
    bins = {100: 10.0, 101: 60.0, 102: 8.0, 103: 2.0, 104: 55.0, 105: 9.0}
    hvns, lvns = compute_volume_nodes(bins, bin_size=1)
    hvn_prices = {round(n.price) for n in hvns}
    lvn_prices = {round(n.price) for n in lvns}
    assert 101 in {p - 1 for p in hvn_prices} or any(101 <= p <= 102 for p in hvn_prices)
    assert 104 in {p - 1 for p in hvn_prices} or any(104 <= p <= 105 for p in hvn_prices)
    assert any(103 <= p <= 104 for p in lvn_prices)


def test_value_migration_direction_and_shift():
    yesterday = make_candles([flat_candle("09:15", 100, 50), flat_candle("09:20", 100, 50)], tz_date="2026-07-01")
    today = make_candles([flat_candle("09:15", 110, 50), flat_candle("09:20", 110, 50)], tz_date="2026-07-02")

    yesterday_vp = compute_volume_profile(yesterday, bin_size=1)
    today_vp = compute_volume_profile(today, bin_size=1)
    migration = compute_value_migration(today_vp, yesterday_vp, developing=[])

    assert migration is not None
    assert migration.direction == "up"
    assert migration.poc_shift == pytest.approx(10.0)


def test_value_migration_none_without_prior_day():
    today_vp = compute_volume_profile(make_candles([flat_candle("09:15", 100, 10)]), bin_size=1)
    assert compute_value_migration(today_vp, None, developing=[]) is None


def test_level_test_accepted_when_price_dwells_at_level():
    candles = make_candles(
        [
            flat_candle("09:15", 100.0, 10),
            flat_candle("09:16", 100.2, 10),
            flat_candle("09:17", 99.8, 10),
            flat_candle("09:18", 100.1, 10),
        ]
    )
    outcome, touches = classify_level_test(candles, level_price=100.0, tolerance=0.5)
    assert outcome == "accepted"
    assert touches == 4


def test_level_test_rejected_on_single_fast_reversal():
    candles = make_candles(
        [
            {"time": "09:15", "o": 90.0, "h": 90.0, "l": 90.0, "c": 90.0, "v": 10},
            {"time": "09:16", "o": 90.0, "h": 100.4, "l": 90.0, "c": 92.0, "v": 10},
            {"time": "09:17", "o": 92.0, "h": 92.0, "l": 85.0, "c": 85.0, "v": 10},
        ]
    )
    outcome, touches = classify_level_test(candles, level_price=100.0, tolerance=0.5)
    assert outcome == "rejected"
    assert touches == 1


def test_level_test_untested_when_never_reached():
    candles = make_candles([flat_candle("09:15", 100.0, 10)])
    outcome, touches = classify_level_test(candles, level_price=200.0, tolerance=0.5)
    assert outcome == "untested"
    assert touches == 0


def test_profile_shape_p_when_volume_concentrated_near_highs():
    bins = {100: 2.0, 101: 3.0, 108: 40.0, 109: 60.0, 110: 45.0}
    result = classify_profile_shape(bins, poc=109.5, bin_size=1)
    assert result.shape == "P"


def test_profile_shape_b_when_volume_concentrated_near_lows():
    bins = {100: 45.0, 101: 60.0, 102: 40.0, 108: 3.0, 109: 2.0}
    result = classify_profile_shape(bins, poc=101.5, bin_size=1)
    assert result.shape == "b"


def test_profile_shape_d_when_balanced():
    bins = {100: 5.0, 101: 20.0, 102: 60.0, 103: 20.0, 104: 5.0}
    result = classify_profile_shape(bins, poc=102.5, bin_size=1)
    assert result.shape == "D"


def test_profile_shape_b_bimodal_when_two_separated_clusters():
    # Two narrow peaks (100-101, 120-121) well above a low-volume valley
    # between them -> two HVN clusters separated by >=25% of the range.
    bins = {
        100: 50.0,
        101: 55.0,
        102: 5.0,
        103: 4.0,
        104: 3.0,
        105: 4.0,
        106: 3.0,
        107: 4.0,
        108: 3.0,
        120: 48.0,
        121: 52.0,
    }
    result = classify_profile_shape(bins, poc=101.5, bin_size=1)
    assert result.shape == "B"


def test_initial_balance_from_first_window():
    candles = make_candles(
        [
            flat_candle("09:15", 100, 10),
            {"time": "09:30", "o": 100, "h": 105, "l": 98, "c": 101, "v": 10},
            {"time": "10:30", "o": 101, "h": 120, "l": 90, "c": 110, "v": 10},  # outside 60-min IB window
        ]
    )
    ib = compute_initial_balance(candles, ib_minutes=60)
    assert ib is not None
    assert ib.ib_high == 105
    assert ib.ib_low == 98
    assert ib.is_complete is True


def test_initial_balance_incomplete_when_session_shorter_than_window():
    candles = make_candles([flat_candle("09:15", 100, 10), flat_candle("09:30", 101, 10)])
    ib = compute_initial_balance(candles, ib_minutes=60)
    assert ib is not None
    assert ib.is_complete is False


def test_opening_type_drive_on_directional_move_with_no_retrace():
    candles = make_candles(
        [
            {"time": "09:15", "o": 100.0, "h": 101.0, "l": 100.0, "c": 101.0, "v": 10},
            {"time": "09:20", "o": 101.0, "h": 103.0, "l": 101.0, "c": 103.0, "v": 10},
            {"time": "09:25", "o": 103.0, "h": 106.0, "l": 103.0, "c": 106.0, "v": 10},
        ]
    )
    result = classify_opening_type(candles, yesterday_vp=None, window_minutes=30)
    assert result is not None
    assert result.type == "Open-Drive"


def test_opening_type_auction_on_tight_range():
    candles = make_candles(
        [
            flat_candle("09:15", 100.00, 10),
            flat_candle("09:20", 100.02, 10),
            flat_candle("09:25", 99.99, 10),
        ]
    )
    result = classify_opening_type(candles, yesterday_vp=None, window_minutes=30)
    assert result is not None
    assert result.type == "Open-Auction"


def test_rotation_factor_trending_when_rotations_agree():
    candles = make_candles(
        [
            {"time": "09:15", "o": 100, "h": 101, "l": 100, "c": 101, "v": 10},
            {"time": "09:45", "o": 101, "h": 103, "l": 101, "c": 103, "v": 10},
            {"time": "10:15", "o": 103, "h": 105, "l": 103, "c": 105, "v": 10},
            {"time": "10:45", "o": 105, "h": 107, "l": 105, "c": 107, "v": 10},
        ]
    )
    result = compute_rotation_factor(candles, period_minutes=30)
    assert result.label == "Trending"
    assert result.value == 0


def test_rotation_factor_rotational_when_alternating():
    candles = make_candles(
        [
            {"time": "09:15", "o": 100, "h": 101, "l": 100, "c": 101, "v": 10},
            {"time": "09:45", "o": 101, "h": 101, "l": 95, "c": 96, "v": 10},
            {"time": "10:15", "o": 96, "h": 104, "l": 96, "c": 103, "v": 10},
            {"time": "10:45", "o": 103, "h": 103, "l": 90, "c": 91, "v": 10},
        ]
    )
    result = compute_rotation_factor(candles, period_minutes=30)
    assert result.label == "Rotational"
    assert result.value >= 2


def test_volume_pace_above_average():
    today = make_candles([flat_candle("09:15", 100, 100), flat_candle("09:20", 100, 100)], tz_date="2026-07-10")
    historical = {
        "2026-07-08": make_candles([flat_candle("09:15", 100, 20), flat_candle("09:20", 100, 20)], tz_date="2026-07-08"),
        "2026-07-09": make_candles([flat_candle("09:15", 100, 30), flat_candle("09:20", 100, 30)], tz_date="2026-07-09"),
    }
    pace = compute_volume_pace(today, historical)
    assert pace is not None
    assert pace.label == "Above Average"
    assert pace.pace_pct > 115


def test_volume_pace_none_without_history():
    today = make_candles([flat_candle("09:15", 100, 10)])
    assert compute_volume_pace(today, {}) is None


def test_orchestrator_smoke_test_full_data():
    today = make_candles(
        [flat_candle(f"09:{15+i}", 100 + i * 0.1, 10) for i in range(0, 40, 5)],
        tz_date="2026-07-10",
    )
    historical = {
        "2026-07-09": make_candles([flat_candle("09:15", 99, 20), flat_candle("09:20", 99, 20)], tz_date="2026-07-09")
    }
    result = compute_volume_profile_intelligence(today, historical, bin_size=1)

    assert result.developing != []
    assert result.profile_shape is not None
    assert result.migration is not None
    assert result.initial_balance is not None
    assert result.opening_type is not None
    assert result.rotation_factor is not None
    assert result.volume_pace is not None
    assert result.level_tests != []


def test_orchestrator_handles_empty_candles_gracefully():
    result = compute_volume_profile_intelligence(make_candles([]), {}, bin_size=1)
    assert result.developing == []
    assert result.hvns == []
    assert result.lvns == []
    assert result.migration is None
    assert result.initial_balance is None
    assert result.opening_type is None
    assert result.volume_pace is None
