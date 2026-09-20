"""12C-scalp-decision-v1 tests (synthetic only; no DB, no network).

Cases 1-13 drive the decision rules through hand-built evidence, so each rule is pinned
on its own. Cases 14-18 go through the real engine on synthetic option snapshots, so the
data-quality and no-lookahead guarantees are tested end to end.
"""

import ast
import hashlib
import re
from datetime import date
from pathlib import Path

import pytest

from option_risk_12b.option_snapshot import minute_range
from scalp_decision_12c import brake as BRAKE
from scalp_decision_12c import entry as ENTRY
from scalp_decision_12c import evidence as EV
from scalp_decision_12c.config import BUY_CE, BUY_PE, CAUTION, DEFAULT, EXIT, HOLD, PREPARE_EXIT, VERSION, WAIT, DecisionConfig
from scalp_decision_12c.engine import decide_at
from tests.test_option_risk_12b import make_day

ROOT = Path(__file__).resolve().parent.parent
D = date(2026, 9, 18)
ATM = 23400.0


# ---------------------------------------------------------------- evidence builder for the rule tests
def ev_of(*, underlying=EV.BULLISH, at_level=None, ce3=3.0, pe3=-2.0, ce_persistent=True, pe_persistent=True,
          ce_label="RISING", pe_label="FALLING", ce_spike=False, pe_spike=False, participation="CE_STRONG",
          ce_rel="LONG_BUILDUP", pe_rel="NO_CLEAR_OI_PRICE_RELATION", liquidity="GOOD", straddle="EXPANDING",
          straddle_3m=1.2, dq="OK", price=23450.0, vwap=23400.0, poc=23380.0, age=None, ce1=1.0, pe1=-0.5):
    rel = (EV.CALL_RS if ce3 - pe3 >= 1.0 and ce3 > 0 else EV.PUT_RS if pe3 - ce3 >= 1.0 and pe3 > 0
           else EV.EXPANSION if (ce3 >= 1.0 and pe3 >= 1.0) else EV.CONTRACTION if (ce3 <= -1.0 and pe3 <= -1.0) else EV.BALANCED)
    if ce3 >= 1.0 and pe3 >= 1.0:
        rel = EV.EXPANSION
    if ce3 <= -1.0 and pe3 <= -1.0:
        rel = EV.CONTRACTION
    und_state = underlying
    detail = dict(price=price, vwap=vwap, poc=poc, at_level=at_level, ret_3m=12.0 if und_state == EV.BULLISH else -12.0,
                  underlying_state="LIVE" if und_state in (EV.BULLISH, EV.BEARISH, EV.NEUTRAL) else und_state.replace("UNDERLYING_", ""),
                  age_minutes=age)
    return dict(
        underlying=dict(category="UNDERLYING", state=und_state, detail=detail, note="underlying note"),
        option_relative=dict(category="OPTION_RELATIVE", state=rel, detail=dict(ce_3m=ce3, pe_3m=pe3), note="relative note"),
        ce_momentum=dict(category="CE_MOMENTUM", state=ce_label,
                         detail=dict(chg_1m=ce1, chg_3m=ce3, persistent=ce_persistent, spike=ce_spike), note="ce note"),
        pe_momentum=dict(category="PE_MOMENTUM", state=pe_label,
                         detail=dict(chg_1m=pe1, chg_3m=pe3, persistent=pe_persistent, spike=pe_spike), note="pe note"),
        participation=dict(category="PARTICIPATION", state=participation,
                           detail=dict(ce_ratio=1.6 if participation == "CE_STRONG" else 0.8,
                                       pe_ratio=1.6 if participation == "PE_STRONG" else 0.8), note="participation note"),
        oi=dict(category="OI_RELATIONSHIP", state="READ", detail=dict(ce_relation=ce_rel, pe_relation=pe_rel), note="oi note"),
        liquidity_ce=dict(category="LIQUIDITY", state=liquidity,
                          detail=dict(spread_pct=0.5 if liquidity == "GOOD" else 8.0, widened_vs_entry=False), note="liq note"),
        liquidity_pe=dict(category="LIQUIDITY", state=liquidity,
                          detail=dict(spread_pct=0.5 if liquidity == "GOOD" else 8.0, widened_vs_entry=False), note="liq note"),
        straddle=dict(category="STRADDLE", state=straddle,
                      detail=dict(chg_3m=straddle_3m, severe_contraction=straddle_3m <= DEFAULT.severe_contraction_pct), note="straddle note"),
        data_quality=dict(category="DATA_QUALITY", state=dq,
                          detail=dict(underlying_state=detail["underlying_state"], options="ACTIVE", flags=[],
                                      greeks_status={"ce": "VALID", "pe": "VALID"}, snapshot_present=True,
                                      underlying_age_minutes=age), note="dq note"),
    )


