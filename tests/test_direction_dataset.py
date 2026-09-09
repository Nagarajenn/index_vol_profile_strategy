"""Milestone 11A dataset-construction tests, including the mandatory
leakage-guard suite (Milestone 11A spec Section 15, items C/D/G):
pre-cutoff features must be bit-identical whether or not post-14:59 data
is present in the inputs, and the option lookup must never be asked for
anything later than 14:59:00.
"""

from datetime import date, time

import pandas as pd
import pytest

from market_transition.direction_dataset import (
    CHECKPOINTS,
    DECISION_CUTOFF,
    TRAJECTORY_MINUTES,
    build_decision_state,
    build_option_checkpoint_features,
    build_option_trajectory,
    build_post_cutoff_outcomes,
    build_pre_cutoff_features,
    build_underlying_checkpoint_features,
    is_baseline_usable,
    merge_pre_post,
)
from tests.fixtures.synthetic_candles import make_candles

BIN_SIZE = 1.0


def _session_candles(post_3pm: bool, tz_date: str = "2026-08-10"):
    rows = []
    price = 100.0
    hours = [(9, range(15, 60)), (10, range(60)), (11, range(60)), (12, range(60)), (13, range(60)), (14, range(60))]
    if post_3pm:
        hours.append((15, range(40)))
    for hh, mm_range in hours:
        for mm in mm_range:
            price += 0.05
            rows.append({"time": f"{hh:02d}:{mm:02d}", "o": price, "h": price + 0.3, "l": price - 0.3, "c": price, "v": 100 + mm})
    candles = make_candles(rows, tz_date=tz_date)
    candles["time"] = candles["timestamp"].dt.time
    return candles


def _strike_entry(oi=1000.0, previous_oi=800.0, volume=5000.0, last_price=100.0, iv=15.0):
    return {
        "oi": oi, "previous_oi": previous_oi, "volume": volume, "previous_volume": volume * 0.9,
        "last_price": last_price, "average_price": last_price, "top_bid_price": last_price - 0.5,
        "top_ask_price": last_price + 0.5, "top_bid_quantity": 100, "top_ask_quantity": 100,
        "implied_volatility": iv, "previous_close_price": last_price,
        "greeks": {"delta": 0.5, "gamma": 0.001, "theta": -10.0, "vega": 5.0},
    }


