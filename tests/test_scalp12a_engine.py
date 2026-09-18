"""12A engine tests: detector, confirmation, selector, risk, exits, counterfactual,
vetoes, NO-TRADE taxonomy, policy and look-ahead safety. Synthetic data only."""

import dataclasses
from datetime import date

import pytest

from scalp_12a.config import ScalpConfig
from scalp_12a.engine import evaluate_day, evaluate_session
from scalp_12a.events import detect_event
from scalp_12a.exits import OPEN, simulate_exit
from scalp_12a.models import Event, Quote, RiskPlan, Selection
from scalp_12a.option_selector import moneyness_steps, select_option
from scalp_12a.risk import plan_risk
from scalp_12a import taxonomy as T
from scalp_12a.thresholds import build_thresholds, percentile
from tests.scalp12a_factory import DAY, flat_then, make_session, thresholds

CFG = ScalpConfig()


def burst_session(start_bar=70, step=2.5, bars=6, **kw):
    """Flat until start_bar (bar 60 = 15:00:00), then a clean up-burst of bars x step."""
    return make_session(flat_then(start_bar, [step] * bars), **kw)


def strong(cands):
    return [c for c in cands if c.event.strength == T.STRONG]


# ------------------------------------------------------------------ thresholds
def test_percentile_linear():
    assert percentile([1, 2, 3, 4], 50) == 2.5 and percentile([], 50) is None


def test_thresholds_need_prior_history_and_use_only_given_days():
    noisy = [23400.0 + (3.0 if i % 2 else -3.0) + 0.1 * i for i in range(400)]
    s = make_session(noisy)
    assert not build_thresholds([s], CFG).sufficient            # 1 prior day < min_history_days
    assert not build_thresholds([burst_session()] * 2, CFG).sufficient   # a zero threshold would fire every bar
    thr = build_thresholds([s, dataclasses.replace(s, trading_date=date(2026, 9, 18))], CFG)
    assert thr.sufficient and thr.thr30_event >= thr.thr30_weak
    assert thr.history_days == ("2026-09-18", "2026-09-21")


def test_insufficient_history_produces_no_candidates_and_a_reason():
    r = evaluate_session(burst_session(), build_thresholds([], CFG), CFG)
    assert r.candidates == [] and r.session_reasons == [T.INSUFFICIENT_HISTORY]


# ------------------------------------------------------------------ detection
def test_momentum_event_detected_after_weak_near_miss():
    r = evaluate_session(burst_session(), thresholds(), CFG)
    kinds = [(c.event.event_type, c.event.strength, c.event.direction) for c in r.candidates]
    assert (T.MOMENTUM_EVENT, T.WEAK, 1) in kinds
    assert (T.MOMENTUM_EVENT, T.STRONG, 1) in kinds             # weak does not block the strong one
    weak = [c for c in r.candidates if c.event.strength == T.WEAK][0]
    assert T.WEAK_MOMENTUM in weak.no_trade_reasons and not weak.would_trade


def test_flat_market_has_no_event():
    assert evaluate_session(make_session([23400.0] * 200), thresholds(), CFG).candidates == []


def test_reversal_event():
    path = flat_then(40, [-1.0] * 36 + [3.0] * 6)                 # 3-min decline, then sharp up burst
    s = make_session(path)
    ev = [detect_event(s, i, thresholds(), CFG) for i in range(len(s))]
    types = {e.event_type for e in ev if e and e.strength == T.STRONG}
    assert T.REVERSAL_EVENT in types


def test_continuation_grind_detected_without_a_burst():
    path = flat_then(40, [0.9] * 40)                              # +36 in 200 s, never 7 in 30 s
    s = make_session(path)
    ev = [detect_event(s, i, thresholds(), CFG) for i in range(len(s))]
    assert any(e and e.event_type == T.CONTINUATION_EVENT and e.direction == 1 for e in ev)
    assert not any(e and e.event_type in (T.MOMENTUM_EVENT, T.REVERSAL_EVENT) for e in ev)


def test_down_event_buys_pe():
    s = make_session(flat_then(70, [-2.5] * 6))
    c = strong(evaluate_session(s, thresholds(), CFG).candidates)[0]
    assert c.event.direction == -1 and c.selection.leg.option_type == "PE"


# ------------------------------------------------------------------ confirmation / gates
def test_clean_mode_a_event_would_trade():
    c = strong(evaluate_session(burst_session(), thresholds(), CFG).candidates)[0]
    assert c.mode == T.MODE_A and c.passed_gates and c.would_trade and c.no_trade_reasons == []
    assert c.confirmation["option_response_ok"] and c.confirmation["persistence_ok"]
    assert c.risk and c.risk.quantity >= 1 and c.risk.rupee_risk <= CFG.max_rupee_loss_per_trade