def mirror(**kw):
    """The same scenario with CE and PE swapped (a BUY PE case)."""
    base = dict(underlying=EV.BEARISH, ce3=-2.0, pe3=3.0, participation="PE_STRONG",
                ce_rel="NO_CLEAR_OI_PRICE_RELATION", pe_rel="LONG_BUILDUP", ce_label="FALLING", pe_label="RISING",
                price=23350.0, vwap=23400.0, poc=23420.0, ce1=-0.5, pe1=1.0)
    base.update(kw)
    return ev_of(**base)


# ---------------------------------------------------------------- 1 / 2
def test_strong_buy_ce_evidence():
    d = ENTRY.decide(ev_of(), DEFAULT)
    assert d["decision"] == BUY_CE and d["confirmation"] in ("STRONG", "MODERATE")
    assert len(d["supporting"]) >= DEFAULT.min_support_for_entry and not d["blocking"]
    assert d["reason"].startswith("BUY CE")


def test_strong_buy_pe_evidence():
    d = ENTRY.decide(mirror(), DEFAULT)
    assert d["decision"] == BUY_PE and not d["blocking"]
    assert any(c == "PE_MOMENTUM" for c, _ in d["supporting"])


# ---------------------------------------------------------------- 3 / 4 / 5 / 6 / 7
def test_conflicting_evidence_waits():
    # underlying bullish while PE is the outperforming side
    d = ENTRY.decide(ev_of(underlying=EV.BULLISH, ce3=-2.0, pe3=3.0, participation="PE_STRONG"), DEFAULT)
    assert d["decision"] == WAIT and d["side"] == "PE"
    assert any(c == "UNDERLYING" for c, _ in d["blocking"])


def test_both_sides_strengthening_waits():
    d = ENTRY.decide(ev_of(ce3=3.0, pe3=2.5), DEFAULT)
    assert d["decision"] == WAIT and d["confirmation"] == "NONE"
    assert "expansion" in d["reason"].lower()


def test_both_sides_weakening_waits():
    d = ENTRY.decide(ev_of(ce3=-2.0, pe3=-2.5), DEFAULT)
    assert d["decision"] == WAIT and "contraction" in d["reason"].lower()


def test_one_minute_spike_without_persistence_waits():
    d = ENTRY.decide(ev_of(ce3=3.0, ce1=9.0, ce_persistent=False, ce_spike=True), DEFAULT)
    assert d["decision"] == WAIT
    assert any(c == "CE_MOMENTUM" for c, _ in d["blocking"])
    # the same move, persistent, is allowed
    assert ENTRY.decide(ev_of(ce3=3.0, ce1=1.0, ce_persistent=True), DEFAULT)["decision"] == BUY_CE


def test_poor_liquidity_blocks_a_directionally_good_setup():
    d = ENTRY.decide(ev_of(liquidity="POOR"), DEFAULT)
    assert d["decision"] == WAIT and any(c == "LIQUIDITY" for c, _ in d["blocking"])


def test_severe_premium_contraction_blocks_entry():
    d = ENTRY.decide(ev_of(straddle="CONTRACTING", straddle_3m=-2.0), DEFAULT)
    assert d["decision"] == WAIT and any(c == "STRADDLE" for c, _ in d["blocking"])


# ---------------------------------------------------------------- 8 / 9
def test_stale_underlying_with_strong_option_evidence():
    d = ENTRY.decide(ev_of(underlying=EV.STALE, age=6, ce3=4.0, straddle_3m=1.5), DEFAULT)
    assert d["decision"] == BUY_CE and d["confirmation"] == "MODERATE"   # never STRONG without a live underlying
    assert "option evidence alone" in d["reason"]


def test_stale_underlying_with_weak_option_evidence_waits():
    d = ENTRY.decide(ev_of(underlying=EV.STALE, age=6, ce3=1.2, participation="MIXED",
                           ce_rel="NO_CLEAR_OI_PRICE_RELATION", straddle="FLAT", straddle_3m=0.1), DEFAULT)
    assert d["decision"] == WAIT and "not live" in d["reason"]


# ---------------------------------------------------------------- 10 / 11 / 12 / 13
CE_POS = dict(option_type="CE", strike=ATM)
PE_POS = dict(option_type="PE", strike=ATM)


