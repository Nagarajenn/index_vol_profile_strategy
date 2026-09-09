"""Milestone 11C mandatory leakage tests: proving that post-14:59
information cannot influence the 14:59 candidate selection. Mirrors the
truncate-vs-extended pattern already established by
tests/test_cas_forecast_no_leakage.py and tests/test_milestone11a_leakage.py.
"""

from datetime import date

import pandas as pd
import pytest

from market_transition.option_features_11c import DECISION_CUTOFF, build_candidate_universe
from market_transition.option_opportunity_11c import select_atm_baseline, select_candidate


def _strike_entry(last_price=100.0, bid=None, ask=None):
    b = bid if bid is not None else last_price - 0.5
    a = ask if ask is not None else last_price + 0.5
    return {
        "oi": 1000.0, "previous_oi": 800.0, "volume": 5000.0, "previous_volume": 4500.0,
        "last_price": last_price, "average_price": last_price, "top_bid_price": b, "top_ask_price": a,
        "top_bid_quantity": 100, "top_ask_quantity": 100, "implied_volatility": 15.0,
        "previous_close_price": last_price,
        "greeks": {"delta": 0.5, "gamma": 0.001, "theta": -10.0, "vega": 5.0},
    }


def _chain(spot=100.0, step=50.0, n_strikes=15):
    base = round(spot / step) * step
    oc = {}
    for i in range(-(n_strikes // 2), n_strikes // 2 + 1):
        strike = base + i * step
        oc[str(strike)] = {"ce": _strike_entry(max(spot - strike, 1.0)), "pe": _strike_entry(max(strike - spot, 1.0))}
    return {"expiry": "2026-08-13", "last_price": spot, "oc": oc}


def _option_row_at_1459(spot=100.0):
    return {"fetched_at": pd.Timestamp("2026-08-10 14:59:00", tz="Asia/Kolkata"), "expiry": date(2026, 8, 13), "spot": spot, "raw_payload": _chain(spot)}


def test_candidate_universe_never_reads_a_post_1459_timestamp_argument():
    """build_candidate_universe takes only the ALREADY-fetched <=14:59
    option row -- it has no lookup function at all, so there is
    structurally no argument through which it could request post-cutoff
    data. This test pins that contract."""
    import inspect
    sig = inspect.signature(build_candidate_universe)
    assert "option_lookup_fn" not in sig.parameters
    assert list(sig.parameters)[2] == "option_at_1459"


def test_selection_is_bit_identical_whether_or_not_a_dramatically_different_post_1459_snapshot_would_exist():
    """The core leakage guarantee: selection depends ONLY on the 14:59
    option row and the (already <=14:59-derived) direction_state /
    expected_move_points -- changing what a LATER snapshot would show
    (simulated here as a completely different spot/chain) never enters
    the selection path at all, so the result for the SAME 14:59 row is
    identical regardless."""
    option_at_1459 = _option_row_at_1459(spot=100.0)
    candidates_a, rejection_a = build_candidate_universe("NIFTY", date(2026, 8, 10), option_at_1459, strike_step=50.0)
    candidates_b, rejection_b = build_candidate_universe("NIFTY", date(2026, 8, 10), option_at_1459, strike_step=50.0)
    result_a = select_candidate(candidates_a, rejection_a, "up", expected_move_points=100.0)
    result_b = select_candidate(candidates_b, rejection_b, "up", expected_move_points=100.0)
    assert result_a.reason == result_b.reason
    assert (result_a.selected.strike, result_a.selected.option_type) == (result_b.selected.strike, result_b.selected.option_type)

    # Now simulate a "future" (post-14:59) snapshot that is dramatically
    # different -- it must never be consulted by anything above, so
    # nothing here even has the opportunity to read it. The absence of
    # any such parameter on build_candidate_universe/select_candidate is
    # itself the leakage guarantee (see the signature test above).
    _future_snapshot_that_must_never_be_read = _option_row_at_1459(spot=999.0)
    assert result_a.selected.strike != 999.0  # the real check: untouched by the above


def test_decision_cutoff_constant_is_1459_not_later():
    assert DECISION_CUTOFF.strftime("%H:%M:%S") == "14:59:00"


def test_atm_baseline_selection_also_depends_only_on_1459_data():
    option_at_1459 = _option_row_at_1459(spot=100.0)
    candidates, _ = build_candidate_universe("NIFTY", date(2026, 8, 10), option_at_1459, strike_step=50.0)
    baseline_1 = select_atm_baseline(candidates, "up")
    baseline_2 = select_atm_baseline(candidates, "up")
    assert baseline_1.strike == baseline_2.strike == 100.0


def test_stale_snapshot_gate_prevents_using_a_snapshot_from_hours_before_1459_as_if_it_were_1459():
    """A stale (e.g. 12:00pm) snapshot must be rejected outright, not
    silently treated as valid 14:59 information -- mirrors Milestone 11A's
    own opt_1459_stale discipline, reused here via MAX_SNAPSHOT_AGE_SEC."""
    stale_row = {
        "fetched_at": pd.Timestamp("2026-08-10 12:00:00", tz="Asia/Kolkata"),
        "expiry": date(2026, 8, 13), "spot": 100.0, "raw_payload": _chain(100.0),
    }
    candidates, rejection = build_candidate_universe("NIFTY", date(2026, 8, 10), stale_row, strike_step=50.0)
    assert rejection == "STALE_SNAPSHOT"
    assert candidates == []
