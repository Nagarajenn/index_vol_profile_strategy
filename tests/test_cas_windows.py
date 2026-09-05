from datetime import date, datetime, time

import pytest

from config.settings import IST
from market_transition.cas_windows import (
    PRE_WINDOW_BOUNDARIES,
    _news_risk_near,
    _option_pressure_score,
    _rvol_pct,
    build_post_transition_minutes,
    build_pre_transition_windows,
    compute_actual_outcome_checkpoints,
)
from tests.fixtures.synthetic_candles import make_candles

BIN_SIZE = 1.0


def _full_day_candles(step: float = 0.05, tz_date: str = "2026-08-27") -> "object":
    rows = []
    price = 100.0
    for hh, mm_range in [(9, range(15, 60)), (10, range(60)), (11, range(60)), (12, range(60)), (13, range(60)), (14, range(60)), (15, range(40))]:
        for mm in mm_range:
            price += step
            rows.append({"time": f"{hh:02d}:{mm:02d}", "o": price, "h": price + 0.5, "l": price - 0.5, "c": price, "v": 100})
    return make_candles(rows, tz_date=tz_date)


def _flat_option_lookup(pcr=0.9, call_oi=1000.0, put_oi=800.0, iv_call=15.0, iv_put=14.5):
    def _lookup(at_time):
        return {
            "pcr": pcr, "call_oi_change_near_atm": call_oi, "put_oi_change_near_atm": put_oi,
            "atm_iv_call": iv_call, "atm_iv_put": iv_put, "spot": 100.0, "atm_strike": 100.0,
            "total_call_oi": 50000.0, "total_put_oi": 45000.0, "max_call_oi_strike": 105.0, "max_put_oi_strike": 95.0,
        }
    return _lookup


# --- build_pre_transition_windows ---


def test_returns_six_windows_matching_the_spec_boundaries():
    candles = _full_day_candles()
    windows = build_pre_transition_windows(candles, {}, _flat_option_lookup(), [], BIN_SIZE, date(2026, 8, 27))
    assert len(windows) == 6
    assert [w.window_label for w in windows] == [f"{s:%H:%M}-{e:%H:%M}" for s, e in PRE_WINDOW_BOUNDARIES]
    assert [w.window_index for w in windows] == [1, 2, 3, 4, 5, 6]


def test_empty_input_returns_no_windows():
    import pandas as pd
    assert build_pre_transition_windows(pd.DataFrame(), {}, _flat_option_lookup(), [], BIN_SIZE, date(2026, 8, 27)) == []


def test_window_volume_sums_its_own_five_candles():
    candles = _full_day_candles()
    windows = build_pre_transition_windows(candles, {}, _flat_option_lookup(), [], BIN_SIZE, date(2026, 8, 27))
    assert windows[0].volume == pytest.approx(5 * 100)


def test_first_window_has_no_prior_option_reading_so_deltas_are_none():
    candles = _full_day_candles()
    windows = build_pre_transition_windows(candles, {}, _flat_option_lookup(), [], BIN_SIZE, date(2026, 8, 27))
    assert windows[0].pcr_change is None
    assert windows[0].call_oi_change is None
    assert windows[1].pcr_change == pytest.approx(0.0)  # constant lookup -> zero delta from window 2 onward


def test_pcr_change_reflects_a_real_move_between_windows():
    calls = {"n": 0}

    def lookup(at_time):
        calls["n"] += 1
        pcr = 0.9 if calls["n"] <= 3 else 1.3  # jumps after the 3rd call
        return {
            "pcr": pcr, "call_oi_change_near_atm": 1000.0, "put_oi_change_near_atm": 800.0,
            "atm_iv_call": 15.0, "atm_iv_put": 14.5, "spot": 100.0, "atm_strike": 100.0,
            "total_call_oi": 50000.0, "total_put_oi": 45000.0, "max_call_oi_strike": 105.0, "max_put_oi_strike": 95.0,
        }

    candles = _full_day_candles()
    windows = build_pre_transition_windows(candles, {}, lookup, [], BIN_SIZE, date(2026, 8, 27))
    assert windows[3].pcr_change == pytest.approx(1.3 - 0.9)


def test_market_regime_and_institutional_bias_populated_when_option_data_available():
    candles = _full_day_candles()
    windows = build_pre_transition_windows(candles, {}, _flat_option_lookup(), [], BIN_SIZE, date(2026, 8, 27))
    assert windows[-1].institutional_bias_label is not None
    assert windows[-1].market_regime is not None


