"""13A-live-scalping-engine: gates, risk brake, position discipline, reconciliation, isolation."""

from pathlib import Path

import pytest

from live_scalping_13a import VERSION
from live_scalping_13a import engine as EN
from live_scalping_13a import features as FE
from live_scalping_13a import gates as G
from live_scalping_13a import position as POS
from live_scalping_13a import reconcile as RC
from live_scalping_13a import risk_brake as RB
from live_scalping_13a.config import (A, ACTIVE, B, BUY_CE, BUY_PE, C, Config, DEFAULT, EARLY,
                                      EXTENDED, GateConfig, IV_HEADWIND, IV_NEUTRAL, IV_TAILWIND,
                                      LOCKED, NORMAL, NO_TRADE, RANGE, REVERSING, RiskConfig,
                                      TRENDING_DOWN, TRENDING_UP, UNKNOWN, WAIT)

ROOT = Path(__file__).resolve().parent.parent
K = 23250.0


def lg(bid, ask, iv=12.0, delta=-0.5, theta=-8.0, vol=1000, oi=5000, greeks=True):
    two_sided = bid is not None and ask is not None
    mid = (bid + ask) / 2 if two_sided else None
    return dict(bid=bid, ask=ask, mid=mid, ltp=bid, spread=(ask - bid) if two_sided else None,
                spread_pct=((ask - bid) / mid * 100) if two_sided else None,
                bid_qty=100, ask_qty=100,
                volume=vol, oi=oi, iv=iv if greeks else None, delta=delta if greeks else None,
                gamma=0.001 if greeks else None, theta=theta if greeks else None,
                vega=1.0 if greeks else None, greeks_status="VALID" if greeks else "UNAVAILABLE")


def mk(spec: dict, side="PE", strike=K, other_side_mid=None):
    """{'09:30': (spot, bid, ask), ...} -> a minimal series with both legs present."""
    other = "CE" if side == "PE" else "PE"
    out = {}
    for m, v in spec.items():
        spot, bid, ask = v[0], v[1], v[2]
        iv = v[3] if len(v) > 3 else 12.0
        vol = v[4] if len(v) > 4 else 1000
        om = other_side_mid if other_side_mid is not None else 100.0
        out[m] = dict(spot=spot, expiry="2026-09-25",
                      legs={(side, strike): lg(bid, ask, iv=iv, vol=vol),
                            (other, strike): lg(om - 1, om + 1)})
    return out


def falling(n=16, start=23300.0, step=-4.0, bid=99.0, ask=99.25, prem_step=1.0):
    """A clean downtrend with a rising PE premium and growing volume.

    The 0.25 spread is deliberate: real ATM spreads measured in 12E average 0.22% of premium,
    and a fixture with an unrealistically wide spread would just test the spread gate."""
    spec = {}
    for i in range(n):
        m = f"09:{30 + i:02d}" if 30 + i < 60 else f"10:{30 + i - 60:02d}"
        spec[m] = (start + step * i, bid + prem_step * i, ask + prem_step * i, 12.0, 1000 + 200 * i)
    return spec


# ================================================================ regime (spec 3)
def test_regime_detects_a_downtrend_and_a_range():
    s = mk(falling())
    last = sorted(s)[-1]
    f = FE.build(s, last, "PE", K)
    assert G.regime(f)["state"] == TRENDING_DOWN
    flat = mk({f"09:{30+i:02d}": (23250.0 + (i % 2), 99.0, 101.0) for i in range(16)})
    f2 = FE.build(flat, sorted(flat)[-1], "PE", K)
    assert G.regime(f2)["state"] == RANGE


def test_range_blocks_both_sides_when_the_filter_is_on():
    assert G.regime_allows(RANGE, "PE")[1] == "REGIME_RANGE"
    assert G.regime_allows(RANGE, "CE")[1] == "REGIME_RANGE"


def test_the_range_filter_is_configurable():
    off = Config(gates=GateConfig(enable_range_filter=False))
    assert G.regime_allows(RANGE, "PE", off)[0] is True


def test_a_trend_against_the_side_is_refused():
    assert G.regime_allows(TRENDING_UP, "PE")[1] == "REGIME_AGAINST"
    assert G.regime_allows(TRENDING_DOWN, "CE")[1] == "REGIME_AGAINST"
    assert G.regime_allows(TRENDING_DOWN, "PE")[0] is True


def test_unknown_regime_refuses_rather_than_passing_through():
    assert G.regime_allows(UNKNOWN, "PE")[1] == "REGIME_UNKNOWN"


