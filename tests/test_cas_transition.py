from datetime import date

import pandas as pd
import pytest

from market_transition.cas_transition import build_cas_daily_transition, extract_cas_transition_record, window_volume
from tests.fixtures.synthetic_candles import make_candles

BIN_SIZE = 25.0


def _session(prices: dict[str, float], tz_date: str = "2026-08-10") -> pd.DataFrame:
    rows = [{"time": t, "o": p, "h": p + 1, "l": p - 1, "c": p, "v": 100} for t, p in prices.items()]
    return make_candles(rows, tz_date=tz_date)


def _prewindow_and_postwindow(pre_start=100.0, pre_end=110.0, post_end=120.0, close_time="15:39") -> dict[str, float]:
    return {
        "09:15": pre_start,
        "14:30": pre_start,
        "14:45": (pre_start + pre_end) / 2,
        "14:59": pre_end,
        "15:00": pre_end,
        "15:20": (pre_end + post_end) / 2,
        close_time: post_end,
    }


def test_none_when_no_pre_window_data():
    # Session ends before 14:30 -- no pre-window candles at all.
    candles = _session({"09:15": 100.0, "14:00": 101.0})
    record = extract_cas_transition_record("NIFTY", date(2026, 8, 10), candles, None, {}, BIN_SIZE, None)
    assert record is None


def test_none_when_no_post_window_data():
    # Session ends right at 14:59 -- no post-window candles at all.
    candles = _session({"09:15": 100.0, "14:30": 100.0, "14:59": 105.0})
    record = extract_cas_transition_record("NIFTY", date(2026, 8, 10), candles, None, {}, BIN_SIZE, None)
    assert record is None


def test_continuation_when_both_windows_trend_same_direction():
    prices = _prewindow_and_postwindow(pre_start=100.0, pre_end=110.0, post_end=130.0)
    candles = _session(prices)
    record = extract_cas_transition_record("NIFTY", date(2026, 8, 10), candles, None, {}, BIN_SIZE, None)
    assert record is not None
    assert record.outcome.outcome == "continuation"
    assert record.outcome.transition_direction == "up"


def test_reversal_when_windows_trend_opposite_directions():
    prices = _prewindow_and_postwindow(pre_start=100.0, pre_end=110.0, post_end=90.0)
    candles = _session(prices)
    record = extract_cas_transition_record("NIFTY", date(2026, 8, 10), candles, None, {}, BIN_SIZE, None)
    assert record is not None
    assert record.outcome.outcome == "reversal"


def test_neutral_when_pre_window_trend_is_flat():
    prices = _prewindow_and_postwindow(pre_start=100.0, pre_end=100.005, post_end=130.0)
    candles = _session(prices)
    record = extract_cas_transition_record("NIFTY", date(2026, 8, 10), candles, None, {}, BIN_SIZE, None)
    assert record is not None
    assert record.outcome.outcome == "neutral"


def test_market_close_uses_actual_last_candle_not_a_fixed_time():
    # One session's last candle is 15:39 (new CAS-era close); confirm
    # market_close reflects that actual last price, not a hardcoded 15:30.
    prices = _prewindow_and_postwindow(pre_start=100.0, pre_end=110.0, post_end=155.0, close_time="15:39")
    candles = _session(prices)
    record = extract_cas_transition_record("NIFTY", date(2026, 8, 10), candles, None, {}, BIN_SIZE, None)
    assert record is not None
    assert record.outcome.market_close == pytest.approx(155.0)


def test_close_1459_is_the_pivot_close():
    prices = _prewindow_and_postwindow(pre_start=100.0, pre_end=112.5, post_end=130.0)
    candles = _session(prices)
    record = extract_cas_transition_record("NIFTY", date(2026, 8, 10), candles, None, {}, BIN_SIZE, None)
    assert record is not None
    assert record.outcome.close_1459 == pytest.approx(112.5)


def test_stray_post_close_candle_does_not_corrupt_market_close():
    # A zero-volume echo candle after the real 15:40 close (observed in
    # real data) must never be picked up as market_close.
    rows = {
        "14:31": 100.0, "14:45": 105.0, "14:59": 110.0,
        "15:00": 110.0, "15:20": 115.0, "15:39": 120.0,
        "16:25": 999.0,  # stray post-close echo -- must be excluded
    }
    candles = _session(rows)
    record = extract_cas_transition_record("NIFTY", date(2026, 8, 10), candles, None, {}, BIN_SIZE, None)
    assert record is not None
    assert record.outcome.market_close == pytest.approx(120.0)


