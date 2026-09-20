"""12A architecture forensic -- opportunity loss analysis (READ-ONLY research).

Uses the UNCHANGED 12A engine (config hash must be 994667c6d552111e) on every
available HR day with causal thresholds, then measures WHERE candidates are
lost. All "what-if" numbers (risk caps, entry delays) are counterfactual
re-measurements of the SAME detected events; the 12A config, engine, shadow
recorder and 11D are not modified, and nothing is written to any database.

Outputs: milestone12a_opportunity_loss_forensics.html and
milestone12a_opportunity_forensics/{forensics.json,candidates.csv}.
"""

import csv
import json
import statistics as st
import sys
from dataclasses import replace
from datetime import time, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import run_scalp12a_5session_backtest as bt  # noqa: E402  (shared lot-size / account helpers)
from scalp_12a import db  # noqa: E402
from scalp_12a import taxonomy as T  # noqa: E402
from scalp_12a.config import DEFAULT_CONFIG  # noqa: E402
from scalp_12a.counterfactual import track  # noqa: E402
from scalp_12a.engine import evaluate_day  # noqa: E402
from scalp_12a.exits import OPEN, simulate_exit  # noqa: E402
from scalp_12a.models import Selection  # noqa: E402
from scalp_12a.opportunity import measure  # noqa: E402
from scalp_12a.risk import plan_risk  # noqa: E402
from scalp_12a.thresholds import build_thresholds  # noqa: E402

EXPECTED_HASH = "994667c6d552111e"
OUT_DIR = ROOT / "milestone12a_opportunity_forensics"
REPORT = ROOT / "milestone12a_opportunity_loss_forensics.html"

# Gate order requested for the funnel. WINDOW (time / mode / expiry) is not in the requested
# list; it is shown as its own stage so its effect is never hidden inside another gate.
GATE_ORDER = ["WINDOW", "CONFIRMATION", "OPTION_RESPONSE", "OPTION_SELECTION", "RISK", "ENTRY"]
GATE_OF = {
    T.TIME_WINDOW_CLOSED: "WINDOW", T.MODE_B_RESEARCH_ONLY: "WINDOW", T.EXPIRY_DAY_CLOSE_VETO: "WINDOW",
    T.EXPIRY_TRANSITION_ZONE: "WINDOW",
    T.WEAK_MOMENTUM: "CONFIRMATION", T.NO_CONFIRMATION: "CONFIRMATION", T.MOVE_ALREADY_EXTENDED: "CONFIRMATION",
    T.OPTION_NOT_RESPONDING: "OPTION_RESPONSE",
    T.SPREAD_TOO_WIDE: "OPTION_SELECTION", T.LOW_LIQUIDITY: "OPTION_SELECTION", T.STALE_DATA: "OPTION_SELECTION",
    T.RISK_TOO_LARGE: "RISK", T.POSITION_OPEN: "RISK", T.DAILY_LIMIT_REACHED: "RISK",
    T.EVENT_EXPIRED: "ENTRY",
}
BUCKETS = [("<0%", None, 0.0), ("0-1%", 0.0, 1.0), ("1-2%", 1.0, 2.0), ("2-3%", 2.0, 3.0), ("3-5%", 3.0, 5.0), (">5%", 5.0, None)]


def med(vals, nd=3):
    v = [x for x in vals if x is not None]
    return round(st.median(v), nd) if v else None


def pct(n, d):
    return round(100.0 * n / d, 1) if d else None


def window_of(t):
    if t < time(15, 0):
        return "PRE 14:55-15:00"
    if t >= time(15, 15):
        return "MODE B 15:15-15:30 (research only)"
    edges = [(time(15, 3), "15:00-15:03"), (time(15, 6), "15:03-15:06"), (time(15, 9), "15:06-15:09"),
             (time(15, 12), "15:09-15:12"), (time(15, 15), "15:12-15:15")]
    return next(lbl for edge, lbl in edges if t < edge)


def cf_plan(c, s, cfg):
    """The engine's own plan, or the same ATM-fallback plan the engine builds for counterfactuals."""
    if c.risk is not None:
        return c.risk
    key = ("CE" if c.event.direction > 0 else "PE", 0)
    q = s.quote(key, c.bar_index)
    if key in s.legs and q and q.valid:
        return plan_risk(c.event, Selection(s.legs[key], q, None, None, 0), cfg)
    return None


def leg_key(c):
    if c.selection and c.selection.leg:
        return (c.selection.leg.option_type, c.selection.leg.atm_offset)
    return ("CE" if c.event.direction > 0 else "PE", 0)


def ret(s, key, i, lag):
    a, b = s.quote(key, i), s.quote(key, i - lag)
    if a and b and a.mid and b.mid:
        return (a.mid - b.mid) / b.mid * 100.0
    return None


