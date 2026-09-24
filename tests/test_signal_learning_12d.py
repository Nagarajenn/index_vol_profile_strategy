"""12D-signal-learning-v1: the entry/position separation, entry-quality measurement and labelling.

The most important tests in this file are the ones asserting that an entry WAIT does NOT close
an open position, and that 12C's own source is unchanged. Everything else measures.
"""

from pathlib import Path

import pytest

from signal_learning_12d import VERSION
from signal_learning_12d import entry_quality as EQ
from signal_learning_12d import outcome_metrics as OM
from signal_learning_12d import signal_labels as SL
from signal_learning_12d.config import (ACCELERATING, CAUTION, DATA_RISK, DECELERATING, DEFAULT, EXIT,
                                        EXHAUSTED, EXHAUSTING, FLAT, HOLD, INSUFFICIENT, LATE,
                                        POSITION_SIGNAL, PREPARE_EXIT, REVERSING, STOP_LOSS)
from signal_learning_12d.position_lifecycle import PositionManager
from signal_learning_12d.signal_lifecycle import SignalEvent, episodes, signal_id

ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------- fixtures
def leg_row(bid, ask, ltp=None, volume=1000, oi=5000):
    return dict(bid=bid, ask=ask, mid=(bid + ask) / 2 if bid and ask else None, ltp=ltp or bid,
                spread_pct=((ask - bid) / ((bid + ask) / 2) * 100) if bid and ask else None,
                bid_qty=100, ask_qty=100, volume=volume, oi=oi, iv=12.0,
                delta=0.5, gamma=0.001, theta=-2.0, vega=1.0, greeks_status="VALID")


def series_from(prices: dict, side="CE", strike=100.0):
    """{'09:30': (bid, ask), ...} -> a minimal 12B-shaped series."""
    out = {}
    for m, (b, a) in prices.items():
        out[m] = dict(fetched_at=None, spot=1000.0, expiry="2026-09-24",
                      legs={(side, strike): leg_row(b, a)})
    return out


def evidence(n_against: int, side="CE", thesis_broken=False):
    """A minimal 12C-shaped evidence dict producing a known number of adverse families."""
    other = "PE" if side == "CE" else "CE"
    c3 = -3.0 if thesis_broken else (-1.5 if n_against >= 1 else 2.0)
    ev = {
        f"{side.lower()}_momentum": dict(state=DECELERATING if n_against else "RISING",
                                         detail=dict(chg_3m=c3, chg_1m=-0.5, persistent=thesis_broken, status="OK")),
        f"{other.lower()}_momentum": dict(state="RISING", detail=dict(chg_3m=3.0 if n_against >= 2 else 0.1,
                                                                     persistent=n_against >= 2)),
        "underlying": dict(state="UNDERLYING_BEARISH" if (n_against >= 3 and side == "CE") else "UNDERLYING_NEUTRAL",
                           note="test", detail=dict(price=1000.0, vwap=1010.0 if n_against >= 3 else 990.0,
                                                    poc=990.0, at_level=None)),
        "option_relative": dict(state="PUT_RELATIVE_STRENGTH" if n_against >= 2 else "BALANCED", note="test"),
        "participation": dict(state=f"{other}_STRONG" if n_against >= 4 else "MIXED",
                              detail={f"{side.lower()}_ratio": 1.0}),
        "oi": dict(detail={f"{side.lower()}_relation": "LONG_UNWINDING" if n_against >= 5 else "NEUTRAL"}),
        f"liquidity_{side.lower()}": dict(state="GOOD", note="tight", detail=dict(widened_vs_entry=False)),
        "straddle": dict(state="FLAT", detail=dict(severe_contraction=False)),
    }
    return ev


def q(bid, ask=None):
    return dict(status="OK", bid=bid, ask=ask or bid + 0.5, ltp=bid)


# ================================================================ 1-4: signal events
def test_buy_ce_creates_a_signal_event():
    ep = episodes([dict(minute="09:30", decision="BUY_CE", confirmation="STRONG", atm=100.0)])
    assert len(ep) == 1 and ep[0]["decision"] == "BUY_CE"


