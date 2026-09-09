"""Milestone 11C tests: candidate universe construction, ATM+/-5,
CE/PE handling, moneyness, spread/spread%, missing bid/ask handling,
stale-data rejection, post-cutoff outcome measurement (MFE/MAE/exit
prices), and underlying outcome extraction.
"""

from datetime import date, time

import pandas as pd
import pytest

from market_transition.option_features_11c import (
    ATM_WINDOW_STRIKES,
    build_candidate_universe,
    build_post_cutoff_option_trajectory,
    compute_realized_option_outcome,
    compute_underlying_outcome,
)
from option_chain.snapshot_features import StrikeDetail
from tests.fixtures.synthetic_candles import make_candles


def _strike_entry(last_price=100.0, bid=None, ask=None, iv=15.0, delta=0.5, theta=-10.0):
    b = bid if bid is not None else last_price - 0.5
    a = ask if ask is not None else last_price + 0.5
    return {
        "oi": 1000.0, "previous_oi": 800.0, "volume": 5000.0, "previous_volume": 4500.0,
        "last_price": last_price, "average_price": last_price, "top_bid_price": b, "top_ask_price": a,
        "top_bid_quantity": 100, "top_ask_quantity": 100, "implied_volatility": iv,
        "previous_close_price": last_price,
        "greeks": {"delta": delta, "gamma": 0.001, "theta": theta, "vega": 5.0},
    }