def test_position_with_mild_contradiction_is_caution():
    ev = ev_of(ce3=1.5, ce_label="DECELERATING", ce1=0.1)     # one family only: MOMENTUM slowing
    r = BRAKE.assess(ev, CE_POS, DEFAULT)
    assert r["risk_action"] == CAUTION and r["risk_level"] == "ELEVATED"
    assert r["n_against"] == 1 and "1 independent signal against" in r["summary"]
    assert r["advisory_only"] is True


def test_buy_ce_position_with_multi_category_contradiction_prepares_exit():
    ev = ev_of(ce3=-1.5, pe3=1.5, ce_persistent=False, participation="PE_STRONG", ce_rel="LONG_UNWINDING",
               ce_label="FALLING", pe_label="RISING")
    r = BRAKE.assess(ev, CE_POS, DEFAULT)
    assert r["risk_action"] == PREPARE_EXIT and r["n_against"] >= DEFAULT.prepare_exit_min_families
    assert {"MOMENTUM", "RELATIVE"} <= set(r["families_against"])


def test_buy_pe_position_with_multi_category_contradiction_prepares_exit():
    ev = mirror(pe3=-1.5, ce3=1.5, pe_persistent=False, participation="CE_STRONG", pe_rel="LONG_UNWINDING",
                pe_label="FALLING", ce_label="RISING")
    r = BRAKE.assess(ev, PE_POS, DEFAULT)
    assert r["risk_action"] == PREPARE_EXIT and "POSITIONING" in r["families_against"]


def test_strong_multi_category_break_exits_but_never_from_one_minute():
    broken = ev_of(underlying=EV.BEARISH, ce3=-3.0, pe3=3.0, ce_persistent=True, participation="PE_STRONG",
                   ce_rel="LONG_UNWINDING", liquidity="POOR", ce_label="FALLING", price=23350.0, vwap=23400.0, poc=23420.0)
    r = BRAKE.assess(broken, CE_POS, DEFAULT)
    assert r["risk_action"] == EXIT and r["risk_level"] == "EXTREME" and r["thesis_broken"] is True
    assert len(r["families_against"]) >= DEFAULT.exit_min_families
    # identical evidence but the fall is NOT persistent -> never EXIT
    noisy = dict(broken)
    noisy["ce_momentum"] = dict(broken["ce_momentum"], detail=dict(broken["ce_momentum"]["detail"], persistent=False))
    r2 = BRAKE.assess(noisy, CE_POS, DEFAULT)
    assert r2["risk_action"] == PREPARE_EXIT and r2["thesis_broken"] is False


def test_supported_position_holds():
    r = BRAKE.assess(ev_of(), CE_POS, DEFAULT)
    assert r["risk_action"] == HOLD and r["risk_level"] in ("LOW", "NORMAL") and r["n_against"] == 0


# ---------------------------------------------------------------- 14 / 15 / 18 (engine level)
def _engine(minute="15:10", position=None, levels=None, **kw):
    snaps, candles = make_day(**kw)
    return decide_at("NIFTY", D, snaps, candles, levels or dict(vwap_now=ATM - 20, today_poc=ATM - 30, close=ATM),
                     position=position, minute=minute)


def test_missing_greeks_are_never_zero():
    out = _engine(greeks=False)
    st = out["option_state"]
    assert st["ce"]["greeks_status"] == "UNAVAILABLE" and st["ce"]["iv"] is None and st["ce"]["delta"] is None
    assert out["evidence"]["data_quality"]["detail"]["greeks_status"]["ce"] == "UNAVAILABLE"
    assert "INVALID_GREEKS" in out["evidence"]["data_quality"]["detail"]["flags"]


def test_degenerate_deep_itm_iv_is_unavailable_not_patched():
    from option_risk_12b.option_snapshot import parse_leg
    leg = parse_leg(dict(top_bid_price=120, top_ask_price=121, implied_volatility=0.0,
                         greeks=dict(delta=0.0, gamma=0.0, theta=0.0, vega=0.0)))
    assert leg["greeks_status"] == "INVALID" and leg["iv"] is None and leg["delta"] is None
    assert leg["iv_raw"] == 0.0 and leg["mid"] == 120.5          # the quote itself is still usable


def test_missing_underlying_is_not_treated_as_neutral_or_live():
    snaps, candles = make_day(freeze_from=None)
    snaps = [s for s in snaps if s["fetched_at"].strftime("%H:%M") != "15:10"]
    candles = [c for c in candles if c["timestamp"].strftime("%H:%M") != "15:09"]
    out = decide_at("NIFTY", D, snaps, candles, None, minute="15:10")
    u = out["evidence"]["underlying"]
    assert u["state"] == EV.MISSING and u["state"] != EV.NEUTRAL
    assert out["entry"]["decision"] == WAIT
    r = BRAKE.assess(out["evidence"], CE_POS, DEFAULT)
    assert any(x["family"] == "UNDERLYING" for x in r["against"])