def test_buy_pe_creates_a_signal_event():
    ep = episodes([dict(minute="09:30", decision="BUY_PE", confirmation="STRONG", atm=100.0)])
    assert len(ep) == 1 and ep[0]["decision"] == "BUY_PE"


def test_wait_creates_no_signal_event():
    assert episodes([dict(minute="09:30", decision="WAIT", confirmation="NONE", atm=100.0)]) == []


def test_repeated_same_side_is_one_episode_not_many():
    """A BUY is a STATE. Five consecutive BUY_CE minutes are one opportunity, not five."""
    rows = [dict(minute=f"09:3{i}", decision="BUY_CE", confirmation="STRONG", atm=100.0) for i in range(5)]
    ep = episodes(rows)
    assert len(ep) == 1 and ep[0]["episode_minutes"] == 5 and ep[0]["minute"] == "09:30"


def test_buy_ce_then_buy_pe_splits_into_two_episodes():
    rows = [dict(minute="09:30", decision="BUY_CE", confirmation="STRONG", atm=100.0),
            dict(minute="09:31", decision="BUY_PE", confirmation="STRONG", atm=100.0)]
    ep = episodes(rows)
    assert [e["decision"] for e in ep] == ["BUY_CE", "BUY_PE"]


def test_signal_id_is_stable_and_age_is_measured_from_the_signal_minute():
    a = signal_id("SENSEX", "2026-09-24", "09:30", "BUY_CE")
    assert a == signal_id("SENSEX", "2026-09-24", "09:30", "BUY_CE")
    ev = SignalEvent(signal_id=a, market="SENSEX", session_date="2026-09-24", signal_minute="09:30",
                     direction="BUY_CE", side="CE", strike=100.0, expiry=None, contract="c",
                     confidence="STRONG", reason="r")
    assert ev.age_at("09:30") == 0 and ev.age_at("09:45") == 15


# ================================================================ 5-9: THE ARCHITECTURAL CORRECTION
def test_an_entry_wait_does_not_close_an_open_position():
    """The single most important behaviour in this milestone. The previous simulator closed the
    position the minute the entry decision became WAIT; the manager must not even look at it."""
    pm = PositionManager(side="CE", strike=100.0, entry_price=100.0, stop_price=90.0)
    step = pm.step("09:31", evidence(0), q(101.0), entry_decision="WAIT")
    assert step["state"] == HOLD and pm.exit_reason is None


def test_the_manager_ignores_the_entry_decision_entirely():
    """Identical evidence must produce an identical verdict whatever the entry engine says."""
    outs = []
    for dec in ("WAIT", "BUY_CE", "BUY_PE", None):
        pm = PositionManager(side="CE", strike=100.0, entry_price=100.0, stop_price=90.0)
        outs.append(pm.step("09:31", evidence(1), q(101.0), entry_decision=dec)["state"])
    assert len(set(outs)) == 1


def test_manager_can_produce_hold():
    pm = PositionManager(side="CE", strike=100.0, entry_price=100.0, stop_price=90.0)
    assert pm.step("09:31", evidence(0), q(101.0))["state"] == HOLD


def test_manager_can_produce_caution():
    pm = PositionManager(side="CE", strike=100.0, entry_price=100.0, stop_price=90.0)
    assert pm.step("09:31", evidence(1), q(101.0))["state"] == CAUTION


def test_manager_can_produce_prepare_exit():
    pm = PositionManager(side="CE", strike=100.0, entry_price=100.0, stop_price=90.0)
    assert pm.step("09:31", evidence(3), q(101.0))["state"] == PREPARE_EXIT


def test_manager_can_produce_exit_but_only_after_confirmation():
    """A single adverse minute must never reach EXIT -- it escalates to PREPARE_EXIT and waits."""
    pm = PositionManager(side="CE", strike=100.0, entry_price=100.0, stop_price=90.0)
    first = pm.step("09:31", evidence(4, thesis_broken=True), q(101.0))
    assert first["state"] == PREPARE_EXIT
    second = pm.step("09:32", evidence(4, thesis_broken=True), q(101.0))
    assert second["state"] == EXIT and pm.exit_reason == POSITION_SIGNAL