def test_no_option_data_leaves_option_fields_none_not_fabricated():
    candles = _full_day_candles()
    windows = build_pre_transition_windows(candles, {}, lambda at: None, [], BIN_SIZE, date(2026, 8, 27))
    for w in windows:
        assert w.pcr is None
        assert w.institutional_bias_label is None
        assert w.option_pressure_score is None


# --- build_post_transition_minutes ---


def test_returns_sixteen_native_minutes_plus_the_1530_closing_snapshot():
    # _full_day_candles() extends through 15:39, so the 15:30 closing
    # candle exists -- the native run is still exactly 16 minutes
    # (15:00-15:15), with the closing snapshot appended as a 17th row.
    candles = _full_day_candles()
    pre_windows = build_pre_transition_windows(candles, {}, _flat_option_lookup(), [], BIN_SIZE, date(2026, 8, 27))
    minutes = build_post_transition_minutes(candles, {}, _flat_option_lookup(), pre_windows[-1], BIN_SIZE, date(2026, 8, 27))
    assert len(minutes) == 17
    native = minutes[:16]
    assert native[0].minute_time == "15:00"
    assert native[-1].minute_time == "15:15"
    assert [m.minute_offset for m in native] == list(range(16))
    assert all(not m.is_closing_snapshot for m in native)

    closing = minutes[16]
    assert closing.minute_time == "15:30"
    assert closing.minute_offset == 16
    assert closing.is_closing_snapshot is True


def test_closing_snapshot_omitted_when_1530_candle_not_yet_available():
    # A live in-progress session that has only reached 15:15 -- honestly
    # omits the closing checkpoint rather than fabricating one.
    rows = []
    price = 100.0
    for hh, mm_range in [(9, range(15, 60)), (10, range(60)), (11, range(60)), (12, range(60)), (13, range(60)), (14, range(60)), (15, range(16))]:
        for mm in mm_range:
            price += 0.05
            rows.append({"time": f"{hh:02d}:{mm:02d}", "o": price, "h": price + 0.5, "l": price - 0.5, "c": price, "v": 100})
    candles = make_candles(rows, tz_date="2026-08-27")
    pre_windows = build_pre_transition_windows(candles, {}, _flat_option_lookup(), [], BIN_SIZE, date(2026, 8, 27))
    minutes = build_post_transition_minutes(candles, {}, _flat_option_lookup(), pre_windows[-1], BIN_SIZE, date(2026, 8, 27))
    assert len(minutes) == 16
    assert all(not m.is_closing_snapshot for m in minutes)


# --- compute_actual_outcome_checkpoints ---


def _post_minutes_for_full_day():
    candles = _full_day_candles()
    pre_windows = build_pre_transition_windows(candles, {}, _flat_option_lookup(), [], BIN_SIZE, date(2026, 8, 27))
    return build_post_transition_minutes(candles, {}, _flat_option_lookup(), pre_windows[-1], BIN_SIZE, date(2026, 8, 27))


def test_returns_all_four_horizons_when_the_full_session_is_available():
    checkpoints = compute_actual_outcome_checkpoints(_post_minutes_for_full_day())
    assert [c.horizon_minutes for c in checkpoints] == [1, 5, 10, 15]


def test_direction_and_point_move_reflect_a_clean_up_move():
    # _full_day_candles() steps price up every minute -- a clean, real up move.
    checkpoints = compute_actual_outcome_checkpoints(_post_minutes_for_full_day())
    for c in checkpoints:
        assert c.direction == "up"
        assert c.point_move > 0
    # Longer horizons must have covered at least as much net move.
    assert checkpoints[-1].point_move >= checkpoints[0].point_move


def test_mfe_is_never_worse_than_mae_for_an_up_move():
    # For a 1-minute horizon there's only a single close, so mfe==mae==the
    # net move itself (no separate adverse point exists yet within the
    # window) -- mfe >= mae is the universally-true invariant, not mae<=0.
    checkpoints = compute_actual_outcome_checkpoints(_post_minutes_for_full_day())
    for c in checkpoints:
        assert c.mfe >= 0
        assert c.mfe >= c.mae


def test_vol_normalized_move_none_without_atr():
    checkpoints = compute_actual_outcome_checkpoints(_post_minutes_for_full_day(), atr_14=None)
    assert all(c.vol_normalized_move is None for c in checkpoints)


def test_vol_normalized_move_populated_with_atr():
    checkpoints = compute_actual_outcome_checkpoints(_post_minutes_for_full_day(), atr_14=50.0)
    assert all(c.vol_normalized_move is not None for c in checkpoints)


