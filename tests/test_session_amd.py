from datetime import date

import pandas as pd
import pytest

from analytics.session_amd import (
    SWEEP_MARGIN_PCT,
    compute_session_amd_phases,
)
from tests.fixtures.synthetic_candles import make_candles

SYMBOL = "SENSEX"
TZ_DATE = "2026-08-27"
ACC_MINUTES = 30  # matches DEFAULT_ACCUMULATION_MINUTES


def _accumulation_block(low: float = 100.0, high: float = 102.0, minutes: int = ACC_MINUTES, start_hh: int = 9, start_mm: int = 15) -> list[dict]:
    """Exactly `minutes` one-minute candles from start_hh:start_mm, with the
    FIRST candle setting the exact high/low boundary and every remaining
    candle flat well inside it -- gives full, precise control over the
    resulting accumulation range for margin/trigger-boundary tests."""
    rows = [{"time": f"{start_hh:02d}:{start_mm:02d}", "o": (low + high) / 2, "h": high, "l": low, "c": (low + high) / 2, "v": 100}]
    mid = (low + high) / 2
    total_start = start_hh * 60 + start_mm
    for i in range(1, minutes):
        total = total_start + i
        hh, mm = total // 60, total % 60
        rows.append({"time": f"{hh:02d}:{mm:02d}", "o": mid, "h": mid + 0.1, "l": mid - 0.1, "c": mid, "v": 100})
    return rows


def _row(hh: int, mm: int, o: float, h: float, l: float, c: float, v: float = 100) -> dict:
    return {"time": f"{hh:02d}:{mm:02d}", "o": o, "h": h, "l": l, "c": c, "v": v}


def _candles(rows: list[dict]) -> pd.DataFrame:
    return make_candles(rows, tz_date=TZ_DATE)


def test_accumulation_still_building_when_session_hasnt_reached_the_window_end():
    # Only 15 of the required 30 minutes exist yet.
    rows = [_row(9, 15 + i, 100, 100.2, 99.8, 100) for i in range(15)]
    result = compute_session_amd_phases(SYMBOL, _candles(rows))
    assert result.accumulation is not None
    assert result.accumulation.is_complete is False
    assert result.current_phase == "Accumulating"
    assert result.narrative  # non-empty


def test_range_established_when_no_test_has_occurred_yet():
    rows = _accumulation_block()
    # Stay comfortably inside the [100,102] range (margin trigger is 99.8/102.2).
    rows += [_row(9, 45 + i, 101, 101.2, 100.8, 101) for i in range(5)]
    result = compute_session_amd_phases(SYMBOL, _candles(rows))
    assert result.accumulation.is_complete is True
    assert result.accumulation.low == pytest.approx(100.0)
    assert result.accumulation.high == pytest.approx(102.0)
    assert result.current_phase == "Range Established -- Awaiting Move"
    assert result.sweeps == []


def test_testing_range_when_a_breakout_is_still_inside_the_grace_window():
    rows = _accumulation_block()
    # A single breakout candle at 09:45, session ends right there -- still
    # ambiguous (could resolve as a sweep or a breakout later).
    rows += [_row(9, 45, 102, 102.5, 101.9, 102.4)]
    result = compute_session_amd_phases(SYMBOL, _candles(rows))
    assert result.current_phase == "Testing Range"
    assert result.sweeps == []


def test_clean_sweep_low_confirms_distribution_up():
    rows = _accumulation_block()
    # 09:45 sweeps below the range (low 99.7 <= 99.8 trigger), 09:46 closes
    # back inside -- a qualifying 2-candle reversal.
    rows += [_row(9, 45, 100, 100.1, 99.7, 99.75)]
    rows += [_row(9, 46, 99.75, 100.6, 99.7, 100.5)]
    # Sustained buy-dominant move up afterward (close == high -> mfm = +1).
    price = 100.5
    for i in range(6):
        o, c = price, price + 0.5
        rows.append(_row(9, 47 + i, o, c, o - 0.1, c))
        price = c

    result = compute_session_amd_phases(SYMBOL, _candles(rows))
    assert result.current_phase == "Distribution"
    assert len(result.sweeps) == 1
    sweep = result.sweeps[0]
    assert sweep.direction == "swept_low"
    assert sweep.extreme_price == pytest.approx(99.7)
    assert sweep.expected_distribution_direction == "up"
    assert sweep.candles_to_reverse == 2

    dist = result.distribution
    assert dist is not None
    assert dist.direction == "up"
    assert dist.net_move_points > 0
    assert dist.status == "Confirmed"
    assert dist.dominant_side_confirms is True
    assert "Distribution" in result.narrative


