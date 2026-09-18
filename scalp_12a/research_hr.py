"""Step 4: HR 5-second research, always against a random baseline.

DESCRIPTIVE until enough HR history exists. Thresholds for each day come only
from earlier HR days (causal), so the first ``min_history_days`` HR days can
never produce candidates. Nothing here tunes a 5-second parameter.

Groups compared (same entry delay, ASK entry, BID exits, same active exit engine):
* CONFIRMED  -- candidates that passed every event/confirmation/liquidity/risk gate
                (vetoes such as Mode B ignored, so Mode B research keeps accumulating);
* ALL_STRONG -- every STRONG event, confirmed or not (displacement only);
* RANDOM     -- random bars in the same windows, random direction, ATM leg.
Statistics are aggregated per trading day first; observations are never pooled
as if every 5-second bar were independent.
"""

import random
import statistics as st

from scalp_12a.config import ScalpConfig
from scalp_12a.engine import evaluate_day
from scalp_12a.exits import OPEN, simulate_exit
from scalp_12a.models import Event, SessionBars, Selection
from scalp_12a.modes import market_mode
from scalp_12a.risk import plan_risk
from scalp_12a.taxonomy import (
    EXIT_TARGET, MODE_A, MODE_B, MODE_B_RESEARCH_ONLY, EXPIRY_DAY_CLOSE_VETO, EXPIRY_TRANSITION_ZONE,
    MOMENTUM_EVENT, MOMENTUM_FAILURE_EXITS, STRONG, TIME_WINDOW_CLOSED,
)
from scalp_12a.thresholds import build_thresholds

VETO_REASONS = {MODE_B_RESEARCH_ONLY, EXPIRY_DAY_CLOSE_VETO, EXPIRY_TRANSITION_ZONE, TIME_WINDOW_CLOSED}
MIN_DAYS_FOR_VALIDATION = 20          # target HR history before any chronological split


def _obs(kind, c_or_none, day, symbol, mode, is_expiry, x, cf):
    return dict(kind=kind, day=str(day), symbol=symbol, mode=mode, expiry=is_expiry,
                exit_pct=x.pnl_pct if x and x.reason != OPEN else None,
                exit_reason=x.reason if x else None,
                peak=x.peak_gain_pct if x else None,
                giveback=(x.peak_gain_pct - x.pnl_pct) if x and x.pnl_pct is not None and x.peak_gain_pct is not None else None,
                hold=x.hold_seconds if x else None,
                mfe=cf.mfe_pct if cf else None, mae=cf.mae_pct if cf else None,
                t_mfe=cf.t_mfe_s if cf else None, t_mae=cf.t_mae_s if cf else None,
                h_exit={h: v for h, v in cf.horizon_exit_pct.items()} if cf else {},
                h_mfe={h: v for h, v in cf.horizon_mfe_pct.items()} if cf else {},
                spread=cf.entry_spread_pct if cf else None,
                event_type=c_or_none.event.event_type if c_or_none else None,
                **_opp(c_or_none.opportunity if c_or_none else None))


def _opp(o):
    if o is None:
        return dict(timing=None, frac_det=None, frac_entry=None, realized_det=None, fut_mfe_det=None, fut_mae_det=None)
    return dict(timing=o.timing, frac_det=o.remaining_fraction_at_detection, frac_entry=o.remaining_fraction_at_entry,
                realized_det=o.realized_at_detection, fut_mfe_det=o.fut_mfe_after_detection,
                fut_mae_det=o.fut_mae_after_detection)