# ================================================================ critical data (spec 7)
def test_missing_greeks_and_quotes_refuse_and_never_fabricate():
    s = {"09:30": dict(spot=23250.0, expiry="x", legs={("PE", K): lg(None, None, greeks=False)})}
    f = FE.build(s, "09:30", "PE", K)
    assert f["delta"] is None and f["iv"] is None          # never zero
    cd = G.critical_data(f)
    assert cd["ok"] is False and "two_sided_quote" in cd["missing"]


# ================================================================ confirmation (spec 4/5)
def test_underlying_must_confirm_in_its_own_direction():
    s = mk(falling())
    f = FE.build(s, sorted(s)[-1], "PE", K)
    assert G.underlying_confirms(f, "PE")["ok"] is True
    assert G.underlying_confirms(f, "CE")["ok"] is False    # spot fell; a CE wanted it up


def test_option_confirmation_needs_several_independent_categories():
    s = mk(falling())
    f = FE.build(s, sorted(s)[-1], "PE", K)
    out = G.option_confirms(f, "PE")
    assert out["n"] >= out["required"] and out["ok"] is True
    strict = Config(gates=GateConfig(option_min_categories=4))
    assert G.option_confirms(f, "PE", strict)["required"] == 4


def test_no_single_indicator_is_sufficient():
    """Own momentum alone must not pass a 3-category requirement."""
    f = dict(opt_pre_3m=5.0, other_pre_3m=None, volume_ratio=None)
    assert G.option_confirms(f, "PE")["ok"] is False


# ================================================================ timing (spec 6)
def test_an_already_extended_premium_is_refused():
    f = dict(opt_pre_3m=9.0, opt_pre_5m=14.0, und_pre_5m=-0.9, premium_range_position=99.0,
             und_acceleration=0.0)
    assert G.entry_timing(f, "PE")["state"] == EXTENDED


def test_a_barely_moved_premium_is_early_not_extended():
    f = dict(opt_pre_3m=0.1, opt_pre_5m=0.2, und_pre_5m=-0.02, premium_range_position=40.0,
             und_acceleration=0.0)
    assert G.entry_timing(f, "PE")["state"] == EARLY


def test_timing_is_unknown_without_premium_history():
    assert G.entry_timing(dict(opt_pre_3m=None, opt_pre_5m=None), "PE")["state"] == UNKNOWN


def test_the_timing_filter_is_configurable():
    off = Config(gates=GateConfig(enable_timing_filter=False))
    assert off.gates.enable_timing_filter is False


# ================================================================ spread + economics (spec 9/10)
def test_spread_is_judged_relative_to_premium_not_in_rupees():
    cheap = G.spread_gate(dict(spread=0.5, mid=250.0))     # 0.2%
    dear = G.spread_gate(dict(spread=0.5, mid=15.0))       # 3.3%
    assert cheap["ok"] is True and dear["ok"] is False


def test_spread_without_a_quote_refuses():
    assert G.spread_gate(dict(spread=None, mid=None))["ok"] is False


def test_economics_requires_expected_move_to_beat_the_round_trip():
    good = G.economics(dict(delta=-0.5, spread=0.5, underlying=23250.0, und_pre_5m=-0.3), "PE")
    assert good["ok"] is True and good["ratio"] > 3
    bad = G.economics(dict(delta=-0.5, spread=8.0, underlying=23250.0, und_pre_5m=-0.02), "PE")
    assert bad["ok"] is False


def test_economics_refuses_when_delta_is_missing():
    assert G.economics(dict(delta=None, spread=0.5, underlying=23250.0, und_pre_5m=-0.3), "PE")["ok"] is False


# ================================================================ IV + quality (spec 8/11)
def test_iv_headwind_downgrades_but_never_rejects():
    checks = {k: dict(ok=True) for k in
              ("critical_data", "regime", "underlying", "option", "timing", "spread", "economics")}
    checks["option"] = dict(ok=True, n=4, required=3)
    checks["economics"] = dict(ok=True, ratio=10.0)
    checks["timing"] = dict(ok=True, state=NORMAL)
    clean = G.trade_quality(checks, dict(state=IV_NEUTRAL))
    head = G.trade_quality(checks, dict(state=IV_HEADWIND))
    assert clean["grade"] == A
    assert head["grade"] == B and "IV_HEADWIND" in head["downgrades"]
    assert head["failed"] == []          # downgraded, not rejected


def test_a_failed_critical_gate_is_no_trade():
    checks = {k: dict(ok=True) for k in
              ("critical_data", "regime", "underlying", "option", "timing", "spread")}
    checks["economics"] = dict(ok=False)
    assert G.trade_quality(checks, dict(state=IV_NEUTRAL))["grade"] == NO_TRADE


def test_grade_c_does_not_buy_by_default():
    assert G.quality_allows(A) and G.quality_allows(B)
    assert not G.quality_allows(C) and not G.quality_allows(NO_TRADE)


