"""12E-option-audit-v1: response economics, attribution, direction measurement and isolation."""

from pathlib import Path

import pytest

from option_audit_12e import VERSION, density
from option_audit_12e import loss_attribution as LA
from option_audit_12e import market_state as MS
from option_audit_12e import trade_diagnostic as TD
from option_audit_12e.config import (ATM, DEFAULT, FAR_OTM, ITM, IV_HEADWIND, IV_NEUTRAL,
                                     IV_TAILWIND, IV_UNKNOWN, NEAR_ATM, RANGE, REVERSING,
                                     TRENDING_DOWN, TRENDING_UP, UNKNOWN)

ROOT = Path(__file__).resolve().parent.parent
STRIKE = 23250.0


def lg(bid, ask, iv=12.0, delta=-0.5, theta=-8.0, greeks=True):
    return dict(bid=bid, ask=ask, mid=(bid + ask) / 2, ltp=bid,
                spread=ask - bid, spread_pct=(ask - bid) / ((bid + ask) / 2) * 100,
                bid_qty=100, ask_qty=100, volume=1000, oi=5000,
                iv=iv if greeks else None, delta=delta if greeks else None,
                gamma=0.001 if greeks else None, theta=theta if greeks else None,
                vega=1.0 if greeks else None, greeks_status="VALID" if greeks else "UNAVAILABLE")


def series(spec: dict, side="PE", strike=STRIKE):
    """{'09:30': (spot, bid, ask[, iv]), ...}"""
    out = {}
    for m, v in spec.items():
        spot, bid, ask = v[0], v[1], v[2]
        iv = v[3] if len(v) > 3 else 12.0
        out[m] = dict(spot=spot, expiry="2026-09-24", legs={(side, strike): lg(bid, ask, iv=iv)})
    return out


def sig(minute="09:30", side="PE", exit_minute=None, **over):
    base = dict(signal_id="s1", market="NIFTY", session_date="2026-09-24", signal_minute=minute,
                direction="BUY_PE" if side == "PE" else "BUY_CE", side=side, strike=STRIKE,
                contract="c", confidence="STRONG", quantity=65, exit_minute=exit_minute,
                hold_minutes=5, exit_reason="POSITION_SIGNAL", mfe_per_unit=None, mae_per_unit=None,
                final_pnl_per_unit=None, final_pnl=None, final_pnl_pct=None)
    return {**base, **over}


# ================================================================ prices and greeks
def test_entry_is_ask_exit_is_bid_and_both_are_recorded():
    s = series({"09:30": (23250, 99.0, 101.0), "09:35": (23200, 120.0, 122.0)})
    r = TD.build(s, sig(exit_minute="09:35"))
    assert r["entry_ask"] == 101.0 and r["entry_bid"] == 99.0
    assert r["exit_bid"] == 120.0 and r["exit_ask"] == 122.0


def test_missing_greeks_stay_none_and_are_never_zero():
    s = {"09:30": dict(spot=23250, expiry="x", legs={("PE", STRIKE): lg(99.0, 101.0, greeks=False)})}
    r = TD.build(s, sig())
    for f in ("entry_delta", "entry_iv", "entry_theta", "entry_gamma", "entry_vega"):
        assert r[f] is None, f
    assert r["greeks_status"] == "UNAVAILABLE"


def test_a_horizon_beyond_the_data_is_none_not_clipped():
    s = series({"09:30": (23250, 99.0, 101.0), "09:31": (23240, 102.0, 104.0)})
    r = TD.build(s, sig())
    assert r["und_1m_pct"] is not None
    assert r["und_10m_pct"] is None and r["opt_10m_pct"] is None


# ================================================================ direction, from the underlying
def test_direction_is_measured_from_spot_not_from_the_option():
    """A PE whose premium ticks up while spot rises must NOT count as direction-correct."""
    s = series({"09:30": (23250, 99.0, 101.0), "09:31": (23300, 110.0, 112.0)})
    r = TD.build(s, sig())
    assert r["und_1m_pct"] > 0
    assert r["und_direction_ok_1m"] is False      # spot went UP; a PE wanted it down
    assert r["opt_profitable_1m"] is True         # the option still happened to be worth more