def test_window_volume_sums_only_within_bounds():
    from datetime import time

    rows = [
        {"time": "14:31", "o": 100, "h": 100, "l": 100, "c": 100, "v": 10},
        {"time": "14:45", "o": 100, "h": 100, "l": 100, "c": 100, "v": 20},
        {"time": "14:59", "o": 100, "h": 100, "l": 100, "c": 100, "v": 30},
        {"time": "15:20", "o": 100, "h": 100, "l": 100, "c": 100, "v": 999},  # outside the window
    ]
    candles = make_candles(rows)
    total = window_volume(candles, time(14, 31), time(14, 59))
    assert total == pytest.approx(60.0)


def test_window_volume_none_when_no_candles_in_range():
    from datetime import time

    candles = _session({"09:15": 100.0})
    assert window_volume(candles, time(14, 31), time(14, 59)) is None


def _full_minute_session(pre_start=100.0, pre_end=110.0, post_end=130.0, stuck_run_at=None) -> pd.DataFrame:
    """Per-minute candles across 14:31-15:39 -- needed for the stuck-candle
    detector, which requires several consecutive real rows, not just the
    3-point sparse fixture used elsewhere in this file."""
    rows = []
    # pre-window: 14:31..14:59, 29 candles, linear ramp
    for i in range(29):
        hh, mm = (14, 31 + i) if 31 + i < 60 else (15, 31 + i - 60)
        price = pre_start + (pre_end - pre_start) * i / 28
        rows.append({"time": f"{hh:02d}:{mm:02d}", "o": price, "h": price + 0.5, "l": price - 0.5, "c": price, "v": 100})
    # post-window: 15:00..15:39, 40 candles, linear ramp from pre_end to post_end
    for i in range(40):
        hh, mm = 15, i
        price = pre_end + (post_end - pre_end) * i / 39
        vol = 100
        rows.append({"time": f"{hh:02d}:{mm:02d}", "o": price, "h": price + 0.5, "l": price - 0.5, "c": price, "v": vol})
    df = make_candles(rows)
    if stuck_run_at is not None:
        start_idx, run_len = stuck_run_at
        stuck_close = df.loc[start_idx, "close"]
        df.loc[start_idx : start_idx + run_len - 1, "close"] = stuck_close
        df.loc[start_idx : start_idx + run_len - 1, "volume"] = 999_999_999
    return df


def test_build_cas_daily_transition_basic_fields():
    candles = _full_minute_session(pre_start=100.0, pre_end=110.0, post_end=130.0)
    result = build_cas_daily_transition("NIFTY", date(2026, 8, 10), candles, None, {}, BIN_SIZE, "weekly")
    assert result is not None
    assert result.symbol == "NIFTY"
    assert result.conclusion == "continuation"
    assert result.pre_direction == "up"
    assert result.post_direction == "up"
    assert result.expiry_type == "weekly"
    assert result.data_quality_flag is None
    assert result.pre_window_volume == pytest.approx(29 * 100)
    # Post-window volume only sums through 15:14 (POST_VOLUME_RELIABLE_END)
    # -- 15:00 through 15:14 inclusive is 15 one-minute candles, not the
    # full 40-candle 15:00-15:39 window used for the price/outcome call.
    assert result.post_window_pre_auction_volume == pytest.approx(15 * 100)


def test_build_cas_daily_transition_passes_through_old_outcome_and_option_context():
    candles = _full_minute_session()
    result = build_cas_daily_transition(
        "NIFTY", date(2026, 8, 10), candles, None, {}, BIN_SIZE, None,
        old_outcome="neutral", old_outcome_magnitude=1.5,
        option_context={"pcr": 0.85, "bias_label": "Mildly Bearish", "bias_score": -1},
    )
    assert result is not None
    assert result.old_methodology_outcome == "neutral"
    assert result.old_methodology_outcome_magnitude == pytest.approx(1.5)
    assert result.pcr_1459 == pytest.approx(0.85)
    assert result.institutional_bias_label_1459 == "Mildly Bearish"
    assert result.institutional_bias_score_1459 == -1