def test_option_not_responding_is_rejected_and_still_tracked():
    frozen = lambda key, i, f, q: Quote(99.85, 100.15, 100.0, 0.3, 1.0, 100.0, 0.0)
    c = strong(evaluate_session(burst_session(option_fn=frozen), thresholds(), CFG).candidates)[0]
    assert T.OPTION_NOT_RESPONDING in c.no_trade_reasons and not c.would_trade
    assert c.counterfactual is not None                         # counterfactual recorded regardless


def test_wide_spreads_rejected_with_explicit_reason():
    c = strong(evaluate_session(burst_session(spread_pct=2.0), thresholds(), CFG).candidates)[0]
    assert T.SPREAD_TOO_WIDE in c.no_trade_reasons and c.counterfactual_leg_source in ("ATM_FALLBACK", "NONE")


def test_no_volume_is_low_liquidity():
    c = strong(evaluate_session(burst_session(volume=0.0), thresholds(), CFG).candidates)[0]
    assert T.LOW_LIQUIDITY in c.no_trade_reasons


def test_extended_move_rejected():
    path = flat_then(40, [1.2] * 30 + [3.0] * 6)                  # big run-up, then the burst
    c = [c for c in strong(evaluate_session(make_session(path), thresholds(), CFG).candidates)
         if c.event.event_type == T.MOMENTUM_EVENT]
    assert c and T.MOVE_ALREADY_EXTENDED in c[0].no_trade_reasons


def test_multiple_reasons_are_all_recorded():
    frozen = lambda key, i, f, q: Quote(97.0, 103.0, 100.0, 6.0, 1.0, 0.0, 0.0)
    c = strong(evaluate_session(burst_session(start_bar=20, option_fn=frozen), thresholds(), CFG).candidates)[0]
    assert T.TIME_WINDOW_CLOSED in c.no_trade_reasons and len(c.no_trade_reasons) >= 2


# ------------------------------------------------------------------ modes and vetoes
def test_pre_window_is_closed():
    c = strong(evaluate_session(burst_session(start_bar=20), thresholds(), CFG).candidates)[0]
    assert c.mode == T.MODE_PRE and T.TIME_WINDOW_CLOSED in c.no_trade_reasons and not c.would_trade


def test_mode_b_is_research_only():
    c = strong(evaluate_session(burst_session(start_bar=250), thresholds(), CFG).candidates)[0]
    assert c.mode == T.MODE_B and T.MODE_B_RESEARCH_ONLY in c.no_trade_reasons and not c.would_trade


def test_expiry_day_mode_b_hard_veto():
    c = strong(evaluate_session(burst_session(start_bar=250, expiry=DAY), thresholds(), CFG).candidates)[0]
    assert T.EXPIRY_DAY_CLOSE_VETO in c.no_trade_reasons and not c.would_trade


def test_expiry_day_transition_zone():
    # bar 60 = 15:00; 15:11:00 = bar 192
    c = strong(evaluate_session(burst_session(start_bar=186, expiry=DAY), thresholds(), CFG).candidates)[0]
    assert c.mode == T.MODE_A and T.EXPIRY_TRANSITION_ZONE in c.no_trade_reasons and not c.would_trade


def test_same_time_non_expiry_is_allowed():
    c = strong(evaluate_session(burst_session(start_bar=186), thresholds(), CFG).candidates)[0]
    assert c.would_trade


# ------------------------------------------------------------------ selection
def test_moneyness_sign():
    assert moneyness_steps("CE", 1) == 1 and moneyness_steps("PE", 1) == -1


def test_selector_never_picks_far_otm_or_cheap_legs():
    s = burst_session()
    ev = strong(evaluate_session(s, thresholds(), CFG).candidates)[0].event
    sel = select_option(s, ev, ev.bar_index, CFG)
    m = moneyness_steps(sel.leg.option_type, sel.leg.atm_offset)
    assert -CFG.max_itm_steps <= m <= CFG.max_otm_steps
    assert sel.rejections.get("moneyness", 0) > 0


# ------------------------------------------------------------------ execution realism
def test_entry_is_next_bar_ask_and_exit_is_bid():
    s = burst_session()
    c = strong(evaluate_session(s, thresholds(), CFG).candidates)[0]
    key = (c.selection.leg.option_type, c.selection.leg.atm_offset)
    assert c.counterfactual.entry_index == c.bar_index + CFG.entry_delay_bars == c.bar_index + 2
    assert c.counterfactual.entry_ask == s.quote(key, c.bar_index + 2).ask
    x = c.policy_exit
    assert x.exit_bid == s.quote(key, x.exit_index).bid