def test_a_move_inside_the_flat_band_is_unmeasurable_not_wrong():
    s = series({"09:30": (23250.0, 99.0, 101.0), "09:31": (23250.5, 99.0, 101.0)})
    r = TD.build(s, sig())
    assert r["und_direction_ok_1m"] is None       # 0.002% is not a direction


def test_pe_direction_correct_when_spot_falls():
    s = series({"09:30": (23250, 99.0, 101.0), "09:33": (23150, 150.0, 152.0)})
    r = TD.build(s, sig())
    assert r["und_direction_ok_3m"] is True


# ================================================================ response economics
def test_theoretical_elasticity_is_delta_times_spot_over_premium():
    s = series({"09:30": (23250, 99.0, 101.0), "09:33": (23150, 150.0, 152.0)})
    r = TD.build(s, sig())
    expected = abs(-0.5) * 23250 / 100.0          # mid = 100
    assert r["theoretical_elasticity_3m"] == pytest.approx(expected, rel=1e-3)


def test_response_efficiency_is_about_one_when_the_premium_moves_as_delta_implies():
    """Spot -100 pts on a -0.5 delta should add ~50 to a 100-premium option: +50%."""
    s = series({"09:30": (23250, 99.0, 101.0), "09:33": (23150, 149.0, 151.0)})
    r = TD.build(s, sig())
    assert r["response_efficiency_3m"] == pytest.approx(1.0, abs=0.06)


def test_a_premium_that_barely_moves_shows_low_efficiency():
    s = series({"09:30": (23250, 99.0, 101.0), "09:33": (23150, 104.0, 106.0)})
    r = TD.build(s, sig())
    assert r["response_efficiency_3m"] < DEFAULT.weak_response_efficiency


def test_no_ratio_is_reported_when_the_underlying_barely_moved():
    """Dividing an option move by a 0.01% wobble produces a number, not a measurement."""
    s = series({"09:30": (23250.0, 99.0, 101.0), "09:33": (23251.0, 120.0, 122.0)})
    r = TD.build(s, sig())
    assert r["response_ratio_3m"] is None and r["response_efficiency_3m"] is None


# ================================================================ strike bands and IV
def test_strike_bands_respect_the_side():
    """A strike ABOVE spot is ITM for a put and OTM for a call."""
    assert TD.strike_band(23300.0, 23250.0, "PE")[2] == ITM
    assert TD.strike_band(23300.0, 23250.0, "CE")[2] in (NEAR_ATM, "MODERATELY_OTM")
    assert TD.strike_band(23250.0, 23250.0, "PE")[2] == ATM
    assert TD.strike_band(26000.0, 23250.0, "CE")[2] == FAR_OTM
    assert TD.strike_band(None, 23250.0, "PE")[2] == "UNKNOWN"


def test_falling_iv_is_a_headwind_for_a_long_option_of_either_side():
    assert TD.iv_label(-5.0, "PE") == IV_HEADWIND
    assert TD.iv_label(-5.0, "CE") == IV_HEADWIND
    assert TD.iv_label(5.0, "PE") == IV_TAILWIND
    assert TD.iv_label(0.1, "PE") == IV_NEUTRAL
    assert TD.iv_label(None, "PE") == IV_UNKNOWN


# ================================================================ execution economics
def test_mid_to_mid_and_ask_to_bid_are_reported_separately():
    s = series({"09:30": (23250, 98.0, 102.0), "09:35": (23150, 108.0, 112.0)})
    r = TD.build(s, sig(exit_minute="09:35", final_pnl_per_unit=6.0))
    assert r["mid_to_mid_per_unit"] == pytest.approx(10.0)      # 110 - 100
    assert r["ask_to_bid_per_unit"] == pytest.approx(6.0)       # 108 - 102
    assert r["execution_friction_per_unit"] == pytest.approx(4.0)