def random_observations(session: SessionBars, config: ScalpConfig, n: int, rng: random.Random):
    """Random entries with the SAME exit engine: event origin = futures 30 s earlier."""
    from scalp_12a.counterfactual import track
    out = []
    lag = 30 // config.bar_seconds
    eligible = [i for i, t in enumerate(session.times)
                if market_mode(t, config) in (MODE_A, MODE_B) and i >= lag and i + config.entry_delay_bars < len(session)]
    for i in rng.sample(eligible, min(n, len(eligible))):
        d = rng.choice([1, -1])
        key = ("CE" if d > 0 else "PE", 0)
        q = session.quote(key, i)
        f_now, f_then = session.fut_ffill(i), session.fut_ffill(i - lag)
        if q is None or not q.valid or f_now is None or f_then is None:
            continue
        # Fair comparison: a notional favourable displacement of the same size as the
        # actual 30 s move, so invalidation sits as far from the entry as for a real event
        # (a raw origin would put half the random entries past invalidation at once).
        size = max(abs(f_now - f_then), session.strike_step * 0.05)
        ev = Event(i, MOMENTUM_EVENT, STRONG, d, None, d * size, None, None, None, d * size, f_now - d * size)
        plan = plan_risk(ev, Selection(session.legs[key], q, None, None, 0), config)
        e = i + config.entry_delay_bars
        cf = track(session, key, e, d, config)
        x = simulate_exit(session, key, e, ev, plan, config)
        out.append(_obs("RANDOM", None, session.trading_date, session.symbol, market_mode(session.times[i], config),
                        session.is_expiry_day, x, cf))
    return out


def run(sessions_by_day: dict, config: ScalpConfig, seed: int = 12, random_per_session: int = 40):
    """sessions_by_day: {date: {symbol: SessionBars}} for every completed HR day (chronological)."""
    rng = random.Random(seed)
    days = sorted(sessions_by_day)
    obs, day_meta, candidates = [], [], []
    for n, d in enumerate(days):
        prior = days[:n]
        todays = sessions_by_day[d]
        thr = {sym: build_thresholds([sessions_by_day[p][sym] for p in prior if sym in sessions_by_day[p]], config)
               for sym in todays}
        res = evaluate_day(list(todays.values()), thr, config)
        meta = dict(day=str(d), prior_days=len(prior), sufficient={s: t.sufficient for s, t in thr.items()},
                    candidates=sum(len(r.candidates) for r in res.values()),
                    would_trade=sum(1 for r in res.values() for c in r.candidates if c.would_trade))
        day_meta.append(meta)
        for sym, r in res.items():
            s = todays[sym]
            for c in r.candidates:
                candidates.append((d, sym, c, thr[sym]))
                if c.event.strength != STRONG:
                    continue
                o = _obs("ALL_STRONG", c, d, sym, c.mode, s.is_expiry_day, c.counterfactual_exit, c.counterfactual)
                obs.append(o)
                gate_reasons = [x for x in c.no_trade_reasons if x not in VETO_REASONS]
                if not gate_reasons and c.counterfactual is not None:
                    obs.append(dict(o, kind="CONFIRMED"))
                elif c.counterfactual is not None:
                    obs.append(dict(o, kind="REJECTED", reasons=gate_reasons))
            if any(t.sufficient for t in thr.values()):
                obs.extend(random_observations(s, config, random_per_session, rng))
    return dict(days=[str(d) for d in days], day_meta=day_meta, observations=obs), candidates


def _day_mean(rows, key):
    by = {}
    for r in rows:
        v = r[key] if not isinstance(key, tuple) else r[key[0]].get(key[1])
        if v is not None:
            by.setdefault((r["day"], r["symbol"]), []).append(v)
    return [st.mean(v) for v in by.values()]