# ================================================================ risk brake (spec 15-19)
def test_capital_and_daily_loss_limit_are_different_numbers():
    r = RiskConfig()
    assert r.experiment_capital == 10000.0
    assert r.max_daily_loss == 2000.0 and r.max_daily_loss != r.experiment_capital
    v = RB.evaluate(RB.RiskState(), Config())
    assert v["allocated_capital"] != v["max_daily_loss"]
    assert "NOT the loss limit" in v["note"]


def test_daily_loss_locks_on_realised_not_unrealised():
    s = RB.RiskState(realised_pnl=-500.0, unrealised_pnl=-5000.0)
    assert RB.evaluate(s)["state"] == ACTIVE          # unrealised must not lock
    s2 = RB.RiskState(realised_pnl=-2000.0)
    assert RB.evaluate(s2)["state"] == LOCKED


def test_consecutive_losses_lock():
    s = RB.RiskState()
    for _ in range(3):
        s.record_close(-100.0)
    assert RB.evaluate(s)["state"] == LOCKED
    assert s.consecutive_losses == 3


def test_a_win_resets_the_consecutive_loss_run():
    s = RB.RiskState()
    s.record_close(-100.0); s.record_close(-100.0); s.record_close(50.0)
    assert s.consecutive_losses == 0 and RB.evaluate(s)["state"] == ACTIVE


def test_trade_count_locks():
    s = RB.RiskState()
    for _ in range(6):
        s.record_close(10.0)
    assert RB.evaluate(s)["state"] == LOCKED


def test_remaining_daily_risk_is_reported_and_never_negative():
    v = RB.evaluate(RB.RiskState(realised_pnl=-1240.0))
    assert v["remaining_daily_risk"] == pytest.approx(760.0)
    assert RB.evaluate(RB.RiskState(realised_pnl=-9999.0))["remaining_daily_risk"] == 0.0


def test_an_oversized_position_is_refused():
    ok, why = RB.position_allowed(RB.RiskState(), 50000.0)
    assert ok is False and why == "RISK_LOCKED"


# ================================================================ engine (spec 12/30)
def test_a_locked_state_outranks_every_other_gate():
    s = mk(falling())
    st = RB.RiskState(realised_pnl=-5000.0)
    out = EN.decide(s, sorted(s)[-1], BUY_PE, "STRONG", K, st, quantity=65)
    assert out["decision"] == WAIT and out["primary_rejection_reason"] == "RISK_LOCKED"


def test_no_base_signal_is_recorded_not_silently_dropped():
    s = mk(falling())
    out = EN.decide(s, sorted(s)[-1], WAIT, "NONE", K, RB.RiskState(), quantity=65)
    assert out["primary_rejection_reason"] == "NO_BASE_SIGNAL"


def test_an_open_position_blocks_a_second_entry():
    s = mk(falling())
    out = EN.decide(s, sorted(s)[-1], BUY_PE, "STRONG", K, RB.RiskState(),
                    position_open=True, quantity=65)
    assert out["primary_rejection_reason"] == "POSITION_OPEN"


def test_a_clean_downtrend_pe_candidate_can_buy():
    s = mk(falling())
    out = EN.decide(s, sorted(s)[-1], BUY_PE, "STRONG", K, RB.RiskState(), quantity=20)
    assert out["decision"] == BUY_PE and out["quality"] in (A, B)
    assert out["primary_rejection_reason"] is None


def test_the_same_candidate_in_a_range_is_refused():
    flat = mk({f"09:{30+i:02d}": (23250.0 + (i % 2), 99.0 + i, 99.25 + i, 12.0, 1000 + 200 * i)
               for i in range(16)})
    out = EN.decide(flat, sorted(flat)[-1], BUY_PE, "STRONG", K, RB.RiskState(), quantity=20)
    assert out["decision"] == WAIT and out["primary_rejection_reason"] == "REGIME_RANGE"


def test_every_wait_names_exactly_one_primary_reason():
    s = mk(falling())
    for base in (WAIT, BUY_CE):
        out = EN.decide(s, sorted(s)[-1], base, "STRONG", K, RB.RiskState(), quantity=65)
        assert out["decision"] == WAIT
        assert isinstance(out["primary_rejection_reason"], str)


def test_the_audit_row_carries_the_full_trail():
    s = mk(falling())
    row = EN.audit_row(EN.decide(s, sorted(s)[-1], BUY_PE, "STRONG", K, RB.RiskState(), quantity=20))
    for f in ("minute", "decision", "regime", "underlying", "bid", "ask", "spread", "delta", "iv",
              "theta", "volume", "oi", "entry_timing", "iv_state", "economics_ratio",
              "primary_rejection_reason"):
        assert f in row, f