def test_evidence_that_clears_steps_the_state_back_down():
    pm = PositionManager(side="CE", strike=100.0, entry_price=100.0, stop_price=90.0)
    pm.step("09:31", evidence(3), q(101.0))
    assert pm.state == PREPARE_EXIT
    pm.step("09:32", evidence(0), q(102.0))
    pm.step("09:33", evidence(0), q(103.0))
    assert pm.state == CAUTION           # eased, not stuck at PREPARE_EXIT


# ================================================================ 10-13: hard risk vs signal exit
def test_stop_loss_is_a_hard_condition_needing_no_confirmation():
    pm = PositionManager(side="CE", strike=100.0, entry_price=100.0, stop_price=90.0)
    step = pm.step("09:31", evidence(0), q(89.0))
    assert step["state"] == EXIT and pm.exit_reason == STOP_LOSS


def test_stop_loss_outranks_clean_evidence():
    """Perfect evidence must not keep a position alive through its stop."""
    pm = PositionManager(side="CE", strike=100.0, entry_price=100.0, stop_price=95.0)
    assert pm.step("09:31", evidence(0), q(94.99))["state"] == EXIT
    assert pm.exit_reason == STOP_LOSS


def test_missing_quote_becomes_data_risk_not_a_signal_exit():
    pm = PositionManager(side="CE", strike=100.0, entry_price=100.0, stop_price=90.0)
    pm.step("09:31", evidence(0), dict(status="UNAVAILABLE", bid=None, ask=None))
    out = pm.step("09:32", evidence(0), dict(status="UNAVAILABLE", bid=None, ask=None))
    assert out["state"] == EXIT and pm.exit_reason == DATA_RISK


def test_exit_reason_categories_never_overlap():
    assert len({STOP_LOSS, POSITION_SIGNAL, DATA_RISK}) == 3


# ================================================================ 14-17: prices and excursions
def test_entry_uses_ask_and_exit_uses_bid():
    s = series_from({"09:30": (99.0, 101.0), "09:31": (105.0, 107.0)})
    assert OM.quote(s, "09:30", "CE", 100.0)["ask"] == 101.0
    assert OM.quote(s, "09:31", "CE", 100.0)["bid"] == 105.0


def test_mfe_and_mae_are_measured_from_entry_on_the_bid():
    s = series_from({"09:30": (99.0, 101.0), "09:31": (120.0, 122.0), "09:32": (90.0, 92.0),
                     "09:33": (105.0, 107.0)})
    m = OM.horizon_metrics(s, "09:30", 101.0, "CE", 100.0)
    assert m["mfe_per_unit"] == pytest.approx(19.0)      # 120 - 101
    assert m["mae_per_unit"] == pytest.approx(-11.0)     # 90 - 101
    assert m["time_to_mfe"] == 1 and m["time_to_mae"] == 2


def test_mfe_is_never_taken_from_before_the_entry():
    """A price spike BEFORE the signal must not appear as favourable excursion."""
    s = series_from({"09:28": (500.0, 502.0), "09:30": (99.0, 101.0), "09:31": (102.0, 104.0)})
    m = OM.horizon_metrics(s, "09:30", 101.0, "CE", 100.0)
    assert m["mfe_per_unit"] == pytest.approx(1.0)       # from 09:31 only, not the 09:28 spike


def test_an_incomplete_horizon_is_none_not_clipped():
    s = series_from({"09:30": (99.0, 101.0), "09:31": (105.0, 107.0)})
    m = OM.horizon_metrics(s, "09:30", 101.0, "CE", 100.0)
    assert m["outcome_1m"] == pytest.approx(4.0)
    assert m["outcome_10m"] is None and m["horizon_10m_complete"] is False


def test_hold_time_and_signal_age_are_different_concepts():
    ev = SignalEvent(signal_id="x", market="S", session_date="2026-09-24", signal_minute="09:30",
                     direction="BUY_CE", side="CE", strike=1.0, expiry=None, contract="c",
                     confidence="STRONG", reason="r")
    assert ev.age_at("09:40") == 10        # signal age from the signal minute
    # hold time is measured from the ENTRY minute, which may differ; the replay records both