def test_theta_is_scaled_to_the_holding_period_not_a_whole_day():
    s = series({"09:30": (23250, 99.0, 101.0), "09:35": (23150, 120.0, 122.0)})
    r = TD.build(s, sig(exit_minute="09:35", hold_minutes=5, final_pnl_per_unit=19.0))
    assert r["theta_estimate_per_unit"] == pytest.approx(-8.0 * 5 / 375)
    assert abs(r["theta_estimate_per_unit"]) < 0.2              # a 5-minute scalp sees very little


# ================================================================ market state (causal)
def test_market_state_uses_only_past_minutes():
    s = series({"09:20": (23300, 99, 101), "09:30": (23200, 99, 101), "09:40": (23100, 99, 101)})
    now = MS.classify(s, "09:30")
    truncated = MS.classify({k: v for k, v in s.items() if k <= "09:30"}, "09:30")
    assert now == truncated


def test_trending_and_range_and_reversing_are_distinguished():
    down = series({"09:20": (23300, 99, 101), "09:27": (23200, 99, 101), "09:30": (23180, 99, 101)})
    assert MS.classify(down, "09:30")["state"] == TRENDING_DOWN
    flat = series({"09:20": (23250, 99, 101), "09:27": (23251, 99, 101), "09:30": (23252, 99, 101)})
    assert MS.classify(flat, "09:30")["state"] == RANGE
    rev = series({"09:20": (23300, 99, 101), "09:27": (23100, 99, 101), "09:30": (23230, 99, 101)})
    assert MS.classify(rev, "09:30")["state"] == REVERSING


def test_market_state_is_unknown_without_prints():
    assert MS.classify({}, "09:30")["state"] == UNKNOWN


# ================================================================ attribution
def base_loss(**over):
    r = dict(side="PE", final_pnl_per_unit=-5.0, exit_reason="POSITION_SIGNAL",
             und_1m_pct=-0.1, und_3m_pct=-0.2, und_5m_pct=-0.3, und_10m_pct=-0.3,
             und_direction_ok_1m=True, und_direction_ok_3m=True, und_direction_ok_5m=True,
             und_direction_ok_10m=True, und_move_to_exit_pct=-0.3,
             mid_to_mid_per_unit=-4.0, execution_friction_per_unit=-1.0,
             iv_state=IV_NEUTRAL, response_efficiency_1m=1.0, strike_band=ATM,
             und_pre_5m_pct=-0.05)
    return {**r, **over}


def test_a_stop_is_attributed_to_the_stop_and_nothing_else():
    assert LA.classify(base_loss(exit_reason="STOP_LOSS"))["loss_reason"] == "STOP_LOSS"


def test_underlying_that_never_went_the_right_way():
    r = base_loss(**{f"und_direction_ok_{h}m": False for h in (1, 3, 5, 10)}, und_move_to_exit_pct=0.4)
    assert LA.classify(r)["loss_reason"] == "UNDERLYING_DID_NOT_CONTINUE"


def test_right_way_then_reversed():
    r = base_loss(und_direction_ok_1m=True, und_move_to_exit_pct=0.5)
    assert LA.classify(r)["loss_reason"] == "MOMENTUM_REVERSAL"


def test_spread_friction_when_the_mid_result_was_positive():
    r = base_loss(mid_to_mid_per_unit=1.0, execution_friction_per_unit=-6.0)
    out = LA.classify(r)
    assert out["loss_reason"] == "SPREAD_FRICTION" and "mid-to-mid" in out["loss_note"].lower()


def test_iv_headwind_when_spot_was_right_but_iv_fell():
    r = base_loss(iv_state=IV_HEADWIND, iv_change_to_exit_pct=-4.0, execution_friction_per_unit=-0.1)
    assert LA.classify(r)["loss_reason"] == "IV_HEADWIND"