def test_only_offers_horizons_the_data_actually_reaches():
    # A session that only reaches 15:04 (5 native minutes: offsets 0-4)
    # should offer the 1 and 5 minute horizons, not 10 or 15.
    rows = []
    price = 100.0
    for hh, mm_range in [(9, range(15, 60)), (10, range(60)), (11, range(60)), (12, range(60)), (13, range(60)), (14, range(60)), (15, range(5))]:
        for mm in mm_range:
            price += 0.05
            rows.append({"time": f"{hh:02d}:{mm:02d}", "o": price, "h": price + 0.5, "l": price - 0.5, "c": price, "v": 100})
    candles = make_candles(rows, tz_date="2026-08-27")
    pre_windows = build_pre_transition_windows(candles, {}, _flat_option_lookup(), [], BIN_SIZE, date(2026, 8, 27))
    minutes = build_post_transition_minutes(candles, {}, _flat_option_lookup(), pre_windows[-1], BIN_SIZE, date(2026, 8, 27))
    checkpoints = compute_actual_outcome_checkpoints(minutes)
    assert [c.horizon_minutes for c in checkpoints] == [1, 5]


def test_empty_post_minutes_returns_no_checkpoints():
    assert compute_actual_outcome_checkpoints([]) == []


def test_shock_score_is_the_mean_over_the_horizon_window():
    minutes = _post_minutes_for_full_day()
    checkpoints = compute_actual_outcome_checkpoints(minutes)
    one_min = checkpoints[0]
    assert one_min.shock_score == pytest.approx(minutes[0].transition_shock_score, abs=0.1)


def test_closing_snapshot_price_change_measured_from_1515_close():
    candles = _full_day_candles()
    pre_windows = build_pre_transition_windows(candles, {}, _flat_option_lookup(), [], BIN_SIZE, date(2026, 8, 27))
    minutes = build_post_transition_minutes(candles, {}, _flat_option_lookup(), pre_windows[-1], BIN_SIZE, date(2026, 8, 27))
    closing = minutes[-1]
    assert closing.price_change == pytest.approx(closing.close - minutes[-2].close)


def test_first_minute_price_change_measured_from_last_pre_window_close():
    candles = _full_day_candles()
    pre_windows = build_pre_transition_windows(candles, {}, _flat_option_lookup(), [], BIN_SIZE, date(2026, 8, 27))
    minutes = build_post_transition_minutes(candles, {}, _flat_option_lookup(), pre_windows[-1], BIN_SIZE, date(2026, 8, 27))
    assert minutes[0].price_change == pytest.approx(minutes[0].close - pre_windows[-1].close)


def test_shock_score_is_bounded_zero_to_hundred():
    candles = _full_day_candles(step=2.0)  # exaggerated moves to stress the formula
    pre_windows = build_pre_transition_windows(candles, {}, _flat_option_lookup(), [], BIN_SIZE, date(2026, 8, 27))
    minutes = build_post_transition_minutes(candles, {}, _flat_option_lookup(), pre_windows[-1], BIN_SIZE, date(2026, 8, 27))
    for m in minutes:
        assert 0.0 <= m.transition_shock_score <= 100.0


def test_no_prior_window_means_first_minute_has_no_price_change_baseline():
    candles = _full_day_candles()
    minutes = build_post_transition_minutes(candles, {}, _flat_option_lookup(), None, BIN_SIZE, date(2026, 8, 27))
    assert minutes[0].price_change == 0.0  # honest zero, not a fabricated comparison


# --- small pure helpers ---


def test_option_pressure_score_none_when_nothing_available():
    assert _option_pressure_score(None, None, None, None) is None


def test_option_pressure_score_bounded():
    score = _option_pressure_score(pcr_change=-5.0, call_oi_change=-10000, put_oi_change=10000, iv_change=-10.0)
    assert -1.0 <= score <= 1.0


def test_news_risk_none_when_no_events_in_window():
    assert _news_risk_near([], time(14, 40), date(2026, 8, 27)) is None


def test_news_risk_scaled_from_severity():
    events = [{"severity": 5, "classified_at": datetime(2026, 8, 27, 14, 35, tzinfo=IST)}]
    assert _news_risk_near(events, time(14, 40), date(2026, 8, 27)) == 100


def test_news_risk_ignores_events_outside_the_trailing_window():
    events = [{"severity": 5, "classified_at": datetime(2026, 8, 27, 13, 0, tzinfo=IST)}]  # >30min before 14:40
    assert _news_risk_near(events, time(14, 40), date(2026, 8, 27)) is None


def test_rvol_pct_none_when_no_baseline_history():
    assert _rvol_pct(500.0, {}, 315.0, 320.0) is None
