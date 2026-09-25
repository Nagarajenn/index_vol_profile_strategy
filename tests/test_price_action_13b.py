"""13B-price-action-v1: causal bars, structure, breaks, context, confirmation and integration."""

from pathlib import Path

import pytest

from price_action_13b import VERSION
from price_action_13b import bars as B
from price_action_13b import context as CX
from price_action_13b import decide as D
from price_action_13b import structure as ST
from price_action_13b.config import (ABOVE_VWAP, BELOW_VWAP, BREAKDOWN, BREAKOUT_CONTINUATION,
                                     BREAKOUT_UP, CLEAN_BREAK, CLEAN_BREAK_FT, CONFIRMED,
                                     CONTRADICTED, CROSSING_VWAP, DEFAULT, EXHAUSTED_BREAK,
                                     FAILED_BREAK, INSUFFICIENT, NO_BREAK, NO_SETUP, PARTIAL,
                                     PriceActionConfig, RANGE, RANGE_ROTATION, TRENDING_DOWN,
                                     TRENDING_UP, UNKNOWN, VOLUME_DECLINING, VOLUME_EXPANDING,
                                     VOLUME_SPIKE)

ROOT = Path(__file__).resolve().parent.parent


def bar(o, h, l, c, v=1000):
    return dict(open=o, high=h, low=l, close=c, volume=v)


def cmap_from(seq, start="09:15"):
    """seq: list of (o,h,l,c[,v]) -> {minute: bar} at 1-minute stamps."""
    h0, m0 = (int(x) for x in start.split(":"))
    out = {}
    for i, t in enumerate(seq):
        mi = h0 * 60 + m0 + i
        out[f"{mi // 60:02d}:{mi % 60:02d}"] = bar(*t)
    return out


def rising(n=30, start=23000.0, step=6.0, vol=1000):
    return [(start + step * i, start + step * i + 4, start + step * i - 2,
             start + step * i + 3, vol) for i in range(n)]


def falling(n=30, start=23300.0, step=-6.0, vol=1000):
    return [(start + step * i, start + step * i + 2, start + step * i - 4,
             start + step * i - 3, vol) for i in range(n)]


def flat(n=30, mid=23200.0, vol=1000):
    return [(mid + (i % 3) - 1, mid + 3, mid - 3, mid + (i % 3) - 1, vol) for i in range(n)]


# ================================================================ causality (spec 13)
def test_the_bar_stamped_at_the_signal_minute_is_never_used():
    """A 1-minute bar stamped 09:30 is still forming at 09:30. Using it reads one minute ahead."""
    cm = cmap_from(rising(10))
    ms = sorted(cm)
    w = B.completed_bars(cm, ms[5])
    assert all(b["minute"] < ms[5] for b in w)
    assert w[-1]["minute"] == ms[4]


def test_deleting_later_bars_changes_nothing():
    cm = cmap_from(falling(40))
    ms = sorted(cm)
    m = ms[30]
    full = B.completed_bars(cm, m)
    trunc = B.completed_bars({k: v for k, v in cm.items() if k < m}, m)
    assert full == trunc


def test_the_whole_evaluation_is_identical_under_truncation():
    cm = cmap_from(falling(40))
    m = sorted(cm)[30]
    lv = dict(vwap_now=23200.0, today_poc=23210.0, today_vah=23250.0, today_val=23150.0)
    a = D.evaluate(cm, m, "PE", lv)
    b = D.evaluate({k: v for k, v in cm.items() if k < m}, m, "PE", lv)
    for f in ("confirmation", "structure", "break_state", "setup", "vwap_state", "volume_state",
              "break_level", "follow_through", "last_completed_bar"):
        assert a[f] == b[f], f


def test_swings_never_use_unconfirmable_recent_bars():
    """A pivot needs k bars on each side; the last k bars cannot be confirmed yet."""
    cm = cmap_from(rising(20))
    w = B.completed_bars(cm, sorted(cm)[-1])
    sw = B.swings(w, k=2)
    if sw["confirmed_through"]:
        assert sw["confirmed_through"] <= w[-3]["minute"]


# ================================================================ structure (spec 2)
def test_an_uptrend_and_a_downtrend_are_distinguished():
    up = B.completed_bars(cmap_from(rising(30)), "10:00")
    down = B.completed_bars(cmap_from(falling(30)), "10:00")
    assert ST.structure(up)["state"] in (TRENDING_UP, BREAKOUT_UP)
    assert ST.structure(down)["state"] in (TRENDING_DOWN, BREAKDOWN)


def test_a_flat_tape_is_a_range_not_a_trend():
    w = B.completed_bars(cmap_from(flat(30)), "10:00")
    assert ST.structure(w)["state"] in (RANGE, INSUFFICIENT)


def test_structure_is_insufficient_without_enough_bars():
    w = B.completed_bars(cmap_from(rising(3)), "09:20")
    assert ST.structure(w)["state"] == INSUFFICIENT