def test_weak_response_and_strike_distance_are_separate_labels():
    weak = base_loss(response_efficiency_1m=0.2, execution_friction_per_unit=-0.1)
    assert LA.classify(weak)["loss_reason"] == "WEAK_OPTION_RESPONSE"
    far = base_loss(response_efficiency_1m=0.2, strike_band="FAR_OTM", strike_distance_pct=2.0,
                    execution_friction_per_unit=-0.1)
    assert LA.classify(far)["loss_reason"] == "STRIKE_DISTANCE"


def test_late_entry_when_most_of_the_move_preceded_the_signal():
    r = base_loss(und_pre_5m_pct=-0.9, und_move_to_exit_pct=-0.1,
                  execution_friction_per_unit=-0.1, response_efficiency_1m=1.0)
    out = LA.classify(r)
    assert out["loss_reason"] == "LATE_ENTRY" and "BEFORE" in out["loss_note"]


def test_missing_result_is_a_data_issue_not_a_loss_reason():
    assert LA.classify(base_loss(final_pnl_per_unit=None))["loss_reason"] == "DATA_ISSUE"


# ================================================================ quadrants
def test_the_four_quadrants_separate_market_call_from_trade_result():
    r = dict(und_direction_ok_5m=True, opt_profitable_5m=False)
    assert LA.quadrant(r, 5) == "UNDERLYING_CORRECT_OPTION_LOSS"
    r = dict(und_direction_ok_5m=True, opt_profitable_5m=True)
    assert LA.quadrant(r, 5) == "UNDERLYING_CORRECT_OPTION_PROFITABLE"
    assert LA.quadrant(dict(und_direction_ok_5m=None, opt_profitable_5m=True), 5) is None


# ================================================================ density and flips
def rowset():
    return [dict(market="NIFTY", session_date="d", signal_minute="09:30", direction="BUY_PE",
                 side="PE", underlying_at_signal=23250.0, final_pnl_per_unit=-2.0),
            dict(market="NIFTY", session_date="d", signal_minute="09:32", direction="BUY_PE",
                 side="PE", underlying_at_signal=23240.0, final_pnl_per_unit=1.0),
            dict(market="NIFTY", session_date="d", signal_minute="09:40", direction="BUY_CE",
                 side="CE", underlying_at_signal=23300.0, final_pnl_per_unit=3.0)]


def test_density_counts_gaps_and_rate():
    d = density.density(rowset())["overall"]
    assert d["total_gaps"] == 2 and d["gaps_under_3min"] == 1


def test_runs_measure_repeated_same_direction_signals():
    r = density.runs(rowset())
    assert r["max_run_length"] == 2 and r["direction_changes"] == 1


def test_a_flip_is_market_confirmed_only_when_the_underlying_moved_against_the_old_side():
    f = density.flips(rowset())
    assert f["flips"] == 1 and f["market_confirmed"] == 1     # spot rose, old side was PE


def test_a_flip_without_a_market_move_is_not_confirmed():
    rows = rowset()
    rows[2]["underlying_at_signal"] = 23200.0                 # spot kept falling; PE was right
    f = density.flips(rows)
    assert f["market_confirmed"] == 0 and f["not_confirmed"] == 1


# ================================================================ isolation
def test_no_order_api_is_reachable_from_this_package():
    frags = ["place" + "_order", "modify" + "_order", "cancel" + "_order", "dhan_client", "dhanhq"]
    for p in (ROOT / "option_audit_12e").rglob("*.py"):
        src = p.read_text(encoding="utf-8")
        for f in frags:
            assert f not in src, f"{p.name} mentions {f}"


def test_12e_does_not_write_to_any_upstream_package():
    for pkg in ("scalp_decision_12c", "option_risk_12b", "position_sim_12c", "signal_learning_12d"):
        for p in (ROOT / pkg).rglob("*.py"):
            assert "option_audit_12e" not in p.read_text(encoding="utf-8"), f"{p} depends on 12E"


def test_version_and_config_hash_are_stamped():
    assert VERSION == "12E-option-audit-v1"
    assert len(DEFAULT.config_hash()) == 16