def test_decisions_do_not_depend_on_future_bars():
    """Look-ahead guard: the decision for every candidate up to bar k is identical
    whether the session ends at k+1 or continues."""
    full = make_session(flat_then(70, [2.5] * 6 + [0.0] * 20 + [-2.5] * 6, n_after=120))
    res_full = evaluate_session(full, thresholds(), CFG)
    for c in res_full.candidates:
        cut = c.bar_index + CFG.entry_delay_bars + 1
        part = dataclasses.replace(full, times=full.times[:cut], fut=full.fut[:cut], fut_updated=full.fut_updated[:cut],
                                   idx=full.idx[:cut], quotes={k: v[:cut] for k, v in full.quotes.items()})
        pc = [p for p in evaluate_session(part, thresholds(), CFG, session_complete=False).candidates
              if p.bar_index == c.bar_index][0]
        assert (pc.event.event_type, pc.event.strength, pc.event.direction, pc.event.displacement) == \
               (c.event.event_type, c.event.strength, c.event.direction, c.event.displacement)
        assert pc.no_trade_reasons == c.no_trade_reasons and pc.passed_gates == c.passed_gates
        assert pc.selection.leg == c.selection.leg and pc.risk.stop_price == c.risk.stop_price


# ------------------------------------------------------------------ risk
def test_risk_is_fixed_before_entry():
    ev = Event(10, T.MOMENTUM_EVENT, T.STRONG, 1, 5, 15, 15, 0, 15, 15.0, 23400.0)
    sel = Selection(None, Quote(99.85, 100.15, 100.0, 0.3), 5.0, 1.0, 1)
    p = plan_risk(ev, sel, CFG)
    assert p.stop_price == pytest.approx(100.15 * 0.95) and p.target_price == pytest.approx(100.15 * 1.05)
    assert p.quantity * (100.15 - p.stop_price) <= CFG.max_rupee_loss_per_trade + 1e-6
    assert p.underlying_invalidation == 23400.0 and p.max_hold_seconds == CFG.max_hold_seconds


def test_risk_too_large_when_one_unit_exceeds_budget():
    cfg = ScalpConfig(max_rupee_loss_per_trade=1.0)
    ev = Event(10, T.MOMENTUM_EVENT, T.STRONG, 1, 5, 15, 15, 0, 15, 15.0, 23400.0)
    p = plan_risk(ev, Selection(None, Quote(399.0, 401.0, 400.0, 0.5), 5.0, 1.0, 1), cfg)
    assert T.RISK_TOO_LARGE in p.reasons


# ------------------------------------------------------------------ exits
def _exit_setup(path, option_fn=None, expiry=None, cfg=CFG):
    s = make_session(path, option_fn=option_fn, expiry=expiry)
    ev = Event(70, T.MOMENTUM_EVENT, T.STRONG, 1, 5, 15, 15, 0, 15, 15.0, path[63])
    q = s.quote(("CE", 0), 71)
    plan = plan_risk(ev, Selection(s.legs[("CE", 0)], q, 5.0, 1.0, 1), cfg)
    return s, ev, plan


def test_stop_loss_exit():
    s, ev, plan = _exit_setup(flat_then(70, [0.0] + [-4.0] * 5))
    x = simulate_exit(s, ("CE", 0), 71, ev, plan, CFG)
    assert x.reason in (T.EXIT_STOP, T.EXIT_UNDERLYING_INVALIDATION, T.EXIT_EVENT_INVALIDATED)


def test_target_exit():
    s, ev, plan = _exit_setup(flat_then(70, [3.0] * 3 + [8.0] * 3))
    x = simulate_exit(s, ("CE", 0), 71, ev, plan, CFG)
    assert x.reason == T.EXIT_TARGET and x.pnl_pct > 0


def test_momentum_failure_when_no_progress():
    path = [23400.0] * 64 + [23415.0] * 200                       # event done, then nothing
    s, ev, plan = _exit_setup(path)
    x = simulate_exit(s, ("CE", 0), 71, ev, plan, CFG)
    assert x.reason == T.EXIT_MOMENTUM_FAILURE and x.hold_seconds <= CFG.no_progress_seconds + 5