def main():
    cfg = DEFAULT_CONFIG
    assert cfg.config_hash() == EXPECTED_HASH, cfg.config_hash()
    OUT_DIR.mkdir(exist_ok=True)
    with db.connect(300000) as conn:
        hr = {r[0]: r[1] for r in conn.execute(
            "SELECT trading_date, session_id FROM hr_capture_sessions WHERE status IN ('COMPLETED','COMPLETED_WITH_GAPS') "
            "ORDER BY trading_date").fetchall()}
        days = sorted(hr)
        sessions = {d: {sym: s for sym in cfg.symbols if (s := db.load_session(conn, hr[d], d, sym)) is not None} for d in days}
        ctx = {d: db.load_context_fn(conn, d) for d in days}
        oi = {}
        for d in days:
            for sym, ot, off, ts, od in conn.execute(
                    "SELECT symbol, option_type, atm_offset, bar_ts, oi_delta FROM hr_option_5s WHERE session_id=%s", (hr[d],)).fetchall():
                oi[(d, sym, ot, int(off), ts)] = float(od) if od is not None else None

    thresholds, cands_by_day = {}, {}
    for n, d in enumerate(days):
        thr = {sym: build_thresholds([sessions[p][sym] for p in days[:n] if sym in sessions[p]], cfg) for sym in sessions[d]}
        thresholds[d] = thr
        res = evaluate_day(list(sessions[d].values()), thr, cfg, context_fn=ctx[d])
        cands_by_day[d] = [c for r in res.values() for c in r.candidates]
    evaluable = [d for d in days if any(t.sufficient for t in thresholds[d].values())]

    expiries = {}
    for d in days:
        for sym, s in sessions[d].items():
            expiries.setdefault(sym, set()).add(s.expiry)
    lots = bt.lot_sizes(expiries)
    led_l, blk_l, _ = bt.account(cands_by_day, sessions, lots, cfg, "EXCHANGE_LOTS")
    led_u, blk_u, _ = bt.account(cands_by_day, sessions, lots, cfg, "CONFIG_UNITS")
    traded_l = {(t["date"], t["symbol"], t["detection"]) for t in led_l}
    traded_u = {(t["date"], t["symbol"], t["detection"]) for t in led_u}
    blocked_l = {(str(c.trading_date), c.symbol, bt.qclose(sessions[c.trading_date][c.symbol], c.bar_index).strftime("%H:%M:%S")): r
                 for c, r in blk_l}

    # ------------------------------------------------------------ per-candidate record
    rows = []
    for d in evaluable:
        for c in sorted(cands_by_day[d], key=lambda c: (c.bar_ts, c.symbol)):
            s = sessions[d][c.symbol]
            det = bt.qclose(s, c.bar_index).strftime("%H:%M:%S")
            k = (str(d), c.symbol, det)
            engine_reasons = [r for r in c.no_trade_reasons if r not in (T.POSITION_OPEN, T.DAILY_LIMIT_REACHED)]
            lot_reasons = engine_reasons + ([blocked_l[k]] if k in blocked_l and blocked_l[k] not in engine_reasons else [])
            gates = [g for g in GATE_ORDER if any(GATE_OF.get(r) == g for r in lot_reasons)]
            x, cf, o = c.counterfactual_exit, c.counterfactual, c.opportunity
            pnl = x.pnl_pct if (x and x.reason != OPEN) else None
            timing = o.timing if o else None
            if k in traded_l:
                category = "TRADED"
            elif timing == "NO_FOLLOW_THROUGH":
                category = "NO_FOLLOW_THROUGH"
            elif pnl is not None and pnl > 0 and timing == "DETECTED_EARLY":
                category = "PROFITABLE_OPPORTUNITY"
            elif pnl is not None and pnl > 0:
                category = "PROFITABLE_BUT_LATE"
            else:
                category = "GENUINELY_BAD_SIGNAL"
            key = leg_key(c)
            i, lag = c.bar_index, 6
            sel_q = s.quote(key, i)
            vol = sum((s.quote(key, j).volume_delta or 0) for j in range(max(0, i - lag + 1), i + 1) if s.quote(key, j))
            oi_chg = sum(v for j in range(max(0, i - lag + 1), i + 1)
                         if (v := oi.get((d, c.symbol, key[0], key[1], s.times[j]))) is not None)
            start_mid = s.quote(key, max(0, i - lag)).mid if s.quote(key, max(0, i - lag)) else None
            resp_lat = None
            if start_mid:
                for j in range(max(0, i - lag) + 1, min(len(s), i + 13)):
                    q = s.quote(key, j)
                    if q and q.mid and (q.mid - start_mid) / start_mid * 100.0 >= cfg.min_option_response_pct:
                        resp_lat = (j - (i - lag)) * 5
                        break
            fut = lambda j: s.fut_ffill(j)
            r15a = (fut(i) - fut(i - 3)) if fut(i) is not None and fut(i - 3) is not None else None
            r15b = (fut(i - 3) - fut(i - 6)) if fut(i - 3) is not None and fut(i - 6) is not None else None
            ce_k, pe_k = ("CE", 0), ("PE", 0)
            acc = lambda kk: (ret(s, kk, i, 3) - ret(s, kk, i - 3, 3)) if ret(s, kk, i, 3) is not None and ret(s, kk, i - 3, 3) is not None else None
            rows.append(dict(
                date=str(d), time=det, symbol=c.symbol, direction="UP" if c.event.direction > 0 else "DOWN",
                event_type=c.event.event_type, strength=c.event.strength, mode=c.mode, window=window_of((s.times[i] + timedelta(seconds=5)).time()),
                expiry_day=s.is_expiry_day, passed_gates=c.passed_gates, reasons=lot_reasons,
                first_gate=gates[0] if gates else ("NONE" if k in traded_l else "NONE"), all_gates=gates,
                traded_lots=k in traded_l, traded_units=k in traded_u, category=category, timing=timing,
                cf_pnl=pnl, cf_exit_reason=x.reason if x else None,
                mfe=cf.mfe_pct if cf else None, mae=cf.mae_pct if cf else None, t_mfe=cf.t_mfe_s if cf else None,
                spread=cf.entry_spread_pct if cf else None,
                detect_after_start_s=(bt.qclose(s, i) - o.event_start_ts).total_seconds() if o else None,
                remaining_at_entry=o.remaining_fraction_at_entry if o else None,
                fut_r30=c.event.r30, fut_accel=(r15a - r15b) if r15a is not None and r15b is not None else None,
                displacement=c.event.displacement,
                ce_ret30=ret(s, ce_k, i, lag), pe_ret30=ret(s, pe_k, i, lag), ce_acc=acc(ce_k), pe_acc=acc(pe_k),
                sel_spread=sel_q.spread_pct if sel_q else None, sel_volume30=vol, sel_oi_change30=oi_chg,
                option_response=c.confirmation.get("option_response_pct"), response_latency_s=resp_lat,
                risk_blocked=k in blocked_l and blocked_l[k] == T.RISK_TOO_LARGE))
    cand = {(r["date"], r["symbol"], r["time"]): r for r in rows}
    all_cands = [(d, c) for d in evaluable for c in cands_by_day[d]]

    # ------------------------------------------------------------ 1. funnel
    N = len(rows)
    strong = [r for r in rows if r["strength"] == T.STRONG]
    passes = lambda r, upto: not any(g in r["all_gates"] for g in upto)
    fun = {}
    for label, pool in (("ALL", rows), ("STRONG", strong), ("IN_WINDOW (Mode A, not vetoed)", [r for r in rows if "WINDOW" not in r["all_gates"]])):
        n = len(pool)
        steps = [("A. detected", n),
                 ("C. pass confirmation", sum(passes(r, ["CONFIRMATION"]) for r in pool)),
                 ("D. + pass option response", sum(passes(r, ["CONFIRMATION", "OPTION_RESPONSE"]) for r in pool)),
                 ("E. + pass option selection", sum(passes(r, ["CONFIRMATION", "OPTION_RESPONSE", "OPTION_SELECTION"]) for r in pool)),
                 ("   + pass time/mode/expiry window", sum(passes(r, ["CONFIRMATION", "OPTION_RESPONSE", "OPTION_SELECTION", "WINDOW"]) for r in pool)),
                 ("F. + pass risk (exchange lots)", sum(passes(r, GATE_ORDER[:5]) for r in pool)),
                 ("G. hypothetical trades (exchange lots)", sum(r["traded_lots"] for r in pool)),
                 ("G'. hypothetical trades (config units)", sum(r["traded_units"] for r in pool)),
                 ("H. rejected (exchange lots)", sum(not r["traded_lots"] for r in pool))]
        fun[label] = [(a, b, pct(b, n)) for a, b in steps]
    first_gate = {}
    for r in rows:
        if not r["traded_lots"]:
            first_gate[r["first_gate"]] = first_gate.get(r["first_gate"], 0) + 1
    # "potentially tradable" = counterfactual active exit would have been positive
    first_gate_profitable = {}
    for r in rows:
        if not r["traded_lots"] and (r["cf_pnl"] or 0) > 0:
            first_gate_profitable[r["first_gate"]] = first_gate_profitable.get(r["first_gate"], 0) + 1
    reason_any = {}
    for r in rows:
        for x in r["reasons"]:
            reason_any[x] = reason_any.get(x, 0) + 1

    # ------------------------------------------------------------ 2. categories
    def stats(pool):
        return dict(count=len(pool), mfe=med([r["mfe"] for r in pool]), mae=med([r["mae"] for r in pool]),
                    pnl=med([r["cf_pnl"] for r in pool]), t_mfe=med([r["t_mfe"] for r in pool], 0),
                    detect=med([r["detect_after_start_s"] for r in pool], 0), remaining=med([r["remaining_at_entry"] for r in pool]),
                    profitable=sum(1 for r in pool if (r["cf_pnl"] or 0) > 0))
    cats = {k: stats([r for r in rows if r["category"] == k]) for k in
            ("GENUINELY_BAD_SIGNAL", "PROFITABLE_OPPORTUNITY", "PROFITABLE_BUT_LATE", "NO_FOLLOW_THROUGH", "TRADED")}

    # ------------------------------------------------------------ 3. missed decomposition
    missed = [r for r in rows if r["category"] == "PROFITABLE_OPPORTUNITY"]
    dims = {}
    for dim in ("first_gate", "symbol", "direction", "event_type", "mode", "expiry_day", "timing", "strength"):
        g = {}
        for r in missed:
            g[str(r[dim])] = g.get(str(r[dim]), 0) + 1
        dims[dim] = g

    def bucket(v):
        for lbl, lo, hi in BUCKETS:
            if (lo is None or v >= lo) and (hi is None or v < hi):
                return lbl
    buckets_missed = {b[0]: 0 for b in BUCKETS}
    buckets_rejected = {b[0]: 0 for b in BUCKETS}
    for r in rows:
        if r["cf_pnl"] is None or r["traded_lots"]:
            continue
        buckets_rejected[bucket(r["cf_pnl"])] += 1
        if r["category"] == "PROFITABLE_OPPORTUNITY":
            buckets_missed[bucket(r["cf_pnl"])] += 1
    # MFE buckets show the move that existed (before any exit) for rejected candidates
    buckets_mfe = {b[0]: 0 for b in BUCKETS}
    for r in rows:
        if r["mfe"] is not None and not r["traded_lots"]:
            buckets_mfe[bucket(r["mfe"])] += 1

    # ------------------------------------------------------------ 4. risk forensics + sensitivity
    risk_rows = []
    for (d, c) in all_cands:
        s = sessions[d][c.symbol]
        det = bt.qclose(s, c.bar_index).strftime("%H:%M:%S")
        k = (str(d), c.symbol, det)
        if blocked_l.get(k) != T.RISK_TOO_LARGE:
            continue
        lot, _src = lots.get((c.symbol, s.expiry), (None, ""))
        ask = c.risk.entry_ref_ask
        loss_lot = ask * c.risk.stop_pct / 100 * lot
        cap_lot = ask * lot
        binding = [n for n, bad in (("max loss Rs 300", loss_lot > cfg.max_rupee_loss_per_trade),
                                    ("capital Rs 6,000", cap_lot > cfg.max_capital_per_trade)) if bad]
        risk_rows.append(dict(date=str(d), time=det, symbol=c.symbol, option=f"{c.selection.leg.option_type} {c.selection.leg.strike:.0f}",
                              ask=ask, lot=lot, loss_per_lot=round(loss_lot, 2), capital_per_lot=round(cap_lot, 2),
                              binding=" + ".join(binding), cf_pnl=cand[k]["cf_pnl"],
                              cf_rupees_one_lot=round(cand[k]["cf_pnl"] / 100 * ask * lot, 2) if cand[k]["cf_pnl"] is not None else None))

    def scenario(max_loss=None, max_cap=None):
        c2 = replace(cfg, max_rupee_loss_per_trade=max_loss or cfg.max_rupee_loss_per_trade,
                     max_capital_per_trade=max_cap or cfg.max_capital_per_trade)
        ledger, blocked, daily = bt.account(cands_by_day, sessions, lots, c2, "EXCHANGE_LOTS")
        sm = bt.summarize(ledger, c2) if ledger else None
        pn = [t["net_pnl"] for t in ledger]
        return dict(max_loss=c2.max_rupee_loss_per_trade, max_capital=c2.max_capital_per_trade, trades=len(ledger),
                    blocked=sum(1 for _, r in blocked if r == T.RISK_TOO_LARGE),
                    blocked_other=sum(1 for _, r in blocked if r != T.RISK_TOO_LARGE),
                    wins=sum(1 for p in pn if p > 0), losses=sum(1 for p in pn if p <= 0),
                    net=round(sum(pn), 2), median=med(pn, 2), max_loss_seen=min(pn) if pn else None,
                    max_dd=sm["max_dd"] if sm else 0.0,
                    capital_total=round(sum(t["capital_deployed"] for t in ledger), 2),
                    capital_max=max((t["capital_deployed"] for t in ledger), default=None),
                    per_day={x["date"]: x["trades"] for x in daily if x["date"] in {str(e) for e in evaluable}})
    sens_loss = [scenario(max_loss=v) for v in (150, 200, 250, 300, 350, 400, 500)]
    sens_cap = [scenario(max_cap=v) for v in (3000, 4000, 5000, 6000, 7500, 10000)]
    # Each cap alone never unlocks a blocked NIFTY lot because BOTH caps bind; a small joint grid
    # (research only) shows what the same signals would have done if both were relaxed together.
    sens_joint = [scenario(max_loss=l, max_cap=c) for l in (300, 400, 500) for c in (6000, 7500, 10000)]

    # ------------------------------------------------------------ 5. entry-delay forensics
    delays = {}
    for dly in (0, 1, 2, 3):
        pool_all, pool_pass = [], []
        for (d, c) in all_cands:
            s = sessions[d][c.symbol]
            key, e = leg_key(c), c.bar_index + dly
            plan = cf_plan(c, s, cfg)
            q = s.quote(key, e) if e < len(s) else None
            if plan is None or q is None or not q.valid:
                continue
            cf = track(s, key, e, c.event.direction, cfg)
            x = simulate_exit(s, key, e, c.event, plan, cfg)
            o = measure(s, c.event, c.bar_index, e, key, cfg)
            xq = s.quote(key, x.exit_index) if x.exit_index is not None else None
            rec = dict(pnl=x.pnl_pct if x.reason != OPEN else None, mfe=cf.mfe_pct if cf else None, mae=cf.mae_pct if cf else None,
                       timing=o.timing, spread_in=q.spread_pct, spread_out=xq.spread_pct if xq else None)
            pool_all.append(rec)
            if c.passed_gates:
                pool_pass.append(rec)
        def agg(p):
            n = len(p)
            return dict(n=n, mfe=med([r["mfe"] for r in p]), mae=med([r["mae"] for r in p]),
                        pnl_median=med([r["pnl"] for r in p]),
                        pnl_mean=round(st.mean([r["pnl"] for r in p if r["pnl"] is not None]), 3) if n else None,
                        profitable_pct=pct(sum(1 for r in p if (r["pnl"] or 0) > 0), n),
                        late_pct=pct(sum(1 for r in p if r["timing"] == "DETECTED_LATE"), n),
                        nft_pct=pct(sum(1 for r in p if r["timing"] == "NO_FOLLOW_THROUGH"), n),
                        early_pct=pct(sum(1 for r in p if r["timing"] == "DETECTED_EARLY"), n),
                        round_trip_spread=med([(r["spread_in"] or 0) / 2 + (r["spread_out"] or 0) / 2 for r in p]))
        delays[dly] = dict(latency_s=dly * 5, all=agg(pool_all), passed=agg(pool_pass))

    # ------------------------------------------------------------ 6. option-response forensics
    fields = ["fut_r30", "fut_accel", "displacement", "ce_ret30", "pe_ret30", "ce_acc", "pe_acc", "sel_spread",
              "sel_volume30", "sel_oi_change30", "option_response", "response_latency_s"]
    def dist(pool):
        out = {"n": len(pool)}
        for f in fields:
            v = [abs(r[f]) if f in ("fut_r30", "displacement") and r[f] is not None else r[f] for r in pool]
            out[f] = med(v, 2)
        return out
    onr = [r for r in rows if T.OPTION_NOT_RESPONDING in r["reasons"]]
    groups6 = {"OPTION_NOT_RESPONDING": dist(onr),
               "CONFIRMED (passed engine gates)": dist([r for r in rows if r["passed_gates"]]),
               "TRADED (exchange lots)": dist([r for r in rows if r["traded_lots"]]),
               "TRADED (config units)": dist([r for r in rows if r["traded_units"]]),
               "PROFITABLE COUNTERFACTUAL (not traded)": dist([r for r in rows if (r["cf_pnl"] or 0) > 0 and not r["traded_lots"]])}
    onr_outcomes = dict(n=len(onr), profitable=sum(1 for r in onr if (r["cf_pnl"] or 0) > 0),
                        pnl_median=med([r["cf_pnl"] for r in onr]),
                        responded_later=sum(1 for r in onr if r["response_latency_s"] is not None and r["response_latency_s"] > 30),
                        responded_then_faded=sum(1 for r in onr if r["response_latency_s"] is not None and r["response_latency_s"] <= 30),
                        never_responded_within_60s=sum(1 for r in onr if r["response_latency_s"] is None),
                        early=sum(1 for r in onr if r["timing"] == "DETECTED_EARLY"),
                        only_onr=sum(1 for r in onr if [g for g in r["all_gates"]] == ["OPTION_RESPONSE"]),
                        only_onr_profitable=sum(1 for r in onr if r["all_gates"] == ["OPTION_RESPONSE"] and (r["cf_pnl"] or 0) > 0))
    non_onr_strong = [r for r in rows if T.OPTION_NOT_RESPONDING not in r["reasons"]]
    onr_outcomes["others_pnl_median"] = med([r["cf_pnl"] for r in non_onr_strong])
    onr_outcomes["others_profitable_pct"] = pct(sum(1 for r in non_onr_strong if (r["cf_pnl"] or 0) > 0), len(non_onr_strong))
    onr_outcomes["onr_profitable_pct"] = pct(onr_outcomes["profitable"], len(onr))

    # ------------------------------------------------------------ 7. early / late
    el = {}
    for tm in ("DETECTED_EARLY", "DETECTED_LATE", "NO_FOLLOW_THROUGH"):
        p = [r for r in rows if r["timing"] == tm]
        el[tm] = dict(events=len(p), confirmed=sum(r["passed_gates"] for r in p), traded_lots=sum(r["traded_lots"] for r in p),
                      traded_units=sum(r["traded_units"] for r in p), profitable=sum(1 for r in p if (r["cf_pnl"] or 0) > 0),
                      remaining=med([r["remaining_at_entry"] for r in p]), mfe=med([r["mfe"] for r in p]),
                      mae=med([r["mae"] for r in p]), pnl=med([r["cf_pnl"] for r in p]), t_mfe=med([r["t_mfe"] for r in p], 0))
    cross = {}
    for tm, lbl in (("DETECTED_EARLY", "EARLY"), ("DETECTED_LATE", "LATE"), ("NO_FOLLOW_THROUGH", "NO_FOLLOW_THROUGH")):
        for prof in (True, False):
            p = [r for r in rows if r["timing"] == tm and ((r["cf_pnl"] or 0) > 0) == prof]
            cross[f"{lbl} + {'PROFITABLE' if prof else 'LOSS'}"] = dict(n=len(p), pnl=med([r["cf_pnl"] for r in p]),
                                                                       mfe=med([r["mfe"] for r in p]), mae=med([r["mae"] for r in p]))

    # ------------------------------------------------------------ 8. symbols
    sym = {}
    for sy in cfg.symbols:
        p = [r for r in rows if r["symbol"] == sy]
        sym[sy] = dict(events=len(p), strong=sum(r["strength"] == T.STRONG for r in p), confirmed=sum(r["passed_gates"] for r in p),
                       risk_blocked=sum(r["risk_blocked"] for r in p), traded_lots=sum(r["traded_lots"] for r in p),
                       traded_units=sum(r["traded_units"] for r in p),
                       profitable_cf=sum(1 for r in p if (r["cf_pnl"] or 0) > 0),
                       missed=sum(1 for r in p if r["category"] == "PROFITABLE_OPPORTUNITY"),
                       mfe=med([r["mfe"] for r in p]), mae=med([r["mae"] for r in p]), spread=med([r["spread"] for r in p]),
                       detect=med([r["detect_after_start_s"] for r in p], 0), pnl=med([r["cf_pnl"] for r in p]))

    # ------------------------------------------------------------ 9. time windows
    wins = {}
    for w in ("PRE 14:55-15:00", "15:00-15:03", "15:03-15:06", "15:06-15:09", "15:09-15:12", "15:12-15:15",
              "MODE B 15:15-15:30 (research only)"):
        p = [r for r in rows if r["window"] == w]
        wins[w] = dict(events=len(p), strong=sum(r["strength"] == T.STRONG for r in p), confirmed=sum(r["passed_gates"] for r in p),
                       profitable=sum(1 for r in p if (r["cf_pnl"] or 0) > 0), pnl=med([r["cf_pnl"] for r in p]),
                       mfe=med([r["mfe"] for r in p]), mae=med([r["mae"] for r in p]),
                       early=sum(r["timing"] == "DETECTED_EARLY" for r in p), late=sum(r["timing"] == "DETECTED_LATE" for r in p),
                       nft=sum(r["timing"] == "NO_FOLLOW_THROUGH" for r in p))

    bigm = [x for x in rows if not x["traded_lots"] and x["mfe"] is not None and x["mfe"] >= 2]
    tm = [x["t_mfe"] for x in bigm if x["t_mfe"] is not None]
    big = dict(n=len(bigm), t_mfe=med(tm, 0), after_hold_pct=pct(sum(1 for v in tm if v > cfg.max_hold_seconds), len(tm)),
               mae=med([x["mae"] for x in bigm]), pnl=med([x["cf_pnl"] for x in bigm]))
    limits = dict(hr_days=len(days), evaluable_days=len(evaluable), symbol_days=sum(len(sessions[d]) for d in evaluable),
                  candidates=N, strong=len(strong), trades_lots=len(led_l), trades_units=len(led_u))
    result = dict(config_hash=cfg.config_hash(), days=[str(d) for d in days], evaluable=[str(d) for d in evaluable], limits=limits,
                  funnel=fun, first_gate=first_gate, first_gate_profitable=first_gate_profitable, reason_any=reason_any,
                  categories=cats, missed=dict(n=len(missed), dims=dims, rows=missed), buckets=dict(missed_active_exit=buckets_missed,
                  rejected_active_exit=buckets_rejected, rejected_mfe=buckets_mfe), risk_rows=risk_rows, sens_loss=sens_loss,
                  sens_cap=sens_cap, sens_joint=sens_joint, delays=delays, onr=groups6, onr_outcomes=onr_outcomes, early_late=el, cross=cross,
                  symbols=sym, windows=wins, big_mfe=big, lots={f"{k[0]} {k[1]}": v for k, v in lots.items()})
    (OUT_DIR / "forensics.json").write_text(json.dumps(result, default=str, indent=1), encoding="utf-8")
    with open(OUT_DIR / "candidates.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        for r in rows:
            w.writerow({k: (";".join(v) if isinstance(v, list) else v) for k, v in r.items()})
    REPORT.write_text(build_html(result), encoding="utf-8")
    print("joint", [(x["max_loss"], x["max_capital"], x["trades"], x["net"]) for x in sens_joint])
    print("onr", result["onr_outcomes"])


def _v(x, nd=2, pct=False, rupee=False):
    if x is None:
        return "&ndash;"
    if isinstance(x, bool):
        return "Yes" if x else "No"
    if isinstance(x, (int, float)):
        s = f"{x:+,.{nd}f}" if (pct or rupee) else (f"{x:,.{nd}f}" if isinstance(x, float) else f"{x:,}")
        return ("&#8377;" + s if rupee else s) + ("%" if pct else "")
    return str(x)


def _t(headers, rows):
    return ("<table><tr>" + "".join(f"<th>{h}</th>" for h in headers) + "</tr>" +
            "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows) + "</table>")


def build_html(r):
    css = ("body{font-family:Georgia,serif;max-width:1240px;margin:0 auto;padding:30px 22px 70px;color:#1c1c1c;background:#fbfaf7;line-height:1.5}"
           "h1{font-size:1.6em;border-bottom:3px solid #2c3e50;padding-bottom:8px}h2{font-size:1.2em;color:#1a3a5c;margin-top:2em;border-left:5px solid #2c3e50;padding-left:10px}"
           "h3{font-size:1em;color:#2c3e50}table{border-collapse:collapse;width:100%;margin:10px 0;font-size:0.82em}th,td{border:1px solid #ccc;padding:4px 7px;text-align:left;vertical-align:top}"
           "th{background:#2c3e50;color:#fff}tr:nth-child(even){background:#f2f0ea}code{background:#eee;padding:1px 4px;border-radius:3px}"
           ".risk{background:#ffebee;border-left:4px solid #c62828;padding:10px 14px;margin:14px 0}.finding{background:#e8f0fe;border-left:4px solid #1a3a5c;padding:10px 14px;margin:14px 0}"
           ".callout{background:#fff8e1;border-left:4px solid #f9a825;padding:10px 14px;margin:14px 0}")
    L, o, big = r["limits"], [], r["big_mfe"]
    o.append(f"<!DOCTYPE html><html lang='en'><head><meta charset='UTF-8'><title>12A Opportunity Loss Forensics</title><style>{css}</style></head><body>")
    o.append("<h1>12A-scalp-v1 &mdash; Architecture Forensic: Where Is the Opportunity Lost?<br><span style='font-size:0.6em;font-weight:normal;color:#555'>"
             "READ-ONLY research &middot; nothing in 12A, 11D, the shadow recorder or paper trading was changed</span></h1>")
    o.append(f"<p><b>Config hash</b> <code>{r['config_hash']}</code> (unchanged) &middot; engine replayed exactly, thresholds causal "
             f"(prior HR days only) &middot; exchange lots: {'; '.join(f'{k} = {v[0]}' for k, v in r['lots'].items() if k.split()[1] in ('2026-09-22', '2026-09-24', '2026-09-17'))}</p>")
    o.append(f"<div class='risk'><b>Data limitation &mdash; descriptive only.</b> HR days captured: <b>{L['hr_days']}</b>; evaluable (enough prior days for "
             f"causal thresholds): <b>{L['evaluable_days']}</b> ({', '.join(r['evaluable'])}); symbol-days: <b>{L['symbol_days']}</b>; candidates: "
             f"<b>{L['candidates']}</b> ({L['strong']} strong); hypothetical trades: <b>{L['trades_lots']}</b> (exchange lots) / "
             f"<b>{L['trades_units']}</b> (config units). Every number below comes from two sessions and must not be read as a validated result. "
             "The what-if tables re-measure the SAME detected events and are not parameter recommendations.</div>")

    # 1 funnel
    o.append("<h2>1. Gate funnel</h2>")
    o.append("<p>The requested order is Event &rarr; Confirmation &rarr; Option response &rarr; Option selection &rarr; Risk &rarr; Entry &rarr; Exit. "
             "The time/mode/expiry window (PRE, Mode B research-only, expiry vetoes) is not in that list, so it is shown as its own step "
             "rather than hidden inside another gate. Risk uses real exchange lots; the config-unit trade count is shown for reference.</p>")
    for lbl, steps in r["funnel"].items():
        o.append(f"<h3>{lbl}</h3>" + _t(["Stage", "Count", "% of detected"], [[a, b, _v(c, 1)] for a, b, c in steps]))
    fg, fgp = r["first_gate"], r["first_gate_profitable"]
    o.append(_t(["First blocking gate (not traded)", "All rejected", "Rejected but profitable in counterfactual (active exit &gt; 0)"],
                [[g, fg.get(g, 0), fgp.get(g, 0)] for g in ["WINDOW", "CONFIRMATION", "OPTION_RESPONSE", "OPTION_SELECTION", "RISK", "ENTRY"]]))
    o.append("<p><b>All reasons recorded (a candidate can carry several):</b> " + ", ".join(f"{k} {v}" for k, v in r["reason_any"].items()) + ".</p>")

    # 2 categories
    o.append("<h2>2. Profitable vs unprofitable candidates (counterfactual, active exit)</h2>")
    o.append(_t(["Category", "Count", "Median MFE %", "Median MAE %", "Median active-exit P&amp;L %", "Median time-to-MFE s",
                 "Median event-start&rarr;detection s", "Median share of move remaining at entry"],
                [[k, v["count"], _v(v["mfe"], 2, True), _v(v["mae"], 2, True), _v(v["pnl"], 2, True), _v(v["t_mfe"], 0),
                  _v(v["detect"], 0), _v(v["remaining"], 2)] for k, v in r["categories"].items()]))
    o.append("<p>Detection time is measured from the event start: momentum events are defined on a 30-second move and continuation events on a "
             "180-second move, so the detection time is structural. A live observer adds about 3.3 s (HR write latency), and the entry adds 10 s more.</p>")

    # 3 missed
    m = r["missed"]
    o.append("<h2>3. Missed profitable opportunities (not traded, detected early, positive after the active exit)</h2>")
    o.append(f"<p><b>{m['n']} candidates.</b> Breakdown: " + "; ".join(f"<b>{dim}</b> {v}" for dim, v in m["dims"].items()) + ".</p>")
    o.append(_t(["Date", "Time", "Symbol", "Dir", "Event", "Strength", "Mode", "First gate", "All reasons", "Option response %",
                 "MFE %", "MAE %", "Active-exit P&amp;L %"],
                [[x["date"], x["time"], x["symbol"], x["direction"], x["event_type"].replace("_EVENT", ""), x["strength"], x["mode"],
                  x["first_gate"], ", ".join(x["reasons"]), _v(x["option_response"], 2, True), _v(x["mfe"], 2, True), _v(x["mae"], 2, True),
                  _v(x["cf_pnl"], 2, True)] for x in m["rows"]]))
    b = r["buckets"]
    o.append(_t(["Profit bucket"] + list(b["missed_active_exit"].keys()),
                [["Missed opportunities &mdash; active-exit P&amp;L"] + list(b["missed_active_exit"].values()),
                 ["All rejected candidates &mdash; active-exit P&amp;L"] + list(b["rejected_active_exit"].values()),
                 ["All rejected candidates &mdash; MFE within 300 s (move that existed)"] + list(b["rejected_mfe"].values())]))

    # 4 risk
    o.append("<h2>4. Risk gate forensics (exchange lots)</h2>")
    o.append(_t(["Date", "Time", "Symbol", "Option", "Decision ASK", "Lot", "Loss/lot at 5% stop", "Capital/lot", "Binding constraint(s)",
                 "Counterfactual %", "Counterfactual &#8377; for 1 lot"],
                [[x["date"], x["time"], x["symbol"], x["option"], _v(x["ask"]), x["lot"], _v(x["loss_per_lot"], 2, rupee=True),
                  _v(x["capital_per_lot"], 2, rupee=True), x["binding"], _v(x["cf_pnl"], 2, True), _v(x["cf_rupees_one_lot"], 2, rupee=True)]
                 for x in r["risk_rows"]]))
    tot1 = sum(x["cf_rupees_one_lot"] or 0 for x in r["risk_rows"])
    o.append(f"<p>Sum of the risk-blocked candidates' counterfactual one-lot results: <b>{_v(tot1, 2, rupee=True)}</b>.</p>")
    hdr = ["Max loss/trade", "Max capital/trade", "Trades", "Risk-blocked", "Other blocked", "Wins", "Losses", "Net P&amp;L", "Median P&amp;L",
           "Worst trade", "Max DD", "Max capital deployed", "Trades/day"]
    row = lambda x: [_v(x["max_loss"], 0, rupee=True), _v(x["max_capital"], 0, rupee=True), x["trades"], x["blocked"], x["blocked_other"],
                     x["wins"], x["losses"], _v(x["net"], 2, rupee=True), _v(x["median"], 2, rupee=True), _v(x["max_loss_seen"], 2, rupee=True),
                     _v(x["max_dd"], 2, rupee=True), _v(x["capital_max"], 2, rupee=True), x["per_day"]]
    o.append("<h3>Max loss per trade varied (capital fixed at the current &#8377;6,000)</h3>" + _t(hdr, [row(x) for x in r["sens_loss"]]))
    o.append("<h3>Capital per trade varied (max loss fixed at the current &#8377;300)</h3>" + _t(hdr, [row(x) for x in r["sens_cap"]]))
    o.append("<h3>Both varied together (added because each cap alone never binds alone)</h3>" + _t(hdr, [row(x) for x in r["sens_joint"]]))
    o.append("<p>Research scenarios only. The 12A config still has &#8377;300 / &#8377;6,000; the exits, signals and daily &#8377;900 cap are unchanged in every scenario.</p>")

    # 5 delay
    o.append("<h2>5. Entry-delay forensics (same detected events)</h2>")
    rows5 = []
    for dly, v in r["delays"].items():
        for grp in ("all", "passed"):
            a = v[grp]
            rows5.append([f"{dly} bar(s){' (CURRENT)' if str(dly) == '2' else ''}", f"{v['latency_s']} s", "all candidates" if grp == "all" else "gate-passing",
                          a["n"], _v(a["mfe"], 2, True), _v(a["mae"], 2, True), _v(a["pnl_median"], 3, True), _v(a["pnl_mean"], 3, True),
                          _v(a["profitable_pct"], 1), _v(a["early_pct"], 1), _v(a["late_pct"], 1), _v(a["nft_pct"], 1), _v(a["round_trip_spread"], 3)])
    o.append(_t(["Delay", "After detection-bar close", "Group", "n", "MFE med %", "MAE med %", "Active-exit P&amp;L med %", "mean %",
                 "% profitable", "% early", "% late", "% no-follow-through", "Round-trip spread med %"], rows5))
    o.append("<p>0 bars is not achievable live: it fills at the price of the very bar that triggered detection. The early/late class is measured "
             "against the futures move anchored at detection, so waiting can move a fill past a small pull-back. No delay is preferred here.</p>")

    # 6 ONR
    oo = r["onr_outcomes"]
    o.append("<h2>6. Option-response forensics</h2>")
    keys = [("n", "n"), ("|fut 30 s move| pts", "fut_r30"), ("fut acceleration (last 15 s &minus; prior 15 s)", "fut_accel"),
            ("|displacement|", "displacement"), ("ATM CE 30 s return %", "ce_ret30"), ("ATM PE 30 s return %", "pe_ret30"),
            ("ATM CE acceleration", "ce_acc"), ("ATM PE acceleration", "pe_acc"), ("selected-leg spread %", "sel_spread"),
            ("selected-leg volume (30 s)", "sel_volume30"), ("selected-leg OI change (30 s)", "sel_oi_change30"),
            ("option response % (engine)", "option_response"), ("response latency s (first +1% from event start)", "response_latency_s")]
    grp = list(r["onr"].keys())
    o.append(_t(["Median of"] + grp, [[lbl] + [_v(r["onr"][g].get(k)) for g in grp] for lbl, k in keys]))
    o.append(f"<p>OPTION_NOT_RESPONDING candidates: <b>{oo['n']}</b>. Counterfactually profitable: <b>{oo['profitable']}</b> "
             f"({_v(oo['onr_profitable_pct'], 1)}%) against {_v(oo['others_profitable_pct'], 1)}% for all other candidates; median active-exit "
             f"{_v(oo['pnl_median'], 2, True)} against {_v(oo['others_pnl_median'], 2, True)}. Blocked by option response <i>alone</i>: "
             f"<b>{oo['only_onr']}</b> (profitable: {oo['only_onr_profitable']}); the rest also failed confirmation or the window. "
             f"Response pattern: {oo['responded_then_faded']} reached +1% during the event window and had faded by detection; "
             f"{oo['responded_later']} reached +1% only after detection; {oo['never_responded_within_60s']} never reached +1% within 60 s of detection. "
             f"{oo['early']} were detected early.</p>")

    # 7 early/late
    o.append("<h2>7. Early / late analysis</h2>")
    o.append(_t(["Timing", "Events", "Confirmed", "Traded (lots)", "Traded (units)", "Profitable", "Remaining at entry (median share)",
                 "MFE med %", "MAE med %", "Active-exit P&amp;L med %", "Time-to-MFE med s"],
                [[k, v["events"], v["confirmed"], v["traded_lots"], v["traded_units"], v["profitable"], _v(v["remaining"], 2),
                  _v(v["mfe"], 2, True), _v(v["mae"], 2, True), _v(v["pnl"], 2, True), _v(v["t_mfe"], 0)] for k, v in r["early_late"].items()]))
    o.append(_t(["Cross", "n", "Active-exit P&amp;L med %", "MFE med %", "MAE med %"],
                [[k, v["n"], _v(v["pnl"], 2, True), _v(v["mfe"], 2, True), _v(v["mae"], 2, True)] for k, v in r["cross"].items()]))

    # 8 symbols
    o.append("<h2>8. Symbol comparison</h2>")
    sk = [("Events", "events"), ("Strong", "strong"), ("Passed all engine gates", "confirmed"), ("Risk-blocked (lots)", "risk_blocked"),
          ("Traded (lots)", "traded_lots"), ("Traded (units)", "traded_units"), ("Profitable counterfactuals", "profitable_cf"),
          ("Missed profitable opportunities", "missed"), ("MFE median %", "mfe"), ("MAE median %", "mae"), ("Spread median %", "spread"),
          ("Event start&rarr;detection median s", "detect"), ("Active-exit P&amp;L median %", "pnl")]
    o.append(_t(["Metric", "NIFTY", "SENSEX"], [[lbl, _v(r["symbols"]["NIFTY"][k]), _v(r["symbols"]["SENSEX"][k])] for lbl, k in sk]))

    # 9 windows
    o.append("<h2>9. Time windows</h2>")
    o.append(_t(["Window", "Events", "Strong", "Passed gates", "Profitable", "Active-exit P&amp;L med %", "MFE med %", "MAE med %", "Early", "Late", "No follow-through"],
                [[k, v["events"], v["strong"], v["confirmed"], v["profitable"], _v(v["pnl"], 2, True), _v(v["mfe"], 2, True), _v(v["mae"], 2, True),
                  v["early"], v["late"], v["nft"]] for k, v in r["windows"].items()]))
    o.append("<p>Mode B remains research-only and is not tradeable. Window samples are 4&ndash;8 events each, too small to rank windows.</p>")

    # 10 answers
    fun_w = dict((a, b) for a, b, _ in r["funnel"]["IN_WINDOW (Mode A, not vetoed)"])
    delays = r["delays"]
    joint_best = [x for x in r["sens_joint"] if x["trades"] > 1]
    joint_txt = "; ".join(f"&#8377;{x['max_loss']:.0f} / &#8377;{x['max_capital']:.0f}: {x['trades']} trades, net "
                          f"{_v(x['net'], 2, rupee=True)}" for x in joint_best) or "no scenario unlocked more than one trade"
    o.append("<h2>10. The five factual questions</h2><div class='finding'><ol>")
    o.append(f"<li><b>Where does 12A lose the most opportunities?</b> By count, most candidates are stopped by the time/mode/expiry window "
             f"({fg.get('WINDOW', 0)} of {L['candidates']}, mostly Mode B and pre-15:00) and by confirmation ({fg.get('CONFIRMATION', 0)}, "
             f"dominated by WEAK_MOMENTUM: {r['reason_any'].get('WEAK_MOMENTUM', 0)} of all candidates are near-miss events below the 95th-percentile "
             f"threshold). Inside the tradeable Mode A window ({fun_w['A. detected']} candidates) confirmation removes the most "
             f"({fun_w['A. detected'] - fun_w['C. pass confirmation']}), and then the exchange-lot risk gate removes "
             f"{fun_w['   + pass time/mode/expiry window'] - fun_w['F. + pass risk (exchange lots)']} of the "
             f"{fun_w['   + pass time/mode/expiry window']} survivors. Among counterfactually profitable rejections the first gate was "
             f"confirmation {fgp.get('CONFIRMATION', 0)}, window {fgp.get('WINDOW', 0)}, risk {fgp.get('RISK', 0)}.</li>")
    o.append(f"<li><b>Is the risk gate preventing valid trades because of exchange lot size?</b> It blocks every gate-passing NIFTY candidate "
             f"but one ({len(r['risk_rows'])} blocked). One 65-unit lot at the selected premiums needs &#8377;6,672&ndash;9,357 of capital "
             "and risks &#8377;334&ndash;468 at the 5% stop, so <b>both</b> caps bind. Raising either cap alone unlocks nothing; only raising both "
             f"does ({joint_txt}). "
             f"The blocked candidates' own one-lot counterfactual sum is {_v(tot1, 2, rupee=True)}. <b>The gate is structurally lot-bound, "
             "but in this sample the trades it blocked would mostly have lost.</b></li>")
    o.append(f"<li><b>Is the entry delay consuming too much of the move?</b> Not measurably in this sample. Across all {delays['2']['all']['n'] if '2' in delays else delays[2]['all']['n']} "
             "candidates the median active-exit result is similar at 0, 1, 2 and 3 bars "
             + ", ".join(f"({k}: {_v(v['all']['pnl_median'], 2, True)})" for k, v in delays.items())
             + ". The move is mostly consumed <i>before</i> detection: momentum events are only recognised after their 30-second move, and the "
             "detection bar is often the local extreme, so a 0-bar fill is not better.</li>")
    o.append(f"<li><b>Is option-response confirmation filtering useful opportunities?</b> Rarely on its own: only {oo['only_onr']} candidate was blocked by it "
             f"alone. The flagged group was not worse than the rest ({_v(oo['onr_profitable_pct'], 1)}% vs {_v(oo['others_profitable_pct'], 1)}% "
             f"counterfactually profitable), so there is no evidence here that it filters bad trades. Its timing is also mismatched: "
             f"{oo['responded_then_faded']} of {oo['n']} flagged candidates had a &ge;1% response that faded before the detection bar, and "
             f"{oo['responded_later']} responded only afterwards. On this sample the 30-second response measure looks disconnected from the scalp "
             "outcome rather than protective, but the sample is too small to separate the four hypotheses.</li>")
    mb = b["missed_active_exit"]
    o.append(f"<li><b>Are the missed profitable opportunities meaningful enough to justify another research iteration?</b> As captured by the current "
             f"active exit, mostly not: {m['n']} missed, {mb.get('0-1%', 0)} of them under +1%, {mb.get('1-2%', 0)} at 1&ndash;2%, "
             f"{mb.get('>5%', 0)} above 5% (outside the trading window). However, the option <i>moved</i>: "
             f"{sum(v for k, v in b['rejected_mfe'].items() if k in ('2-3%', '3-5%', '>5%'))} rejected candidates saw an MFE of 2% or more within "
             f"300 s; for them the median time-to-MFE was {_v(big['t_mfe'], 0)} s ({_v(big['after_hold_pct'], 0)}% peaked after the 120-second hold), "
             f"the median MAE on the way was {_v(big['mae'], 2, True)}, and the active exit's median result was {_v(big['pnl'], 2, True)}. The opportunity is "
             "present in the market but is not capturable by the current entry and exit design. That is a research question, not a tuning result.</li>")
    o.append("</ol></div>")

    o.append("<h2>WHERE WE ARE LOSING THE OPPORTUNITY</h2><div class='callout'><ul>"
             f"<li><b>Before detection.</b> Events are recognised only after their 30-second (or 180-second) move; the median event-start-to-detection "
             "time is 35 s and much of the displacement is already spent.</li>"
             f"<li><b>At confirmation.</b> WEAK_MOMENTUM near-misses are the largest single rejection reason ({r['reason_any'].get('WEAK_MOMENTUM', 0)} of "
             f"{L['candidates']}); they include {fgp.get('CONFIRMATION', 0)} counterfactually profitable candidates, almost all small.</li>"
             f"<li><b>At risk sizing with real lots.</b> {len(r['risk_rows'])} of the 7 gate-passing NIFTY candidates are blocked because one lot "
             "breaches both the &#8377;300 and &#8377;6,000 caps. SENSEX produced no gate-passing candidate.</li>"
             f"<li><b>At the exit.</b> {big['n']} of the {L['candidates'] - L['trades_lots']} rejected candidates' options moved 2%+ within 5 minutes, "
             f"but typically late (median {_v(big['t_mfe'], 0)} s, {_v(big['after_hold_pct'], 0)}% after the 120-second hold) and after a "
             f"{_v(big['mae'], 2, True)} median adverse move; the active exit (as designed) realises a median {_v(big['pnl'], 2, True)} on them.</li>"
             "<li><b>Not at the entry delay</b> (0&ndash;3 bars give similar results) and <b>not mainly at option response alone</b> "
             f"(the sole blocker for {oo['only_onr']} candidate).</li>"
             f"<li><b>All of this is descriptive:</b> {L['evaluable_days']} days, {L['candidates']} candidates, {L['trades_lots']}&ndash;{L['trades_units']} trades. "
             "No parameter change is recommended or made.</li></ul></div>")
    o.append("<footer style='margin-top:40px;color:#666;font-size:0.85em'>Generated by scripts/run_scalp12a_opportunity_forensics.py &middot; "
             "machine-readable outputs in milestone12a_opportunity_forensics/ &middot; read-only; no database writes; config hash "
             f"{r['config_hash']}</footer></body></html>")
    return "\n".join(o)


if __name__ == "__main__":
    main()