def _flat_chain(spot=100.0, step=1.0, n_strikes=15):
    base_strike = round(spot / step) * step
    oc = {}
    for i in range(-(n_strikes // 2), n_strikes // 2 + 1):
        strike = base_strike + i * step
        oc[str(strike)] = {"ce": _strike_entry(last_price=100.0 - i), "pe": _strike_entry(last_price=50.0 + i)}
    return {"expiry": date(2026, 8, 13), "last_price": spot, "oc": oc}


class _FakeOptionLookup:
    """Records every time argument it's called with; returns a payload for
    times at/before a configured cutoff, mirroring
    db.reader.get_option_chain_raw_near's own `fetched_at::time <=
    at_or_before` filtering -- and raises if ever asked for something
    later than DECISION_CUTOFF, so a leakage bug in the caller shows up
    immediately as a test failure rather than silently returning data."""

    def __init__(self, available_until: str = "14:59:00"):
        self.calls: list[str] = []
        self.available_until = available_until

    def __call__(self, at_or_before: str) -> dict | None:
        self.calls.append(at_or_before)
        if at_or_before > DECISION_CUTOFF.strftime("%H:%M:%S"):
            raise AssertionError(f"option_lookup_fn asked for post-cutoff time {at_or_before}")
        if at_or_before < "09:15:00":
            return None
        cutoff_time = min(at_or_before, self.available_until)
        spot = 100.0 + (int(cutoff_time[3:5]) * 0.01)
        return {"fetched_at": pd.Timestamp(f"2026-08-10 {cutoff_time}", tz="Asia/Kolkata"), "expiry": date(2026, 8, 13), "spot": spot, "raw_payload": _flat_chain(spot=spot)}


# ---------------------------------------------------------------- underlying

def test_underlying_checkpoint_features_populate_for_a_normal_session():
    out = build_underlying_checkpoint_features(_session_candles(post_3pm=False), BIN_SIZE)
    assert out["under_1459_close"] is not None
    assert out["under_1459_mom_15min"] is not None
    assert out["under_1430_close"] is not None


def test_underlying_checkpoint_features_are_bit_identical_with_or_without_post_3pm_candles():
    truncated = build_underlying_checkpoint_features(_session_candles(post_3pm=False), BIN_SIZE)
    extended = build_underlying_checkpoint_features(_session_candles(post_3pm=True), BIN_SIZE)
    assert truncated == extended


def test_underlying_checkpoint_features_empty_for_empty_candles():
    empty = pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume", "time"])
    assert build_underlying_checkpoint_features(empty, BIN_SIZE) == {}


# ------------------------------------------------------------------ options

def test_option_checkpoint_features_populate_and_never_request_past_1459():
    lookup = _FakeOptionLookup()
    out = build_option_checkpoint_features(date(2026, 8, 10), lookup)
    assert out["opt_1459_available"] is True
    assert out["opt_1459_pcr_oi"] is not None
    assert all(c <= "14:59:00" for c in lookup.calls)
    assert set(lookup.calls) == {cp.strftime("%H:%M:%S") for cp in CHECKPOINTS}


def test_option_trajectory_covers_exactly_the_last_10_minutes_and_no_later():
    lookup = _FakeOptionLookup()
    out = build_option_trajectory(lookup)
    assert set(lookup.calls) == {cp.strftime("%H:%M:%S") for cp in TRAJECTORY_MINUTES}
    assert out["traj_1450_pcr_oi"] is not None
    assert out["traj_1459_atm_straddle_value"] is not None
    # trajectory only carries the 4 lightweight fields, never the full feature set
    assert "traj_1459_call_oi_concentration" not in out


def test_option_checkpoint_marks_unavailable_when_no_snapshot_exists_at_all():
    out = build_option_checkpoint_features(date(2026, 8, 10), lambda _at_or_before: None)
    assert out["opt_1430_available"] is False
    assert out["opt_1459_available"] is False
    assert "opt_1459_pcr_oi" not in out


def test_decision_state_derives_expiry_and_days_to_expiry():
    lookup = _FakeOptionLookup()
    option_at_1459 = lookup(DECISION_CUTOFF.strftime("%H:%M:%S"))
    calendar = {date(2026, 8, 10): "weekly"}
    state = build_decision_state("NIFTY", date(2026, 8, 10), option_at_1459, calendar)
    assert state["symbol"] == "NIFTY"
    assert state["expiry_type"] == "weekly"
    assert state["days_to_expiry"] == 3
    assert state["atm_strike"] is not None


# --------------------------------------------------------------- pre/post merge

def test_build_pre_cutoff_features_returns_none_for_no_candles():
    empty = pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume", "time"])
    lookup = _FakeOptionLookup()
    assert build_pre_cutoff_features("NIFTY", date(2026, 8, 10), empty, lookup, BIN_SIZE) is None


def test_build_pre_cutoff_features_has_no_actual_outcome_keys():
    lookup = _FakeOptionLookup()
    row = build_pre_cutoff_features("NIFTY", date(2026, 8, 10), _session_candles(False), lookup, BIN_SIZE)
    assert not any(k.startswith("actual_") for k in row)


def test_build_post_cutoff_outcomes_uses_explicit_prefixed_names_not_ambiguous_ones():
    outcomes = {15: {"direction": "up", "point_move": 42.0, "pct_move": 0.17, "mfe": 50.0, "mae": -5.0}}
    post = build_post_cutoff_outcomes(outcomes)
    assert post["actual_15m_direction"] == "up"
    assert post["actual_15m_point_move"] == 42.0
    # the exact Milestone 10 bug this naming scheme prevents:
    assert "direction_15m" not in post
    assert "direction" not in post


def test_merge_pre_post_raises_on_key_collision():
    with pytest.raises(ValueError):
        merge_pre_post({"x": 1}, {"x": 2})


def test_merge_pre_post_combines_disjoint_dicts():
    merged = merge_pre_post({"under_1459_close": 100.0}, {"actual_15m_direction": "up"})
    assert merged == {"under_1459_close": 100.0, "actual_15m_direction": "up"}


# ------------------------------------------------------------- baseline usability

def test_is_baseline_usable_true_when_all_three_fields_present():
    row = {
        "opt_1459_pcr_oi": 0.9, "opt_1459_call_put_volume_imbalance": 0.1, "opt_1459_atm_straddle_change": 2.0,
    }
    assert is_baseline_usable(row)


def test_is_baseline_usable_false_when_any_field_missing():
    row = {"opt_1459_pcr_oi": 0.9, "opt_1459_call_put_volume_imbalance": None, "opt_1459_atm_straddle_change": 2.0}
    assert not is_baseline_usable(row)
    assert not is_baseline_usable({})


def test_is_baseline_usable_false_when_1459_snapshot_is_stale():
    # all three fields present and non-null, but sourced from a stale
    # (e.g. 12:47pm) fallback snapshot -- must not be treated as a real
    # 14:59 read (this is the exact Aug-18/Aug-26 case this milestone's
    # real-DB run surfaced: get_option_chain_raw_near falls back to
    # whatever existed earlier in the day when 14:30-15:15 coverage is
    # genuinely missing).
    row = {
        "opt_1459_pcr_oi": 0.9, "opt_1459_call_put_volume_imbalance": 0.1, "opt_1459_atm_straddle_change": 2.0,
        "opt_1459_stale": True,
    }
    assert not is_baseline_usable(row)


def test_is_baseline_usable_true_when_1459_snapshot_freshness_flag_is_absent_or_false():
    row = {"opt_1459_pcr_oi": 0.9, "opt_1459_call_put_volume_imbalance": 0.1, "opt_1459_atm_straddle_change": 2.0}
    assert is_baseline_usable(row)
    assert is_baseline_usable({**row, "opt_1459_stale": False})