def test_points_move_uses_best_print_not_just_close_to_close():
    # Post-window closes only modestly up, but spikes much higher mid-window
    # -- points_move should reflect the actual high reached, not the close.
    rows = []
    for i in range(29):
        hh, mm = 14, 31 + i
        rows.append({"time": f"{hh:02d}:{mm:02d}", "o": 100, "h": 100.5, "l": 99.5, "c": 100, "v": 100})
    post_prices = [110, 112, 130, 111, 111.5]  # spikes to 130 mid-window, closes near 111.5
    for i, p in enumerate(post_prices):
        rows.append({"time": f"15:{i:02d}", "o": p, "h": p + 1, "l": p - 1, "c": p, "v": 100})
    candles = make_candles(rows)

    result = build_cas_daily_transition("NIFTY", date(2026, 8, 10), candles, None, {}, BIN_SIZE, None)
    assert result is not None
    assert result.post_direction == "up"
    assert result.close_1459 == pytest.approx(100.0)
    # high reached (131) minus close_1459 (100, flat pre-window)
    assert result.post_window_points_move == pytest.approx(131 - 100)


def test_points_move_none_direction_is_zero():
    candles = _full_minute_session(pre_start=100.0, pre_end=100.0, post_end=100.0)
    result = build_cas_daily_transition("NIFTY", date(2026, 8, 10), candles, None, {}, BIN_SIZE, None)
    assert result is not None
    if result.pre_direction == "flat":
        assert result.pre_window_points_move == 0.0


def test_build_cas_daily_transition_flags_stuck_candle_run():
    # Real-world case: 10 consecutive post-window candles frozen at one
    # (close, volume) pair -- discovered in actual NIFTY data.
    candles = _full_minute_session(stuck_run_at=(35, 10))  # somewhere in the post-window rows
    result = build_cas_daily_transition("NIFTY", date(2026, 8, 10), candles, None, {}, BIN_SIZE, None)
    assert result is not None
    assert result.data_quality_flag == "stuck_candle_run_detected"


def test_post_auction_frozen_volume_excluded_and_does_not_false_flag():
    # Reproduces the real pattern found 2026-08-21: price keeps moving
    # genuinely from 15:15-15:38, but volume is frozen at one value the
    # whole time. Must NOT trip the stuck-candle detector (this is expected,
    # not an anomaly) and must NOT be included in post_window_pre_auction_volume.
    rows = []
    for i in range(29):
        hh, mm = 14, 31 + i
        rows.append({"time": f"{hh:02d}:{mm:02d}", "o": 100, "h": 100.5, "l": 99.5, "c": 100 + i * 0.1, "v": 100})
    for i in range(15):  # 15:00-15:14, reliable, varying volume
        rows.append({"time": f"15:{i:02d}", "o": 110, "h": 110.5, "l": 109.5, "c": 110 + i * 0.2, "v": 200 + i * 10})
    for i in range(24):  # 15:15-15:38, price moves but volume frozen at 5705
        mm = 15 + i
        rows.append({"time": f"15:{mm:02d}", "o": 113, "h": 113.5, "l": 112.5, "c": 113 + i * 0.05, "v": 5705})
    candles = make_candles(rows)

    result = build_cas_daily_transition("NIFTY", date(2026, 8, 10), candles, None, {}, BIN_SIZE, None)
    assert result is not None
    assert result.data_quality_flag is None
    # Only the 15 reliable minutes (200..340 step 10) should be summed.
    assert result.post_window_pre_auction_volume == pytest.approx(sum(200 + i * 10 for i in range(15)))
    # Price direction still reflects the genuine move all the way to 15:38/15:39.
    assert result.post_direction == "up"


def test_build_cas_daily_transition_no_flag_for_short_repeats():
    # A couple of coincidentally-equal candles (below STUCK_CANDLE_MIN_RUN)
    # must not trip the detector -- real quiet minutes can share a price.
    candles = _full_minute_session(stuck_run_at=(35, 2))
    result = build_cas_daily_transition("NIFTY", date(2026, 8, 10), candles, None, {}, BIN_SIZE, None)
    assert result is not None
    assert result.data_quality_flag is None