def test_clean_sweep_high_confirms_distribution_down():
    rows = _accumulation_block()
    rows += [_row(9, 45, 102, 102.3, 101.9, 102.25)]  # breaks 102.2 trigger
    rows += [_row(9, 46, 102.25, 102.3, 101.4, 101.5)]  # closes back inside
    price = 101.5
    for i in range(6):
        o, c = price, price - 0.5
        rows.append(_row(9, 47 + i, o, o, c, c))  # high == open, low == close -> mfm = -1 (sell-dominant)
        price = c

    result = compute_session_amd_phases(SYMBOL, _candles(rows))
    assert result.current_phase == "Distribution"
    sweep = result.sweeps[0]
    assert sweep.direction == "swept_high"
    assert sweep.expected_distribution_direction == "down"

    dist = result.distribution
    assert dist.direction == "down"
    assert dist.net_move_points < 0
    assert dist.status == "Confirmed"
    assert dist.dominant_side_confirms is True


def test_distribution_marked_failed_when_price_recrosses_the_sweep_extreme():
    rows = _accumulation_block()
    rows += [_row(9, 45, 100, 100.1, 99.7, 99.75)]
    rows += [_row(9, 46, 99.75, 100.6, 99.7, 100.5)]
    rows += [_row(9, 47, 100.5, 100.8, 100.4, 100.7)]
    # Crashes back below the sweep's own extreme (99.7) -- invalidates the setup.
    rows += [_row(9, 48, 100.7, 100.7, 99.5, 99.5)]

    result = compute_session_amd_phases(SYMBOL, _candles(rows))
    assert result.distribution is not None
    assert result.distribution.status == "Failed"


def test_genuine_breakout_without_reversal_is_not_labeled_manipulation():
    rows = _accumulation_block()
    # Breaks above the range at 09:45 and never closes back inside within
    # the 15-minute grace window (session runs to 10:05).
    price = 102.3
    for i, mm in enumerate(range(45, 65 + 1, 1)):  # 09:45 .. 10:05, in-order minute offsets past 60
        hh = 9 if mm < 60 else 10
        mm_actual = mm if mm < 60 else mm - 60
        rows.append(_row(hh, mm_actual, price, price + 0.1, price - 0.05, price + 0.05))
        price += 0.05

    result = compute_session_amd_phases(SYMBOL, _candles(rows))
    assert result.current_phase == "Breakout (not manipulation)"
    assert result.sweeps == []
    assert result.distribution is None


def test_multiple_sweeps_in_one_session_yield_no_clear_setup():
    rows = _accumulation_block()
    # Sweep #1: below the range, reverses.
    rows += [_row(9, 45, 100, 100.1, 99.7, 99.75)]
    rows += [_row(9, 46, 99.75, 100.6, 99.7, 100.5)]
    # Sweep #2: above the range, reverses.
    rows += [_row(9, 50, 101.8, 102.3, 101.7, 102.25)]
    rows += [_row(9, 51, 102.25, 102.3, 101.0, 101.5)]

    result = compute_session_amd_phases(SYMBOL, _candles(rows))
    assert len(result.sweeps) == 2
    assert result.current_phase == "No Clear Setup"
    assert result.distribution is None


def test_empty_candles_returns_a_safe_default():
    result = compute_session_amd_phases(SYMBOL, pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"]))
    assert result.as_of is None
    assert result.accumulation is None
    assert result.narrative == "No candles yet today."


def test_sweep_margin_is_a_documented_starting_default():
    # Not a behavioral test -- just pins the constant so an accidental
    # tuning change doesn't silently drift without a test failure to flag it.
    assert SWEEP_MARGIN_PCT == pytest.approx(0.10)