def test_momentum_fade_gives_back_limited():
    up = [23415.0 + 1.8 * k for k in range(1, 6)]
    path = [23400.0] * 64 + [23415.0] * 7 + up + [up[-1] - 1.8 * k for k in range(1, 8)] + [up[-1] - 12.6] * 50
    s, ev, plan = _exit_setup(path)
    x = simulate_exit(s, ("CE", 0), 71, ev, plan, CFG)
    assert x.reason == T.EXIT_MOMENTUM_FADE
    assert x.peak_gain_pct >= CFG.fade_activation_pct and x.pnl_pct > -CFG.stop_pct   # small give-back, not the hard stop


def test_stop_only_tightens():
    path = [23400.0] * 64 + [23415.0] * 7 + [23415.0 + 1.5 * k for k in range(1, 30)] + [23458.0] * 30
    s, ev, plan = _exit_setup(path, cfg=ScalpConfig(target_pct=50.0))
    x = simulate_exit(s, ("CE", 0), 71, ev, plan, ScalpConfig(target_pct=50.0))
    assert x.stop_history == sorted(x.stop_history) and len(x.stop_history) >= 2


def test_spread_expansion_exit():
    def widen(key, i, f, q):
        return Quote(q.mid * 0.97, q.mid * 1.03, q.mid, 6.0, 1.0, 100.0, 0.0) if i >= 74 else q
    path = [23400.0] * 64 + [23415.0] * 7 + [23416.0] * 60
    s, ev, plan = _exit_setup(path, option_fn=widen)
    x = simulate_exit(s, ("CE", 0), 71, ev, plan, CFG)
    assert x.reason in (T.EXIT_SPREAD_EXPANSION, T.EXIT_STOP)


def test_time_exit_at_max_hold():
    path = [23400.0] * 64 + [23415.0] * 7 + [23415.3 + 0.001 * k for k in range(200)]
    cfg = ScalpConfig(no_progress_seconds=10_000)
    s, ev, plan = _exit_setup(path, cfg=cfg)
    x = simulate_exit(s, ("CE", 0), 71, ev, plan, cfg)
    assert x.reason == T.EXIT_TIME and x.hold_seconds == pytest.approx(CFG.max_hold_seconds, abs=5)


def test_expiry_day_forced_flat_before_zone():
    path = [23400.0] * 64 + [23415.0] * 7 + [23415.3 + 0.001 * k for k in range(300)]
    cfg = ScalpConfig(no_progress_seconds=10_000, max_hold_seconds=10_000)
    s, ev, plan = _exit_setup(path, expiry=DAY, cfg=cfg)
    x = simulate_exit(s, ("CE", 0), 71, ev, plan, cfg)
    assert x.reason == T.EXIT_EXPIRY_ZONE and x.exit_ts.strftime("%H:%M") == "15:10"


def test_open_position_when_live_data_ends():
    path = [23400.0] * 64 + [23415.0] * 7 + [23415.5] * 3
    s, ev, plan = _exit_setup(path)
    assert simulate_exit(s, ("CE", 0), 71, ev, plan, CFG, session_complete=False).reason == OPEN


# ------------------------------------------------------------------ counterfactual + policy
def test_counterfactual_mfe_mae_and_times():
    s = burst_session(step=2.5, bars=6)
    c = strong(evaluate_session(s, thresholds(), CFG).candidates)[0]
    cf = c.counterfactual
    assert cf.mfe_pct >= cf.mae_pct and cf.t_mfe_s is not None and set(cf.horizon_exit_pct) == set(CFG.horizons_seconds)


def test_every_candidate_gets_an_active_exit_counterfactual():
    r = evaluate_session(burst_session(start_bar=250), thresholds(), CFG)       # Mode B: never trades
    c = strong(r.candidates)[0]
    assert not c.would_trade and c.counterfactual_exit is not None


def test_one_position_at_a_time_across_symbols():
    a = burst_session(symbol="NIFTY")
    b = burst_session(symbol="SENSEX")
    res = evaluate_day([a, b], {"NIFTY": thresholds(), "SENSEX": thresholds()}, CFG)
    traded = [c for r in res.values() for c in r.candidates if c.would_trade]
    blocked = [c for r in res.values() for c in r.candidates if T.POSITION_OPEN in c.no_trade_reasons]
    assert len(traded) == 1 and len(blocked) == 1


def test_daily_trade_cap():
    cfg = ScalpConfig(max_trades_per_day=0)
    res = evaluate_day([burst_session()], {"NIFTY": thresholds()}, cfg)
    c = strong(res["NIFTY"].candidates)[0]
    assert T.DAILY_LIMIT_REACHED in c.no_trade_reasons and not c.would_trade