# ================================================================ 18-21: momentum and exhaustion
def feats(**over):
    base = dict(ce_chg_1m=1.0, ce_chg_3m=3.0, ce_chg_5m=4.0, ce_acceleration=None,
                straddle_chg_3m=0.2)
    return {**base, **over}


def test_accelerating_is_detected():
    assert EQ.momentum_state(feats(ce_chg_1m=2.5, ce_chg_3m=3.0), "CE")["state"] == ACCELERATING


def test_decelerating_is_detected_while_the_move_is_still_positive():
    """The case the milestone was opened for: CE up over 3 minutes, latest minute already slow."""
    out = EQ.momentum_state(feats(ce_chg_1m=0.1, ce_chg_3m=3.0), "CE")
    assert out["state"] == DECELERATING and "slower" in out["note"]


def test_reversing_is_detected_when_the_last_minute_opposes_the_trend():
    assert EQ.momentum_state(feats(ce_chg_1m=-1.0, ce_chg_3m=3.0), "CE")["state"] == REVERSING


def test_flat_and_insufficient_are_distinguished():
    assert EQ.momentum_state(feats(ce_chg_1m=0.05, ce_chg_3m=0.1), "CE")["state"] == FLAT
    assert EQ.momentum_state(feats(ce_chg_1m=None, ce_chg_3m=None), "CE")["state"] == INSUFFICIENT


def test_exhaustion_requires_extension_and_loss_of_momentum():
    out = EQ.move_exhaustion(feats(ce_chg_1m=0.05, ce_chg_3m=1.0, ce_chg_5m=12.0), "CE")
    assert out["state"] == EXHAUSTING


def test_entry_timing_labels_are_marked_provisional():
    out = EQ.entry_timing(feats(ce_chg_1m=0.1, ce_chg_3m=3.0, ce_chg_5m=9.0), "CE")
    assert out["state"] in (LATE, EXHAUSTED) and out["provisional"] is True


def test_missing_option_data_yields_insufficient_not_a_guess():
    out = EQ.assess({}, "CE")
    assert out["momentum_state"] == INSUFFICIENT and out["entry_timing"] == INSUFFICIENT


# ================================================================ 22-26: labels
def test_outcome_labels_span_the_range():
    assert SL.outcome_label(15.0) == "STRONG_WIN"
    assert SL.outcome_label(4.0) == "WIN"
    assert SL.outcome_label(1.0) == "SMALL_WIN"
    assert SL.outcome_label(0.0) == "FLAT"
    assert SL.outcome_label(-1.0) == "SMALL_LOSS"
    assert SL.outcome_label(-5.0) == "LOSS"
    assert SL.outcome_label(-15.0) == "STRONG_LOSS"
    assert SL.outcome_label(None) is None


def test_a_loss_that_was_once_in_profit_is_not_labelled_the_same_as_a_false_signal():
    """The spec's own example: +54 MFE / -157 final must not read the same as a signal that
    never worked at all."""
    gave_back = dict(mfe_pct=8.0, mae_pct=-12.0, final_pnl_pct=-12.0, outcome_1m_pct=1.0,
                     entry_timing="GOOD", exhaustion_state="ACTIVE")
    never_worked = dict(mfe_pct=0.1, mae_pct=-12.0, final_pnl_pct=-12.0, outcome_1m_pct=-3.0,
                        entry_timing="GOOD", exhaustion_state="ACTIVE")
    assert SL.lifecycle_label(gave_back) == "GOOD_DIRECTION_BAD_EXIT"
    assert SL.lifecycle_label(never_worked) == "IMMEDIATE_FALSE_SIGNAL"


def test_a_late_entry_that_gave_back_is_attributed_to_the_entry_not_the_exit():
    row = dict(mfe_pct=8.0, mae_pct=-12.0, final_pnl_pct=-12.0, outcome_1m_pct=1.0,
               entry_timing=LATE, exhaustion_state="SLOWING")
    assert SL.lifecycle_label(row) == "GOOD_DIRECTION_LATE_ENTRY"