# ================================================================ position (spec 13/14/28)
def test_entry_is_the_ask_and_pnl_marks_on_the_bid():
    s = mk(falling())
    m = sorted(s)[-1]
    p = POS.open_position(s, m, "NIFTY", "2026-09-25", "PE", K, 65, A)
    assert p.entry_ask == s[m]["legs"][("PE", K)]["ask"]
    card = p.mark(s, m)
    assert card["pnl_per_unit"] == pytest.approx(s[m]["legs"][("PE", K)]["bid"] - p.entry_ask)
    assert card["pnl"] == pytest.approx(card["pnl_per_unit"] * 65)


def test_the_stop_is_set_once_and_never_moves():
    s = mk(falling())
    m = sorted(s)[-1]
    p = POS.open_position(s, m, "NIFTY", "2026-09-25", "PE", K, 65, A)
    original = p.stop_price
    assert original == pytest.approx(round(p.entry_ask * 0.9, 2))
    for mm in sorted(s):
        p.mark(s, mm)
    assert p.stop_price == original          # marking never widens or moves the stop


def test_no_fill_is_invented_without_an_ask():
    s = {"09:30": dict(spot=23250.0, expiry="x", legs={("PE", K): lg(None, None)})}
    assert POS.open_position(s, "09:30", "NIFTY", "2026-09-25", "PE", K, 65, A) is None


def test_closing_uses_the_bid_and_the_identity_holds():
    s = mk(falling())
    ms = sorted(s)
    p = POS.open_position(s, ms[0], "NIFTY", "2026-09-25", "PE", K, 20, A)
    p.close(s, ms[-1], "SESSION_END")
    assert p.exit_bid == s[ms[-1]]["legs"][("PE", K)]["bid"]
    assert p.realised_pnl == pytest.approx(round((p.exit_bid - p.entry_ask), 2) * 20)


# ================================================================ reconciliation (spec 2)
def test_the_identity_check_catches_a_wrong_cash_figure():
    good = [dict(signal_id="a", entry_price=100.0, exit_bid=110.0, quantity=20,
                 final_pnl_per_unit=10.0, final_pnl=200.0)]
    bad = [dict(signal_id="b", entry_price=100.0, exit_bid=110.0, quantity=20,
                final_pnl_per_unit=10.0, final_pnl=999.0)]
    assert RC.check_identity(good, "t")["exact"] is True
    assert RC.check_identity(bad, "t")["exact"] is False


def test_unpriced_rows_are_counted_not_treated_as_passing():
    rows = [dict(signal_id="a", entry_price=None, exit_bid=None, quantity=20,
                 final_pnl_per_unit=None, final_pnl=None)]
    out = RC.check_identity(rows, "t")
    assert out["unpriced"] == 1 and out["checked"] == 0


def test_differing_exit_minutes_are_explained_not_reported_as_mismatches():
    research = [dict(market="NIFTY", session_date="2026-09-24", signal_minute="09:30", side="PE",
                     strike=K, exit_minute="09:40", entry_price=100.0, exit_bid=110.0,
                     quantity=20, final_pnl=200.0)]
    command = [dict(symbol="NIFTY", session_date="2026-09-24", signal_minute="09:30", side="PE",
                    strike=K, exit_minute="09:33", entry_price=100.0, exit_bid=104.0,
                    quantity=20, realised_pnl=80.0)]
    out = RC.cross_source(research, command)
    assert out["matched_different_exit_minute"] == 1 and out["exact"] is True


# ================================================================ isolation (spec 1/23)
def test_no_broker_or_order_path_exists_in_this_package():
    frags = ["place" + "_order", "modify" + "_order", "cancel" + "_order", "super" + "_order",
             "dhan_client", "dhanhq", "live_trading"]
    for p in (ROOT / "live_scalping_13a").rglob("*.py"):
        src = p.read_text(encoding="utf-8")
        for f in frags:
            assert f not in src, f"{p.name} mentions {f}"


def test_13a_does_not_modify_any_earlier_milestone():
    for pkg in ("scalp_decision_12c", "option_risk_12b", "position_sim_12c",
                "signal_learning_12d", "option_audit_12e", "paper_trading"):
        for p in (ROOT / pkg).rglob("*.py"):
            assert "live_scalping_13a" not in p.read_text(encoding="utf-8"), f"{p} depends on 13A"


def test_gates_are_pure_functions():
    src = (ROOT / "live_scalping_13a" / "gates.py").read_text(encoding="utf-8")
    for banned in ("datetime.now", "psycopg", "requests", "connect("):
        assert banned not in src, f"gates.py must stay pure, found {banned}"


def test_version_and_hashes_are_stamped():
    assert VERSION == "13A-live-scalping-engine-v1"
    assert len(DEFAULT.config_hash()) == 16
    assert DEFAULT.gates.config_hash() != DEFAULT.risk.config_hash()