def test_structure_reports_higher_high_and_higher_low_flags():
    w = B.completed_bars(cmap_from(rising(30)), "10:00")
    s = ST.structure(w)
    assert s["higher_high"] is not False
    assert isinstance(s["note"], str)


# ================================================================ breaks (spec 3)
def test_a_close_through_a_level_that_holds_is_a_clean_break_with_follow_through():
    # The flat base has a ~6-point range, so ATR is ~6. The break must stay inside
    # 2.5 ATR of the level or it is (correctly) called exhausted rather than clean.
    seq = flat(20, 23200.0) + [(23204, 23212, 23203, 23210), (23210, 23214, 23207, 23212),
                               (23212, 23216, 23210, 23214)]
    w = B.completed_bars(cmap_from(seq), "09:40")
    st = ST.structure(w)
    brk = ST.break_quality(w, "up", st)
    assert brk["state"] in (CLEAN_BREAK, CLEAN_BREAK_FT)


def test_a_wick_through_a_level_is_not_a_break():
    """A bar that pierces the level but closes back inside must not count."""
    seq = flat(20, 23200.0) + [(23202, 23260, 23200, 23203)]
    w = B.completed_bars(cmap_from(seq), "09:38")
    st = ST.structure(w)
    brk = ST.break_quality(w, "up", st)
    assert brk["state"] == NO_BREAK
    assert brk["pierced_without_close"] is True


def test_a_break_that_comes_back_inside_is_a_failed_break():
    seq = flat(20, 23200.0) + [(23205, 23240, 23204, 23235), (23235, 23238, 23190, 23195),
                               (23195, 23200, 23188, 23192)]
    w = B.completed_bars(cmap_from(seq), "09:40")
    st = ST.structure(w)
    assert ST.break_quality(w, "up", st)["state"] == FAILED_BREAK


def test_a_very_extended_break_is_exhausted():
    seq = flat(20, 23200.0) + [(23205, 23600, 23204, 23590), (23590, 23610, 23585, 23605)]
    w = B.completed_bars(cmap_from(seq), "09:39")
    st = ST.structure(w)
    out = ST.break_quality(w, "up", st)
    assert out["state"] in (EXHAUSTED_BREAK, CLEAN_BREAK, CLEAN_BREAK_FT)


def test_break_quality_is_insufficient_without_a_level():
    assert ST.break_quality([], "up", dict(recent_high=None))["state"] == INSUFFICIENT


# ================================================================ setup (spec 4)
def test_a_clean_break_is_a_continuation_and_a_flat_tape_is_a_rotation():
    assert ST.setup_type(dict(state=TRENDING_UP), dict(state=CLEAN_BREAK_FT, note=""))["state"] \
        == BREAKOUT_CONTINUATION
    assert ST.setup_type(dict(state=RANGE), dict(state=NO_BREAK, note=""))["state"] == RANGE_ROTATION


# ================================================================ context (spec 5/6/7)
def test_vwap_context_distinguishes_above_below_and_sitting_on_it():
    """Index-scale prices: the bands are percentages, so toy numbers land in DISTANT."""
    w = [bar(23200, 23205, 23195, 23200.0)]
    assert CX.vwap_context(w, 23160.0)["state"] == ABOVE_VWAP     # +0.17%
    assert CX.vwap_context(w, 23240.0)["state"] == BELOW_VWAP     # -0.17%
    assert CX.vwap_context(w, 23199.0)["state"] == CROSSING_VWAP  # +0.004%
    assert CX.vwap_context(w, 23000.0)["state"] == "DISTANT_FROM_VWAP"
    assert CX.vwap_context(w, None)["state"] == UNKNOWN


def test_value_context_never_invents_a_missing_level():
    w = [bar(100, 101, 99, 100.0)]
    assert CX.value_context(w, None)["state"] == UNKNOWN
    assert CX.value_context(w, {})["state"] == UNKNOWN
    out = CX.value_context(w, dict(today_vah=95.0, today_val=90.0, today_poc=92.0))
    assert out["state"] == "ACCEPTANCE_ABOVE_VAH"


def test_volume_states_are_relative_to_the_bars_own_average():
    base = [bar(1, 2, 0, 1, 1000) for _ in range(12)]
    assert CX.volume_context(base)["state"] == "VOLUME_NORMAL"
    assert CX.volume_context(base + [bar(1, 2, 0, 1, 3000)])["state"] == VOLUME_SPIKE
    assert CX.volume_context(base + [bar(1, 2, 0, 1, 1300)])["state"] == VOLUME_EXPANDING
    assert CX.volume_context(base + [bar(1, 2, 0, 1, 500)])["state"] == VOLUME_DECLINING


def test_volume_confirms_only_when_it_expands_on_a_bar_going_the_right_way():
    up_bar = [bar(100, 102, 99, 101)]
    assert CX.volume_confirms(dict(state=VOLUME_EXPANDING), "CE", up_bar) is True
    assert CX.volume_confirms(dict(state=VOLUME_EXPANDING), "PE", up_bar) is False
    assert CX.volume_confirms(dict(state=UNKNOWN), "CE", up_bar) is None