def test_exhaustion_entry_is_labelled_when_the_move_was_already_done():
    row = dict(mfe_pct=0.1, mae_pct=-5.0, final_pnl_pct=-5.0, outcome_1m_pct=0.0,
               entry_timing=EXHAUSTED, exhaustion_state=EXHAUSTING)
    assert SL.lifecycle_label(row) == "MOMENTUM_EXHAUSTION_ENTRY"


def test_recovery_is_distinguished_from_a_clean_win():
    row = dict(mfe_pct=6.0, mae_pct=-3.0, final_pnl_pct=5.0, outcome_1m_pct=-2.0,
               entry_timing="GOOD", exhaustion_state="ACTIVE")
    assert SL.lifecycle_label(row) == "INITIAL_ADVERSE_THEN_RECOVERED"


def test_missing_measurements_produce_inconclusive_not_a_label():
    assert SL.lifecycle_label(dict(mfe_pct=None, mae_pct=None, final_pnl_pct=None)) == "INCONCLUSIVE"


def test_the_three_diagnostic_questions_are_answered_separately():
    row = dict(mfe_pct=10.0, final_pnl_pct=-5.0, mae_1m=-0.5, entry_price=100.0)
    d = SL.diagnose(row)
    assert d["direction_correct"] is True and d["entry_timing_ok"] is True and d["exit_ok"] is False


# ================================================================ 27-29: analysis discipline
def test_small_groups_are_marked_insufficient_sample():
    from signal_learning_12d import lifecycle_report as LR
    rows = [dict(final_pnl=10.0, mfe_per_unit=1.0, mae_per_unit=-1.0, mfe_pct=1.0, mae_pct=-1.0,
                 hold_minutes=3)] * 3
    d = LR.describe(rows)
    assert d["n"] == 3 and d["sufficient"] is False and d["note"] == "INSUFFICIENT SAMPLE"


def test_a_group_at_the_threshold_is_sufficient():
    from signal_learning_12d import lifecycle_report as LR
    rows = [dict(final_pnl=1.0, mfe_pct=1.0, mae_pct=-1.0, hold_minutes=1)] * DEFAULT.min_sample
    assert LR.describe(rows)["sufficient"] is True


def test_wait_survival_is_reported():
    from signal_learning_12d import lifecycle_report as LR
    rows = [dict(entry_waits_survived=4, final_pnl=10.0), dict(entry_waits_survived=0, final_pnl=-5.0)]
    w = LR.wait_survival(rows)
    assert w["episodes_with_a_wait"] == 1 and w["of_those_profitable"] == 1


# ================================================================ 30-32: isolation
def test_12c_signal_generation_is_untouched_by_this_package():
    """12D may IMPORT 12C, never write to it. No file in 12C mentions 12D."""
    for p in (ROOT / "scalp_decision_12c").rglob("*.py"):
        assert "signal_learning_12d" not in p.read_text(encoding="utf-8"), f"{p} depends on 12D"
    for p in (ROOT / "option_risk_12b").rglob("*.py"):
        assert "signal_learning_12d" not in p.read_text(encoding="utf-8"), f"{p} depends on 12D"


def test_no_order_api_is_reachable_from_this_package():
    frags = ["place" + "_order", "modify" + "_order", "cancel" + "_order", "super" + "_order", "dhan_client"]
    for p in (ROOT / "signal_learning_12d").rglob("*.py"):
        src = p.read_text(encoding="utf-8")
        for f in frags:
            assert f not in src, f"{p.name} mentions {f}"


def test_the_package_writes_only_sl12d_tables():
    sql = (ROOT / "signal_learning_12d" / "schema.sql").read_text(encoding="utf-8")
    import re
    for obj in re.findall(r"CREATE (?:TABLE|INDEX)(?: IF NOT EXISTS)? (\w+)", sql):
        assert obj.startswith(("sl12d_", "idx_sl12d_")), obj
    assert "DROP " not in sql.upper() and "DELETE FROM" not in sql.upper()


def test_version_is_stamped():
    assert VERSION == "12D-signal-learning-v1"
    assert len(DEFAULT.config_hash()) == 16