def test_stale_underlying_shows_state_and_active_options():
    out = _engine(minute="15:22", spot_path=lambda i: ATM + 5.0 * i, freeze_from="15:15")
    assert out["evidence"]["underlying"]["state"] == EV.STALE
    assert out["evidence"]["data_quality"]["detail"]["options"] == "ACTIVE"
    assert out["summary"]["evidence_row"]["UNDERLYING_DATA"] == "STALE"
    assert [r["minute"] for r in out["closing_state"]][:2] == ["15:15", "15:16"]


# ---------------------------------------------------------------- 16
def test_no_future_data_can_enter_the_decision():
    snaps, candles = make_day(spot_path=lambda i: ATM + 4.0 * i, freeze_from=None)
    for t in minute_range("15:05", "15:20"):
        full = decide_at("NIFTY", D, snaps, candles, None, minute=t)
        cut = decide_at("NIFTY", D, [s for s in snaps if s["fetched_at"].strftime("%H:%M") <= t],
                        [c for c in candles if c["timestamp"].strftime("%H:%M") < t], None, minute=t)
        assert full == cut, t
    # and as_of never produces a later minute than asked for
    assert decide_at("NIFTY", D, snaps, candles, None, as_of="15:08")["minute"] == "15:08"


# ---------------------------------------------------------------- 17
def test_oi_delta_uses_consecutive_snapshots():
    out = _engine(oi_step=(400, 10))
    d = out["evidence"]["oi"]["detail"]
    assert d["ce_oi_pct_3m"] == pytest.approx(3 * 400 / (50_000 + 400 * 12) * 100, rel=1e-3)
    assert d["ce_relation"] in ("LONG_BUILDUP", "SHORT_BUILDUP", "NO_CLEAR_OI_PRICE_RELATION")
    assert out["option_state"]["ce"]["intraday_oi_change"] == 400          # consecutive, not prior-day previous_oi
    assert out["trace"]["ce_oi_signal"] == d["ce_relation"]


# ---------------------------------------------------------------- trace / isolation / advisory
def test_trace_is_complete_and_reproducible():
    out = _engine(position=dict(option_type="CE", strike=ATM, entry_spread_pct=0.5))
    t = out["trace"]
    for k in ("timestamp", "symbol", "underlying_state", "position_state", "decision", "confirmation", "risk_level",
              "risk_action", "underlying_signal", "ce_relative_strength", "pe_relative_strength", "ce_momentum",
              "pe_momentum", "ce_volume_signal", "pe_volume_signal", "ce_oi_signal", "pe_oi_signal", "liquidity_signal",
              "straddle_signal", "reason", "config_hash", "version"):
        assert k in t, k
    again = _engine(position=dict(option_type="CE", strike=ATM, entry_spread_pct=0.5))
    assert again["trace"] == t                                   # same inputs -> same decision
    assert t["position_state"] == "BUY_CE"


def test_advisory_only_and_isolated():
    out = _engine()
    assert out["advisory_only"] is True and "never places" in out["notice"]
    from paper_trading.config import DEFAULT_CONFIG as C11
    from scalp_12a.config import DEFAULT_CONFIG as C12A
    from tests.test_hr_isolation import FROZEN_FILES
    assert C11.config_hash() == "9c7c362d7e0c6a14" and C12A.config_hash() == "994667c6d552111e"
    for rel, digest in FROZEN_FILES.items():
        assert hashlib.sha256((ROOT / rel).read_bytes().replace(b"\r\n", b"\n")).hexdigest() == digest, rel
    forbidden = ("paper_trading", "scalp_12a", "pipeline.live_loop", "pipeline.run_snapshot", "dhan_client", "dhanhq",
                 "hr_capture", "backend", "db.writer")
    txt = ""
    for p in (ROOT / "scalp_decision_12c").glob("*.py"):
        txt += p.read_text(encoding="utf-8")
        for node in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
            names = ([a.name for a in node.names] if isinstance(node, ast.Import)
                     else [node.module] if isinstance(node, ast.ImportFrom) and node.module and node.level == 0 else [])
            for n in names:
                assert not any(n == f or n.startswith(f + ".") for f in forbidden), (p.name, n)
    assert not re.search("|".join(["place" + "_order", "modify" + "_order", "cancel" + "_order", "/" + "orders"]), txt)
    assert VERSION == "12C-scalp-decision-v1" and DecisionConfig().config_hash() == DEFAULT.config_hash()
    assert DecisionConfig(min_support_for_entry=2).config_hash() != DEFAULT.config_hash()