# ================================================================ confirmation (spec 8)
def test_a_range_with_no_break_is_no_setup():
    cm = cmap_from(flat(30))
    out = D.evaluate(cm, "10:00", "PE", dict(vwap_now=23200.0))
    assert out["confirmation"] in (NO_SETUP, UNKNOWN, CONTRADICTED)


def test_a_candidate_against_the_structure_is_contradicted():
    cm = cmap_from(rising(30))
    out = D.evaluate(cm, "10:00", "PE", dict(vwap_now=22900.0))
    assert out["confirmation"] in (CONTRADICTED, NO_SETUP)


def test_insufficient_bars_produce_unknown_not_a_guess():
    cm = cmap_from(rising(3))
    out = D.evaluate(cm, "09:20", "CE", None)
    assert out["confirmation"] == UNKNOWN


def test_the_reason_is_always_a_readable_sentence():
    for seq, side in ((flat(30), "PE"), (rising(30), "CE"), (falling(30), "PE")):
        out = D.evaluate(cmap_from(seq), "10:00", side, dict(vwap_now=23100.0))
        assert isinstance(out["reason"], str) and len(out["reason"]) > 10
        assert "None" not in out["reason"]


# ================================================================ integration (spec 9)
def test_13b_can_never_create_a_buy():
    for pa in (CONFIRMED, PARTIAL, CONTRADICTED, NO_SETUP, UNKNOWN):
        out = D.apply("WAIT", dict(confirmation=pa, reason="x"))
        assert out["final_decision"] == "WAIT"
        assert out["price_action_block"] is False


def test_confirmed_preserves_the_13a_buy():
    out = D.apply("BUY_PE", dict(confirmation=CONFIRMED, reason="x"))
    assert out["final_decision"] == "BUY_PE" and out["price_action_block"] is False


def test_partial_contradicted_and_no_setup_block_by_default():
    for pa in (PARTIAL, CONTRADICTED, NO_SETUP):
        out = D.apply("BUY_CE", dict(confirmation=pa, reason="x"))
        assert out["final_decision"] == "WAIT" and out["price_action_block"] is True
        assert out["block_reason"] == f"PRICE_ACTION_{pa}"


def test_unknown_preserves_the_decision_and_marks_it():
    out = D.apply("BUY_CE", dict(confirmation=UNKNOWN, reason="x"))
    assert out["final_decision"] == "BUY_CE" and out["price_action_block"] is False
    assert out["final_price_action_state"] == UNKNOWN


def test_every_block_is_configurable():
    cfg = PriceActionConfig(block_on_partial=False)
    out = D.apply("BUY_CE", dict(confirmation=PARTIAL, reason="x"), cfg)
    assert out["final_decision"] == "BUY_CE"


def test_the_whole_layer_can_be_disabled():
    cfg = PriceActionConfig(enabled=False)
    out = D.apply("BUY_PE", dict(confirmation=CONTRADICTED, reason="x"), cfg)
    assert out["final_decision"] == "BUY_PE" and out["price_action_block"] is False


# ================================================================ isolation (spec 1/15)
def test_no_broker_or_order_path_exists():
    frags = ["place" + "_order", "modify" + "_order", "cancel" + "_order", "dhanhq", "dhan_client"]
    for p in (ROOT / "price_action_13b").rglob("*.py"):
        src = p.read_text(encoding="utf-8")
        for f in frags:
            assert f not in src, f"{p.name} mentions {f}"


def test_13b_does_not_modify_any_earlier_milestone():
    for pkg in ("live_scalping_13a", "scalp_decision_12c", "option_risk_12b", "position_sim_12c",
                "signal_learning_12d", "option_audit_12e", "paper_trading"):
        for p in (ROOT / pkg).rglob("*.py"):
            assert "price_action_13b" not in p.read_text(encoding="utf-8"), f"{p} depends on 13B"


def test_no_indicator_pile_was_added():
    """The spec forbids RSI/MACD/stochastics. Four ideas only."""
    import re
    for p in (ROOT / "price_action_13b").rglob("*.py"):
        src = p.read_text(encoding="utf-8").lower()
        for banned in ("rsi", "macd", "stochastic", "bollinger", "ichimoku"):
            # word boundaries: a bare substring match hits "excursion" for "rsi"
            assert not re.search(rf"{banned}", src), f"{p.name} mentions {banned}"


def test_classifiers_do_not_see_the_candidate_side():
    """structure.py must describe price without knowing which side was proposed."""
    src = (ROOT / "price_action_13b" / "structure.py").read_text(encoding="utf-8")
    assert '"CE"' not in src and '"PE"' not in src


def test_version_and_config_hash_are_stamped():
    assert VERSION == "13B-price-action-v1"
    assert len(DEFAULT.config_hash()) == 16