def _flat_chain(spot=100.0, step=50.0, n_strikes=15, overrides=None):
    overrides = overrides or {}
    base = round(spot / step) * step
    oc = {}
    for i in range(-(n_strikes // 2), n_strikes // 2 + 1):
        strike = base + i * step
        ce = dict(overrides.get((strike, "ce"), _strike_entry(last_price=max(spot - strike, 1.0))))
        pe = dict(overrides.get((strike, "pe"), _strike_entry(last_price=max(strike - spot, 1.0))))
        oc[str(strike)] = {"ce": ce, "pe": pe}
    return {"expiry": "2026-08-13", "last_price": spot, "oc": oc}


def _option_row(spot=100.0, step=50.0, fetched_at=None, expiry=date(2026, 8, 13), overrides=None):
    return {
        "fetched_at": fetched_at or pd.Timestamp("2026-08-10 14:59:00", tz="Asia/Kolkata"),
        "expiry": expiry, "spot": spot, "raw_payload": _flat_chain(spot, step, overrides=overrides),
    }


# ------------------------------------------------------------- candidate universe

def test_build_candidate_universe_returns_atm_pm_5_both_legs():
    candidates, rejection = build_candidate_universe("NIFTY", date(2026, 8, 10), _option_row(), strike_step=50.0)
    assert rejection is None
    strikes = sorted({c.strike for c in candidates})
    assert len(strikes) == 2 * ATM_WINDOW_STRIKES + 1
    assert {c.option_type for c in candidates} == {"CE", "PE"}


def test_build_candidate_universe_rejects_missing_snapshot():
    candidates, rejection = build_candidate_universe("NIFTY", date(2026, 8, 10), None, strike_step=50.0)
    assert candidates == []
    assert rejection == "NO_SNAPSHOT"


def test_build_candidate_universe_rejects_stale_snapshot():
    stale_row = _option_row(fetched_at=pd.Timestamp("2026-08-10 12:00:00", tz="Asia/Kolkata"))
    candidates, rejection = build_candidate_universe("NIFTY", date(2026, 8, 10), stale_row, strike_step=50.0)
    assert candidates == []
    assert rejection == "STALE_SNAPSHOT"


def test_moneyness_sign_convention_ce_vs_pe():
    candidates, _ = build_candidate_universe("NIFTY", date(2026, 8, 10), _option_row(spot=100.0), strike_step=50.0)
    otm_ce = next(c for c in candidates if c.option_type == "CE" and c.atm_offset == 1)
    itm_ce = next(c for c in candidates if c.option_type == "CE" and c.atm_offset == -1)
    otm_pe = next(c for c in candidates if c.option_type == "PE" and c.atm_offset == -1)
    itm_pe = next(c for c in candidates if c.option_type == "PE" and c.atm_offset == 1)
    assert otm_ce.moneyness > 0
    assert itm_ce.moneyness < 0
    assert otm_pe.moneyness > 0
    assert itm_pe.moneyness < 0


def test_spread_and_spread_pct_computed_correctly():
    overrides = {(100.0, "ce"): _strike_entry(last_price=10.0, bid=9.0, ask=11.0)}
    candidates, _ = build_candidate_universe("NIFTY", date(2026, 8, 10), _option_row(overrides=overrides), strike_step=50.0)
    atm_ce = next(c for c in candidates if c.option_type == "CE" and c.strike == 100.0)
    assert atm_ce.spread == pytest.approx(2.0)
    assert atm_ce.spread_pct == pytest.approx(2.0 / 11.0 * 100)


def test_missing_bid_ask_marked_missing_quote():
    bad_entry = _strike_entry(last_price=10.0)
    bad_entry["top_bid_price"] = None
    bad_entry["top_ask_price"] = None
    overrides = {(100.0, "ce"): bad_entry}
    candidates, _ = build_candidate_universe("NIFTY", date(2026, 8, 10), _option_row(overrides=overrides), strike_step=50.0)
    atm_ce = next(c for c in candidates if c.option_type == "CE" and c.strike == 100.0)
    assert atm_ce.data_quality == "MISSING_QUOTE"
    assert atm_ce.spread is None


def test_degenerate_greeks_flagged_not_silently_patched():
    zero_greeks_entry = _strike_entry(last_price=10.0, delta=0.0, theta=0.0)
    zero_greeks_entry["greeks"] = {"delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0}
    overrides = {(100.0, "ce"): zero_greeks_entry}
    candidates, _ = build_candidate_universe("NIFTY", date(2026, 8, 10), _option_row(overrides=overrides), strike_step=50.0)
    atm_ce = next(c for c in candidates if c.option_type == "CE" and c.strike == 100.0)
    assert atm_ce.data_quality == "DEGENERATE_GREEKS"
    assert atm_ce.delta == 0.0  # not imputed/patched -- disclosed as-is


# -------------------------------------------------------------- realized outcome

def test_compute_realized_option_outcome_exit_at_bid_not_ltp():
    trajectory = [
        (time(15, 0), StrikeDetail(100.0, "CE", ltp=12.0, volume=1, oi=1, oi_change=0, iv=15, bid=10.0, ask=13.0, bid_qty=1, ask_qty=1, delta=0.5, gamma=0, theta=0, vega=0)),
        (time(15, 5), None),
        (time(15, 10), None),
        (time(15, 15), StrikeDetail(100.0, "CE", ltp=14.0, volume=1, oi=1, oi_change=0, iv=15, bid=13.0, ask=15.0, bid_qty=1, ask_qty=1, delta=0.5, gamma=0, theta=0, vega=0)),
    ]
    outcome = compute_realized_option_outcome(entry_ask=11.0, trajectory=trajectory)
    assert outcome["exits"]["15:00"]["exit_bid"] == 10.0  # bid, not ltp=12.0
    assert outcome["final_pnl"] == pytest.approx(2.0)  # 13.0 - 11.0
    assert outcome["mfe_pct"] == pytest.approx((13.0 - 11.0) / 11.0 * 100)
    assert outcome["mae_pct"] == pytest.approx((10.0 - 11.0) / 11.0 * 100)
    assert outcome["time_to_mfe"] == "15:15"
    assert outcome["time_to_mae"] == "15:00"


def test_compute_realized_option_outcome_handles_all_missing_gracefully():
    trajectory = [(time(15, 0), None), (time(15, 5), None), (time(15, 10), None), (time(15, 15), None)]
    outcome = compute_realized_option_outcome(entry_ask=11.0, trajectory=trajectory)
    assert outcome["final_pnl"] is None
    assert outcome["mfe_pct"] is None
    assert outcome["mae_pct"] is None


# ---------------------------------------------------------------- underlying outcome

def _candles_with_time(rows):
    c = make_candles(rows, tz_date="2026-08-10")
    c["time"] = c["timestamp"].dt.time
    return c


def test_underlying_outcome_final_move_and_direction():
    rows = [
        {"time": "14:59", "o": 100, "h": 100.2, "l": 99.8, "c": 100.0, "v": 10},
        {"time": "15:00", "o": 100, "h": 100.5, "l": 99.9, "c": 100.5, "v": 10},
        {"time": "15:05", "o": 100.5, "h": 101.5, "l": 100.4, "c": 101.5, "v": 10},
        {"time": "15:10", "o": 101.5, "h": 101.6, "l": 101.0, "c": 101.0, "v": 10},
        {"time": "15:15", "o": 101.0, "h": 101.2, "l": 100.8, "c": 101.2, "v": 10},
    ]
    outcome = compute_underlying_outcome(_candles_with_time(rows))
    assert outcome["baseline_1459"] == pytest.approx(100.0)
    assert outcome["final_move"] == pytest.approx(1.2)
    assert outcome["direction"] == "up"
    assert outcome["max_favorable_up_move"] == pytest.approx(1.5)  # 101.5 - 100.0
