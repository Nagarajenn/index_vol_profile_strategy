"""12A impulse research gate -- READ-ONLY research (no strategy implemented).

Answers seven questions about detecting short BUY-only option scalps from
synchronized 5-second futures-mid + option data. Nothing in scalp_12a/, the
shadow recorder, HR capture, 11D or any DB table is changed.

Causality: thresholds for day D come from HR days strictly before D (futures from
all prior days, options from prior NON-expiry days); every label used for a
decision is computed from bars <= the decision bar; outcomes (MFE/MAE/P&L) are
measured after the realistic entry only. No parameter is selected on 09-17/09-18.

Output: milestone12a_impulse_research_gate.html + milestone12a_impulse_research/*.
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

import run_scalp12a_nextgen_research as ng  # noqa: E402  (audited helpers: dist, mv, opt_ret, simulate ...)
from scalp_12a import db  # noqa: E402
from scalp_12a import taxonomy as T  # noqa: E402
from scalp_12a.config import DEFAULT_CONFIG  # noqa: E402
from scalp_12a.engine import evaluate_day  # noqa: E402
from scalp_12a.thresholds import build_thresholds, percentile  # noqa: E402

EXPECTED_HASH = "994667c6d552111e"
OUT = ROOT / "milestone12a_impulse_research"
REPORT = ROOT / "milestone12a_impulse_research_gate.html"
W = 12
CHECK_T = (10, 15, 20, 25, 30, 45, 60)
med, pct, q, mean = ng.med, ng.pct, ng.q, ng.mean


# ------------------------------------------------------------------ distributions (extends ng.dist)
def extra_dist(opt_sessions):
    acc = {k: [] for k in ("syn10", "o15", "o30", "oacc5", "oacc10", "vacc")}
    for s in opt_sessions:
        for i in range(len(s)):
            c10, p10 = ng.opt_ret(s, ("CE", 0), i, 2), ng.opt_ret(s, ("PE", 0), i, 2)
            if c10 is not None and p10 is not None:
                acc["syn10"].append(abs(c10 - p10))
            for key in (("CE", 0), ("PE", 0)):
                for k, lag in (("o15", 3), ("o30", 6)):
                    v = ng.opt_ret(s, key, i, lag)
                    if v is not None:
                        acc[k].append(abs(v))
                a, b = ng.opt_ret(s, key, i, 1), ng.opt_ret(s, key, i - 1, 1)
                if a is not None and b is not None:
                    acc["oacc5"].append(abs(a - b))
                a, b = ng.opt_ret(s, key, i, 2), ng.opt_ret(s, key, i - 2, 2)
                if a is not None and b is not None:
                    acc["oacc10"].append(abs(a - b))
                v = [s.quote(key, k).volume_delta for k in (i, i - 1) if s.quote(key, k) and s.quote(key, k).volume_delta is not None]
                if len(v) == 2 and v[1] > 0:
                    acc["vacc"].append(v[0] / v[1])
    return {k: {p: (percentile(sorted(v), p) if v else None) for p in (50, 75, 90, 95)} for k, v in acc.items()}


# ------------------------------------------------------------------ impulse detector (records EVERY impulse)
def impulses(s, P, X, variant):
    """variant '10s': futures-mid |r10| >= p90 OR |CE-PE 10 s| >= p90.
       variant '5s' : futures-mid |d1|  >= p95 OR |CE-PE 5 s|  >= p95 (earlier, noisier).
    60 s cooldown per symbol+direction. Direction from the futures when it triggered, else the option."""
    out, last = [], {1: -10**9, -1: -10**9}
    for i in range(W + 1, len(s)):
        if variant == "10s":
            f, fthr = ng.mv(s, i, 2), P["r10"][90]
            c, p = ng.opt_ret(s, ("CE", 0), i, 2), ng.opt_ret(s, ("PE", 0), i, 2)
            othr = X["syn10"][90]
        else:
            f, fthr = ng.mv(s, i, 1), P["d1"][95]
            c, p = ng.opt_ret(s, ("CE", 0), i, 1), ng.opt_ret(s, ("PE", 0), i, 1)
            othr = P["syn5"][95]
        syn = (c - p) if (c is not None and p is not None) else None
        ft = f is not None and fthr is not None and abs(f) >= fthr and abs(f) > 0
        ot = syn is not None and othr is not None and abs(syn) >= othr
        if not (ft or ot):
            continue
        d = (1 if f > 0 else -1) if ft else (1 if syn > 0 else -1)
        if i - last[d] < 12:
            continue
        last[d] = i
        out.append(dict(i=i, d=d, by="FUTURES" if ft and not ot else ("OPTION" if ot and not ft else "BOTH"),
                        conflict=bool(ft and ot and (f > 0) != (syn > 0))))
    return out


def lead_lag(s, i, d, P):
    """Causal lead/lag class at bar i (only bars <= i)."""
    lo = max(1, i - W)
    key = ng.leg_for(d)
    fav = lambda k: (ng.fut(s, k) - ng.fut(s, lo)) * d if ng.fut(s, k) is not None and ng.fut(s, lo) is not None else 1e18
    on_f = min(range(lo, i + 1), key=fav)
    mids = [k for k in range(lo, i + 1) if ng.mid(s, key, k)]
    on_o = min(mids, key=lambda k: ng.mid(s, key, k)) if mids else None
    rf = next((k for k in range(on_f + 1, i + 1) if (ng.mv(s, k, 1) or 0) * d >= P["d1"][75] and (ng.mv(s, k, 1) or 0) != 0), None)
    ro = next((k for k in range(on_o + 1, i + 1) if (ng.opt_ret(s, key, k, 1) or 0) >= P["o5"][75]), None) if on_o is not None else None
    if rf is not None and ro is not None:
        lag = ro - rf
        cls = "SYNCHRONIZED" if abs(lag) <= 2 else ("OPTION_LEAD" if lag < 0 else "UNDERLYING_LEAD")
    elif ro is not None:
        cls = "FALSE_OPTION_MOVE"
    elif rf is not None:
        cls = "OPTION_RESPONSE_LAG"
    else:
        cls = "NO_CLEAR_ONSET"
    fade = False
    if on_o is not None and ro is not None:
        peak = max(ng.mid(s, key, k) for k in mids if k >= on_o)
        base, now = ng.mid(s, key, on_o), ng.mid(s, key, i)
        fade = peak > base and (peak - now) >= 0.5 * (peak - base)
    return dict(cls=cls, fade=fade, onset_f=on_f, onset_o=on_o, resp_f=rf, resp_o=ro,
                lag_bars=(rf - ro) if (rf is not None and ro is not None) else None)


def checks(s, c, i, d, P, X, cfg, onset_f):
    """Approval checks evaluated at bar c (>= trigger bar i). Same v2 definitions as the previous
    research iteration (not re-tuned)."""
    r = []
    t = (s.times[c] + timedelta(seconds=5)).time()
    if ng.mode_of(t) != "MODE_A":
        r.append("WINDOW")
    if s.is_expiry_day and t >= time.fromisoformat(cfg.expiry_transition_zone_start):
        r.append("EXPIRY_ZONE")
    if (i - onset_f) > 6:
        r.append("NOT_EARLY")
    syn = (ng.opt_ret(s, ("CE", 0), c, 2) or 0) - (ng.opt_ret(s, ("PE", 0), c, 2) or 0)
    if syn * d <= 0 or (ng.mv(s, c, 2) or 0) * d <= 0:
        r.append("NO_DIRECTIONAL_AGREEMENT")
    o10 = ng.opt_ret(s, ng.leg_for(d), c, 2)
    if o10 is None or o10 < P["o10"][75]:
        r.append("OPTION_NOT_RESPONDING")
    qq = s.quote(ng.leg_for(d), c)
    vol = sum((s.quote(ng.leg_for(d), k).volume_delta or 0) for k in range(c - 2, c + 1) if s.quote(ng.leg_for(d), k))
    if qq is None or not qq.valid or (qq.spread_pct or 99) > cfg.max_spread_pct or (qq.quote_age_s or 0) > cfg.max_quote_age_s or vol <= 0:
        r.append("LIQUIDITY")
    r300 = ng.mv(s, c, 60)
    if r300 is not None and r300 * d > 0 and abs(r300) >= P["r300"][90]:
        r.append("EXTENDED")
    return r


def path_stats(s, key, e, d):
    """BID path (percent of entry ASK) and futures-mid favourable path for 120 s after entry."""
    qe = s.quote(key, e) if e < len(s) else None
    if qe is None or not qe.valid:
        return None
    ask, f0 = qe.ask, ng.fut(s, e)
    p = []
    for k in range(e + 1, min(len(s), e + 25)):
        qk = s.quote(key, k)
        if qk and qk.valid:
            p.append(((k - e) * 5, (qk.bid - ask) / ask * 100.0, ((ng.fut(s, k) or f0) - f0) * d if f0 is not None else 0.0,
                      (qk.mid - s.quote(key, k - 1).mid) / s.quote(key, k - 1).mid * 100.0 if s.quote(key, k - 1) and s.quote(key, k - 1).mid else 0.0))
    return p


def first_t(p, lvl, horizon=120):
    return next((t for t, v, _, _ in p if t <= horizon and v >= lvl), None)


def rule_exit(p, rule):
    """Research exit rules on the same BID path (parameters fixed a priori, not optimised)."""
    peak, down = -1e9, 0
    prev = None
    for t, v, fv, om in p:
        peak = max(peak, v)
        down = down + 1 if (prev is not None and v < prev) else 0
        prev = v
        if rule == "FIXED_30" and t >= 30:
            return v, t
        if rule == "FIXED_60" and t >= 60:
            return v, t
        if rule == "NO_PROGRESS_20" and ((t == 20 and v <= 0) or t >= 60):
            return v, t
        if rule == "NO_PROGRESS_30" and ((t == 30 and v <= 0) or t >= 60):
            return v, t
        if rule == "ADVERSE_1PCT" and (v <= -1.0 or t >= 60):
            return v, t
        if rule == "GIVEBACK_HALF" and ((peak >= 1.0 and v <= peak / 2) or t >= 60):
            return v, t
        if rule == "MOMENTUM_FAIL_2BARS" and ((t >= 10 and down >= 2) or t >= 60):
            return v, t
        if rule == "DIVERGENCE" and ((t >= 10 and fv > 0 and v < 0) or t >= 60):
            return v, t
        if rule == "COMBINED" and ((t == 20 and v <= 0) or v <= -1.0 or (peak >= 1.0 and v <= peak / 2) or t >= 60):
            return v, t
    return (p[-1][1], p[-1][0]) if p else (None, None)


RULES = ["FIXED_30", "FIXED_60", "NO_PROGRESS_20", "NO_PROGRESS_30", "ADVERSE_1PCT", "GIVEBACK_HALF", "MOMENTUM_FAIL_2BARS",
         "DIVERGENCE", "COMBINED"]


def remaining(s, onset, e, d):
    """Share of the futures-mid favourable move still ahead at entry e (outcome measurement)."""
    f_on, f_e = ng.fut(s, onset), ng.fut(s, e)
    if f_on is None or f_e is None:
        return None
    done = (f_e - f_on) * d
    ahead = max([((ng.fut(s, k) or f_e) - f_e) * d for k in range(e + 1, min(len(s), e + 61))] + [0.0])
    tot = max(done, 0) + ahead
    return (ahead / tot) if tot > 0 else None


def option_consumed(s, key, on_o, e):
    if on_o is None or not ng.mid(s, key, on_o) or not ng.mid(s, key, e):
        return None
    base, now = ng.mid(s, key, on_o), ng.mid(s, key, e)
    ahead = max([(ng.mid(s, key, k) or now) - now for k in range(e + 1, min(len(s), e + 61))] + [0.0])
    done = now - base
    tot = max(done, 0) + ahead
    return (max(done, 0) / tot) if tot > 0 else None


# ------------------------------------------------------------------ main
def main():
    cfg = DEFAULT_CONFIG
    assert cfg.config_hash() == EXPECTED_HASH
    OUT.mkdir(exist_ok=True)
    with db.connect(300000) as conn:
        hr = [r for r in db.hr_session_ids(conn) if r[2] != "RUNNING"]
        days = [r[0] for r in hr]
        sid = {r[0]: r[1] for r in hr}
        sessions = {d: {s: db.load_session(conn, sid[d], d, s) for s in cfg.symbols} for d in days}
        mids = {}
        for d in days:
            for sym, ts, b, a in conn.execute("SELECT symbol, bar_ts, futures_bid, futures_ask FROM hr_option_transition_state WHERE session_id=%s",
                                              (sid[d],)).fetchall():
                if b and a:
                    mids[(d, sym, ts)] = (float(b) + float(a)) / 2
        ref = reference_quality(conn, days, sid)
        trace = tick_trace(conn, sid)
    smid = {d: {sym: replace(sessions[d][sym], fut=[mids.get((d, sym, t)) for t in sessions[d][sym].times],
                             fut_updated=[mids.get((d, sym, t)) is not None for t in sessions[d][sym].times]) for sym in cfg.symbols} for d in days}
    P, X, thr12 = {}, {}, {}
    for n, d in enumerate(days):
        for sym in cfg.symbols:
            pm = [smid[p][sym] for p in days[:n]]
            po = [x for x in pm if not x.is_expiry_day] or pm
            thr12[(d, sym)] = build_thresholds([sessions[p][sym] for p in days[:n]], cfg)
            if len(pm) >= 2:
                P[(d, sym)], X[(d, sym)] = ng.dist(pm, po), extra_dist(po)
    evaluable = [d for d in days if all((d, s) in P for s in cfg.symbols)]

    # --- impulses (both variants) + current 12A events
    recs = []
    for d in evaluable:
        for sym in cfg.symbols:
            s, Pd, Xd = smid[d][sym], P[(d, sym)], X[(d, sym)]
            for variant in ("10s", "5s"):
                for imp in impulses(s, Pd, Xd, variant):
                    recs.append(build_rec(s, d, sym, imp["i"], imp["d"], variant, Pd, Xd, cfg, imp))
        res = evaluate_day(list(sessions[d].values()), {s: thr12[(d, s)] for s in cfg.symbols}, cfg)
        for sym in cfg.symbols:
            for c in res[sym].candidates:
                if c.event.strength == T.STRONG:
                    recs.append(build_rec(smid[d][sym], d, sym, c.bar_index, c.event.direction, "CURRENT_12A", P[(d, sym)], X[(d, sym)], cfg,
                                          dict(by="FUTURES_LAST_TRADE", conflict=False)))
    # random baseline
    import random
    rng = random.Random(12)
    for d in evaluable:
        for sym in cfg.symbols:
            s = smid[d][sym]
            elig = [i for i, t in enumerate(s.times) if ng.mode_of((t + timedelta(seconds=5)).time()) == "MODE_A" and i > W and i + 30 < len(s)]
            for i in rng.sample(elig, min(60, len(elig))):
                recs.append(build_rec(s, d, sym, i, rng.choice([1, -1]), "RANDOM", P[(d, sym)], X[(d, sym)], cfg, dict(by="RANDOM", conflict=False)))

    R = analyse(recs, cfg, days, evaluable, smid, ref, trace)
    (OUT / "impulse_research.json").write_text(json.dumps(R, default=str, indent=1), encoding="utf-8")
    flat = [{k: v for k, v in r.items() if k not in ("path1", "path2", "dims")} | {f"dim_{k}": v for k, v in r["dims"].items()} for r in recs]
    with open(OUT / "impulses.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(flat[0].keys()))
        w.writeheader()
        w.writerows(flat)
    from impulse_report import render
    REPORT.write_text(render(R), encoding="utf-8")
    print(json.dumps(R["headline"], default=str, indent=1))


def build_rec(s, d, sym, i, dirn, variant, P, X, cfg, meta):
    key = ng.leg_for(dirn)
    ll = lead_lag(s, i, dirn, P)
    conf_bar, why = None, []
    for c in range(i, min(i + 3, len(s))):          # confirmation allowed within 10 s of detection
        why = checks(s, c, i, dirn, P, X, cfg, ll["onset_f"])
        if not why:
            conf_bar = c
            break
    base_bar = conf_bar if conf_bar is not None else i
    rec = dict(date=str(d), symbol=sym, variant=variant, i=i, dir=dirn, by=meta.get("by"), conflict=meta.get("conflict"),
               time=(s.times[i] + timedelta(seconds=5)).strftime("%H:%M:%S"),
               window=ng.window_of((s.times[i] + timedelta(seconds=5)).time()), mode=ng.mode_of((s.times[i] + timedelta(seconds=5)).time()),
               expiry=s.is_expiry_day, cls=ll["cls"], fade=ll["fade"], lag_bars=ll["lag_bars"],
               onset_age_s=(i - ll["onset_f"]) * 5, approved=conf_bar is not None, reasons=why,
               confirm_delay_s=((conf_bar - i) * 5) if conf_bar is not None else None)
    for tag, off in (("1", 1), ("2", 2)):
        e = base_bar + off
        sim = ng.simulate(s, base_bar, dirn, key, max(0, i - 3), cfg, off)
        p = path_stats(s, key, e, dirn)
        rec[f"path{tag}"] = p
        rec[f"pnl{tag}"] = sim["pnl"] if sim else None
        rec[f"mfe{tag}"] = sim["mfe"] if sim else None
        rec[f"mae{tag}"] = sim["mae"] if sim else None
        rec[f"tmae{tag}"] = sim["t_mae"] if sim else None
        rec[f"spread{tag}"] = sim["spread_in"] if sim else None
        rec[f"t05_{tag}"] = first_t(p, 0.5) if p else None
        rec[f"t1_{tag}"] = first_t(p, 1.0) if p else None
        rec[f"t2_{tag}"] = first_t(p, 2.0) if p else None
        rec[f"good{tag}"] = bool(p) and any(t <= 60 and v >= 1.0 for t, v, _, _ in p)
        rec[f"hit1first{tag}"] = hit_first(p)
        rec[f"remain{tag}"] = remaining(s, ll["onset_f"], e, dirn) if e < len(s) else None
        rec[f"optcons{tag}"] = option_consumed(s, key, ll["onset_o"], e) if e < len(s) else None
        rec[f"delay_to_entry{tag}"] = (e - ll["onset_f"]) * 5
    rec["dims"] = dims(s, i, dirn, P, ll)
    return rec


def hit_first(p):
    """+1% reached before -1% within 60 s (scalp-relevant precision label, outcome only)."""
    if not p:
        return None
    for t, v, _, _ in p:
        if t > 60:
            break
        if v >= 1.0:
            return True
        if v <= -1.0:
            return False
    return False


def dims(s, i, d, P, ll):
    key = ng.leg_for(d)
    d1, d1p = ng.mv(s, i, 1), ng.mv(s, i - 1, 1)
    o5, o5p = ng.opt_ret(s, key, i, 1), ng.opt_ret(s, key, i - 1, 1)
    syn = (ng.opt_ret(s, ("CE", 0), i, 2) or 0) - (ng.opt_ret(s, ("PE", 0), i, 2) or 0)
    qq = s.quote(key, i)
    lo = ll["onset_f"]
    peak = max(((ng.fut(s, k) or 0) - (ng.fut(s, lo) or 0)) * d for k in range(lo, i + 1))
    used = ((ng.fut(s, i) or 0) - (ng.fut(s, lo) or 0)) * d
    t = s.times[i] + timedelta(seconds=5)
    return {"A_futures_strength": ng.prank(P, "r10", abs(ng.mv(s, i, 2) or 0)),
            "B_futures_acceleration": ng.prank(P, "acc", abs((d1 or 0) - (d1p or 0))) if (d1 or 0) * d > 0 else 0.0,
            "C_option_acceleration": (o5 or 0) - (o5p or 0),
            "D_direction_agreement": 1.0 if syn * d > 0 else 0.0,
            "E_lead_lag_bars(+ = option first)": ll["lag_bars"],
            "F_liquidity(-spread)": -(qq.spread_pct or 0) if qq else None,
            "G_earlyness(-onset age s)": -(i - lo) * 5,
            "H_reversal_risk(-retrace)": -(peak - used),
            "I_time_remaining_s": (15 * 3600 + 15 * 60) - (t.hour * 3600 + t.minute * 60 + t.second)}


# ------------------------------------------------------------------ reference quality (Part 1) and tick trace (Part 2)
def reference_quality(conn, days, sid):
    out = []
    for d in days:
        rows = conn.execute("""SELECT h.symbol, avg(h.update_count), avg(h.trade_count), 100.0*avg((h.trade_count=0)::int)
                               FROM hr_ohlc_5s h WHERE h.session_id=%s AND h.instrument_type='FUTIDX' GROUP BY 1""", (sid[d],)).fetchall()
        for sym, upd, trd, notrade in rows:
            mid_rows = conn.execute("""SELECT bar_ts, (futures_bid+futures_ask)/2, futures_status, extract(epoch from created_at-bar_ts)
                                       FROM hr_option_transition_state WHERE session_id=%s AND symbol=%s ORDER BY bar_ts""", (sid[d], sym)).fetchall()
            lt = conn.execute("""SELECT close FROM hr_ohlc_5s WHERE session_id=%s AND symbol=%s AND instrument_type='FUTIDX' ORDER BY bar_ts""",
                              (sid[d], sym)).fetchall()
            def runs(vals):
                longest, cur, n30 = 0, 0, 0
                for a, b in zip(vals, vals[1:]):
                    if a == b:
                        cur += 1
                    else:
                        if cur >= 6:
                            n30 += 1
                        cur = 0
                    longest = max(longest, cur)
                return longest * 5, n30 + (1 if cur >= 6 else 0)
            mv_ = [r[1] for r in mid_rows]
            lr, ln = runs([r[0] for r in lt])
            mr, mn = runs(mv_)
            ltt = conn.execute("""SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY extract(epoch from receive_ts-exchange_ts)),
                                         percentile_cont(0.95) WITHIN GROUP (ORDER BY extract(epoch from receive_ts-exchange_ts))
                                  FROM hr_raw_ticks WHERE session_id=%s AND symbol=%s AND instrument_type='FUTIDX' AND exchange_ts IS NOT NULL""",
                               (sid[d], sym)).fetchone()
            out.append(dict(date=str(d), symbol=sym, bars=len(mid_rows), quote_updates_per_bar=round(float(upd), 1),
                            trades_per_bar=round(float(trd), 2), no_trade_bar_pct=round(float(notrade), 1),
                            mid_moved_pct=round(100.0 * sum(1 for a, b in zip(mv_, mv_[1:]) if a != b) / max(1, len(mv_) - 1), 1),
                            last_trade_longest_stale_s=lr, last_trade_stale_runs_30s=ln, mid_longest_stale_s=mr, mid_stale_runs_30s=mn,
                            frozen_status_bars=sum(1 for r in mid_rows if r[2] == "FROZEN"),
                            write_latency_mean_s=round(st.mean(float(r[3]) for r in mid_rows), 2),
                            write_latency_max_s=round(max(float(r[3]) for r in mid_rows), 2),
                            ltt_lag_median_s=round(float(ltt[0]), 2) if ltt and ltt[0] is not None else None,
                            ltt_lag_p95_s=round(float(ltt[1]), 2) if ltt and ltt[1] is not None else None))
    return out


def tick_trace(conn, sid):
    """Raw ticks -> 5 s bars for the 09-17 NIFTY CE 23300 and futures around 15:00:20-15:01:10."""
    d = next(x for x in sid if str(x) == "2026-09-17")
    rows = []
    for itype, extra in (("OPTIDX", "AND strike=23300 AND option_type='CE'"), ("FUTIDX", "")):
        rows += conn.execute(f"""SELECT instrument_type, to_timestamp(floor(extract(epoch from receive_ts) / 5) * 5)::time AS bucket,
                                        count(*), min(receive_ts)::time, max(receive_ts)::time, min(exchange_ts)::time, max(exchange_ts)::time,
                                        min(bid_price_1), max(ask_price_1), min(ltp), max(ltp)
                                 FROM hr_raw_ticks WHERE session_id=%s AND symbol='NIFTY' AND instrument_type=%s {extra}
                                   AND receive_ts::time BETWEEN '15:00:15' AND '15:01:15' GROUP BY 1,2 ORDER BY 2,1""",
                             (sid[d], itype)).fetchall()
    bars = conn.execute("""SELECT o.bar_ts::time, o.bid, o.ask, o.mid, o.update_count, extract(epoch from o.created_at-o.bar_ts)
                           FROM hr_option_5s o WHERE o.session_id=%s AND o.symbol='NIFTY' AND o.strike=23300 AND o.option_type='CE'
                             AND o.bar_ts::time BETWEEN '15:00:15' AND '15:01:10' ORDER BY 1""", (sid[d],)).fetchall()
    return dict(ticks=[[str(x) for x in r] for r in rows], bars=[[str(x) for x in r] for r in bars])


# ------------------------------------------------------------------ analysis
def grp_stats(rs, tag="2"):
    n = len(rs)
    return dict(n=n, mfe=med([r[f"mfe{tag}"] for r in rs]), mae=med([r[f"mae{tag}"] for r in rs]), pnl=med([r[f"pnl{tag}"] for r in rs]),
                pnl_mean=mean([r[f"pnl{tag}"] for r in rs]), t05=med([r[f"t05_{tag}"] for r in rs], 0), t1=med([r[f"t1_{tag}"] for r in rs], 0),
                t2=med([r[f"t2_{tag}"] for r in rs], 0), tmae=med([r[f"tmae{tag}"] for r in rs], 0),
                profitable=pct(sum(1 for r in rs if (r[f"pnl{tag}"] or 0) > 0), n), spread=med([r[f"spread{tag}"] for r in rs]),
                remain=med([r[f"remain{tag}"] for r in rs]), optcons=med([r[f"optcons{tag}"] for r in rs]),
                hit1first=pct(sum(1 for r in rs if r[f"hit1first{tag}"]), sum(1 for r in rs if r[f"hit1first{tag}"] is not None)),
                reach_t05=pct(sum(1 for r in rs if r[f"t05_{tag}"] is not None), n))


def analyse(recs, cfg, days, evaluable, smid, ref, trace):
    R = dict(days=[str(d) for d in days], evaluable=[str(d) for d in evaluable], reference=ref, trace=trace)
    byv = lambda v, extra=lambda r: True: [r for r in recs if r["variant"] == v and extra(r)]
    modeA = lambda r: r["mode"] == "MODE_A"
    R["counts"] = {v: dict(all=len(byv(v)), modeA=len(byv(v, modeA)), approved=len(byv(v, lambda r: r["approved"])))
                   for v in ("10s", "5s", "CURRENT_12A", "RANDOM")}
    # Q1 / Part 4: lead-lag classes (10 s impulses, Mode A and all)
    R["classes"] = {}
    for scope, f in (("Mode A", modeA), ("all windows", lambda r: True)):
        for sym in cfg.symbols + ("both",):
            pool = byv("10s", lambda r, f=f, sym=sym: f(r) and (sym == "both" or r["symbol"] == sym))
            R["classes"][f"{scope} | {sym}"] = {c: grp_stats([r for r in pool if r["cls"] == c]) for c in
                                                ("OPTION_LEAD", "UNDERLYING_LEAD", "SYNCHRONIZED", "FALSE_OPTION_MOVE", "OPTION_RESPONSE_LAG", "NO_CLEAR_ONSET")}
            R["classes"][f"{scope} | {sym}"]["OPTION_FADE (flag)"] = grp_stats([r for r in pool if r["fade"]])
    R["classes_by_day"] = {d: {c: grp_stats([r for r in byv("10s", modeA) if r["date"] == d and r["cls"] == c])
                               for c in ("OPTION_LEAD", "UNDERLYING_LEAD", "SYNCHRONIZED", "FALSE_OPTION_MOVE", "OPTION_RESPONSE_LAG")} for d in R["evaluable"]}
    # Q2/Q3/Q4: detector variants, Mode A, non-expiry and expiry separately
    R["variants"] = {}
    for v in ("CURRENT_12A", "10s", "5s", "RANDOM"):
        for ex in (False, True):
            for sym in cfg.symbols:
                pool = byv(v, lambda r, ex=ex, sym=sym: modeA(r) and r["expiry"] == ex and r["symbol"] == sym)
                R["variants"][f"{v} | {'EXPIRY' if ex else 'normal'} | {sym}"] = dict(grp_stats(pool), onset_age=med([r["onset_age_s"] for r in pool], 0))
    # Part 5: approval + delays (Mode A approved, 10 s and 5 s)
    R["approval"] = {}
    for v in ("10s", "5s"):
        ap = byv(v, lambda r: r["approved"])
        rej = {}
        for r in byv(v, modeA):
            for x in r["reasons"]:
                rej[x] = rej.get(x, 0) + 1
        R["approval"][v] = dict(n_modeA=len(byv(v, modeA)), approved=len(ap), rejections=rej,
                                onset_to_detect=med([r["onset_age_s"] for r in ap], 0), confirm_delay=med([r["confirm_delay_s"] for r in ap], 0),
                                onset_to_entry1=med([r["delay_to_entry1"] for r in ap], 0), onset_to_entry2=med([r["delay_to_entry2"] for r in ap], 0),
                                fut_remaining1=med([r["remain1"] for r in ap]), fut_remaining2=med([r["remain2"] for r in ap]),
                                opt_consumed1=med([r["optcons1"] for r in ap]), opt_consumed2=med([r["optcons2"] for r in ap]),
                                by_symbol={s: len([r for r in ap if r["symbol"] == s]) for s in cfg.symbols},
                                by_day={d: len([r for r in ap if r["date"] == d]) for d in R["evaluable"]})
    # Part 6: i+1 vs i+2
    R["entry"] = {}
    for v in ("CURRENT_12A", "10s", "5s", "RANDOM"):
        for grp, f in (("all Mode A", modeA), ("approved", lambda r: r["approved"])):
            if v in ("CURRENT_12A", "RANDOM") and grp == "approved":
                continue
            pool = byv(v, f)
            R["entry"][f"{v} | {grp}"] = {"i+1 (streaming)": grp_stats(pool, "1"), "i+2 (5 s polling)": grp_stats(pool, "2")}
    # Part 7: dimensions -- per-day Spearman + out-of-sample tercile test (cuts from day 1 applied to day 2)
    pool = byv("10s", modeA)
    d1, d2 = R["evaluable"][0], R["evaluable"][-1]
    R["dims"] = {}
    for k in pool[0]["dims"] if pool else []:
        a = [r for r in pool if r["date"] == d1 and r["dims"][k] is not None and r["pnl2"] is not None]
        b = [r for r in pool if r["date"] == d2 and r["dims"][k] is not None and r["pnl2"] is not None]
        rho1 = ng.spearman([r["dims"][k] for r in a], [r["pnl2"] for r in a])
        rho2 = ng.spearman([r["dims"][k] for r in b], [r["pnl2"] for r in b])
        oos = None
        if len(a) >= 9 and len(b) >= 9:
            vals = sorted(r["dims"][k] for r in a)
            lo_cut, hi_cut = percentile(vals, 33.3), percentile(vals, 66.7)
            top = [r["pnl2"] for r in b if r["dims"][k] >= hi_cut]
            bot = [r["pnl2"] for r in b if r["dims"][k] <= lo_cut]
            if top and bot and hi_cut != lo_cut:
                oos = dict(top_mean=round(st.mean(top), 3), bottom_mean=round(st.mean(bot), 3), n_top=len(top), n_bottom=len(bot),
                           top_hit1=pct(sum(1 for r in b if r["dims"][k] >= hi_cut and r["hit1first2"]), len(top)),
                           bottom_hit1=pct(sum(1 for r in b if r["dims"][k] <= lo_cut and r["hit1first2"]), len(bot)))
        stable = rho1[0] is not None and rho2[0] is not None and (rho1[0] > 0) == (rho2[0] > 0)
        R["dims"][k] = dict(rho_day1=rho1, rho_day2=rho2, stable=stable, oos=oos,
                            oos_consistent=bool(oos and stable and ((oos["top_mean"] > oos["bottom_mean"]) == (rho1[0] > 0))))
    # Part 8: exits on 10 s impulses (Mode A, normal days) with i+2 entry
    ex_pool = [r for r in byv("10s", lambda r: modeA(r) and not r["expiry"]) if r["path2"]]
    good = [r for r in ex_pool if any(t <= 60 and v >= 1.0 for t, v, _, _ in r["path2"])]
    bad = [r for r in ex_pool if not any(t <= 60 and v >= 0.5 for t, v, _, _ in r["path2"])]
    sep = {}
    for t in CHECK_T:
        at = lambda r: next((v for tt, v, _, _ in r["path2"] if tt == t), None)
        g = [at(r) for r in good if at(r) is not None]
        b = [at(r) for r in bad if at(r) is not None]
        sep[t] = dict(good_underwater=pct(sum(1 for v in g if v < 0), len(g)), bad_underwater=pct(sum(1 for v in b if v < 0), len(b)),
                      good_le_m05=pct(sum(1 for v in g if v <= -0.5), len(g)), bad_le_m05=pct(sum(1 for v in b if v <= -0.5), len(b)),
                      good_med=med(g), bad_med=med(b), n_good=len(g), n_bad=len(b))
    rules = {}
    for rl in RULES:
        res = [rule_exit(r["path2"], rl) for r in ex_pool]
        pn = [x[0] for x in res if x[0] is not None]
        hold = [x[1] for x in res if x[1] is not None]
        peaks = [max(v for _, v, _, _ in r["path2"][: max(1, (x[1] or 5) // 5)]) - (x[0] or 0) for r, x in zip(ex_pool, res) if x[0] is not None]
        byd = {d: mean([rule_exit(r["path2"], rl)[0] for r in ex_pool if r["date"] == d]) for d in R["evaluable"]}
        rules[rl] = dict(n=len(pn), mean=mean(pn), median=med(pn), profitable=pct(sum(1 for v in pn if v > 0), len(pn)), hold=med(hold, 0),
                         giveback=med(peaks), by_day=byd)
    rules["CURRENT_12A_EXIT_ENGINE"] = dict(n=len(ex_pool), mean=mean([r["pnl2"] for r in ex_pool]), median=med([r["pnl2"] for r in ex_pool]),
                                            profitable=pct(sum(1 for r in ex_pool if (r["pnl2"] or 0) > 0), len(ex_pool)), hold=None, giveback=None,
                                            by_day={d: mean([r["pnl2"] for r in ex_pool if r["date"] == d]) for d in R["evaluable"]})
    R["exits"] = dict(pool=len(ex_pool), good=len(good), bad=len(bad), separation=sep, rules=rules,
                      usable=dict(t05=med([first_t(r["path2"], 0.5, 60) for r in good], 0), t1=med([first_t(r["path2"], 1.0, 60) for r in good], 0),
                                  t15=med([first_t(r["path2"], 1.5, 60) for r in good], 0), t2=med([first_t(r["path2"], 2.0, 60) for r in good], 0),
                                  reach2=pct(sum(1 for r in good if first_t(r["path2"], 2.0, 60) is not None), len(good))))
    # Expiry separately (10 s impulses, Mode A)
    R["expiry"] = {("EXPIRY" if ex else "normal"): grp_stats(byv("10s", lambda r, ex=ex: modeA(r) and r["expiry"] == ex)) for ex in (False, True)}
    # headline numbers for the answers
    ol = R["classes"]["Mode A | both"]
    R["headline"] = dict(counts=R["counts"], option_lead=ol["OPTION_LEAD"], underlying_lead=ol["UNDERLYING_LEAD"], sync=ol["SYNCHRONIZED"],
                         false_move=ol["FALSE_OPTION_MOVE"], lag=ol["OPTION_RESPONSE_LAG"],
                         approval=R["approval"], exits_sep=sep, random=grp_stats(byv("RANDOM", modeA)),
                         imp10=grp_stats(byv("10s", modeA)), imp5=grp_stats(byv("5s", modeA)), cur=grp_stats(byv("CURRENT_12A", modeA)))
    return R


if __name__ == "__main__":
    main()