def summarize(result: dict, config: ScalpConfig) -> dict:
    obs = result["observations"]
    out = {}
    for kind in ("CONFIRMED", "ALL_STRONG", "RANDOM"):
        for mode in (MODE_A, MODE_B):
            rows = [o for o in obs if o["kind"] == kind and o["mode"] == mode]
            if not rows:
                out[f"{kind}|{mode}"] = dict(n=0)
                continue
            dm = _day_mean(rows, "exit_pct")
            out[f"{kind}|{mode}"] = dict(
                n=len(rows), day_groups=len(dm),
                active_exit_day_mean=round(st.mean(dm), 3) if dm else None,
                active_exit_median=round(st.median([r["exit_pct"] for r in rows if r["exit_pct"] is not None]), 3)
                if any(r["exit_pct"] is not None for r in rows) else None,
                mae_median=round(st.median([r["mae"] for r in rows if r["mae"] is not None]), 3)
                if any(r["mae"] is not None for r in rows) else None,
                mfe_median=round(st.median([r["mfe"] for r in rows if r["mfe"] is not None]), 3)
                if any(r["mfe"] is not None for r in rows) else None,
                t_mfe_median=st.median([r["t_mfe"] for r in rows if r["t_mfe"] is not None])
                if any(r["t_mfe"] is not None for r in rows) else None,
                giveback_median=round(st.median([r["giveback"] for r in rows if r["giveback"] is not None]), 3)
                if any(r["giveback"] is not None for r in rows) else None,
                momentum_failure_exit_share=round(sum(1 for r in rows if r["exit_reason"] in MOMENTUM_FAILURE_EXITS) / len(rows), 3),
                target_share=round(sum(1 for r in rows if r["exit_reason"] == EXIT_TARGET) / len(rows), 3),
                fixed_exit_median={h: round(st.median([r["h_exit"].get(h) for r in rows if r["h_exit"].get(h) is not None]), 3)
                                   for h in config.horizons_seconds
                                   if any(r["h_exit"].get(h) is not None for r in rows)},
                symbols={s: sum(1 for r in rows if r["symbol"] == s) for s in config.symbols},
                days={d: sum(1 for r in rows if r["day"] == d) for d in sorted({r["day"] for r in rows})},
            )
    # Opportunity remaining at detection + missed opportunities / false positives (Mode A and B pooled,
    # descriptive). A "missed" opportunity = rejected by a non-veto gate yet DETECTED_EARLY with a
    # positive active-exit counterfactual; a "false positive" = confirmed but the active exit lost.
    timing = {}
    for kind in ("CONFIRMED", "REJECTED", "ALL_STRONG"):
        rows = [o for o in obs if o["kind"] == kind]
        counts = {}
        for r in rows:
            counts[r["timing"]] = counts.get(r["timing"], 0) + 1
        med = lambda k: round(st.median([r[k] for r in rows if r.get(k) is not None]), 3)             if any(r.get(k) is not None for r in rows) else None
        timing[kind] = dict(n=len(rows), counts=counts, frac_det_median=med("frac_det"),
                            frac_entry_median=med("frac_entry"), realized_det_median=med("realized_det"),
                            fut_mfe_after_det_median=med("fut_mfe_det"), fut_mae_after_det_median=med("fut_mae_det"))
    rej = [o for o in obs if o["kind"] == "REJECTED"]
    conf = [o for o in obs if o["kind"] == "CONFIRMED"]
    missed = [o for o in rej if o["timing"] == "DETECTED_EARLY" and (o["exit_pct"] or 0) > 0]
    reason_counts = {}
    for o in missed:
        for x in o.get("reasons", []):
            reason_counts[x] = reason_counts.get(x, 0) + 1
    out["opportunity_timing"] = timing
    out["missed_opportunities"] = dict(n=len(missed), of_rejected=len(rej), by_reason=reason_counts)
    out["false_positives"] = dict(n=sum(1 for o in conf if o["exit_pct"] is not None and o["exit_pct"] <= 0),
                                  of_confirmed=len(conf),
                                  late_or_no_follow=sum(1 for o in conf if o["timing"] in ("DETECTED_LATE", "NO_FOLLOW_THROUGH")))
    evaluable = [m for m in result["day_meta"] if any(m["sufficient"].values())]
    out["history"] = dict(hr_days=len(result["days"]), evaluable_days=len(evaluable),
                          target_days=MIN_DAYS_FOR_VALIDATION,
                          status="DESCRIPTIVE_ONLY" if len(evaluable) < MIN_DAYS_FOR_VALIDATION else "VALIDATION_POSSIBLE")
    return out
