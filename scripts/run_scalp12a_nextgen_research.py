"""12A next-generation scalp architecture -- research only (Parts 2-17).

READ-ONLY. Nothing in scalp_12a/, the shadow recorder, 11D or any DB table is
changed. The CURRENT 12A engine is replayed unchanged for comparison; the
12A-EARLY detector below exists only in this script as a research prototype.

Causality rules used everywhere:
* every threshold for day D is a percentile of the same symbol's data on HR days
  strictly before D (min 2 prior days, the same rule 12A uses);
* a trigger at bar i reads bars <= i only; entries use the ASK of a LATER bar;
* anything read after the entry bar is outcome measurement, never a decision input.

Entry-timing model (Part 5): a bar's values are known at bar close; HR lands them
in the DB ~3.3 s later (median). The earliest quote formed AFTER detection is
therefore the close of bar i+1 ("0 s": needs a streaming consumer), then i+2
("5 s": what the current 5-second DB poller can guarantee -- 12A today),
i+3 ("10 s") and i+4 ("15 s").

Outputs: milestone12a_next_generation_scalp_research.html and
milestone12a_nextgen_research/{nextgen.json, early_triggers.csv, current_candidates.csv}.
"""

import csv
import json
import math
import random
import statistics as st
import sys
from dataclasses import replace
from datetime import time, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import run_scalp12a_5session_backtest as bt  # noqa: E402  (lot sizes, account, qclose)
from scalp_12a import db  # noqa: E402
from scalp_12a import taxonomy as T  # noqa: E402
from scalp_12a.config import DEFAULT_CONFIG  # noqa: E402
from scalp_12a.counterfactual import track  # noqa: E402
from scalp_12a.engine import evaluate_day  # noqa: E402
from scalp_12a.exits import OPEN, simulate_exit  # noqa: E402
from scalp_12a.models import Event, Selection  # noqa: E402
from scalp_12a.risk import plan_risk  # noqa: E402
from scalp_12a.thresholds import build_thresholds, percentile  # noqa: E402

EXPECTED_HASH = "994667c6d552111e"
OUT = ROOT / "milestone12a_nextgen_research"
REPORT = ROOT / "milestone12a_next_generation_scalp_research.html"
W = 12                                   # 60 s look-back for impulse onset
FAMILIES = ["A_EARLY_MOMENTUM", "B_ACCELERATION", "C_OPTION_LEADS", "D_UNDERLYING_LEADS", "E_BOTH_CONFIRM",
            "F_REVERSAL", "G_CONTINUATION"]
DELAYS = {"0s (i+1, streaming)": 1, "5s (i+2, current poller)": 2, "10s (i+3)": 3, "15s (i+4)": 4}
HOLDS = (15, 30, 45, 60, 90, 120)
MIN_PRIOR = 2


# ------------------------------------------------------------------ small helpers
def med(v, nd=3):
    v = [x for x in v if x is not None]
    return round(st.median(v), nd) if v else None


def mean(v, nd=3):
    v = [x for x in v if x is not None]
    return round(st.mean(v), nd) if v else None


def pct(n, d):
    return round(100.0 * n / d, 1) if d else None


def q(v, p):
    v = sorted(x for x in v if x is not None)
    return round(percentile(v, p), 3) if v else None


def spearman(xs, ys):
    pairs = [(x, y) for x, y in zip(xs, ys) if x is not None and y is not None]
    if len(pairs) < 5:
        return None, len(pairs)
    def ranks(v):
        order = sorted(range(len(v)), key=lambda k: v[k])
        r = [0.0] * len(v)
        i = 0
        while i < len(v):
            j = i
            while j + 1 < len(v) and v[order[j + 1]] == v[order[i]]:
                j += 1
            for k in range(i, j + 1):
                r[order[k]] = (i + j) / 2.0
            i = j + 1
        return r
    a, b = ranks([p[0] for p in pairs]), ranks([p[1] for p in pairs])
    ma, mb = st.mean(a), st.mean(b)
    num = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    den = math.sqrt(sum((x - ma) ** 2 for x in a) * sum((y - mb) ** 2 for y in b))
    return (round(num / den, 3) if den else None), len(pairs)


def fut(s, i):
    return s.fut_ffill(i) if 0 <= i < len(s) else None


def mv(s, i, lag):
    a, b = fut(s, i), fut(s, i - lag)
    return None if a is None or b is None else a - b


def mid(s, key, i):
    qq = s.quote(key, i) if 0 <= i < len(s) else None
    return qq.mid if qq and qq.mid else None


def opt_ret(s, key, i, lag):
    a, b = mid(s, key, i), mid(s, key, i - lag)
    return None if a is None or b is None or b == 0 else (a - b) / b * 100.0


def leg_for(d):
    return ("CE", 0) if d > 0 else ("PE", 0)


def mode_of(t):
    if t < time(15, 0):
        return "PRE"
    return "MODE_A" if t < time(15, 15) else "MODE_B"


def window_of(t):
    if t < time(15, 0):
        return "PRE 14:55-15:00"
    if t >= time(15, 15):
        return "MODE B 15:15-15:30"
    for edge, lbl in ((time(15, 3), "15:00-15:03"), (time(15, 6), "15:03-15:06"), (time(15, 9), "15:06-15:09"),
                      (time(15, 12), "15:09-15:12"), (time(15, 15), "15:12-15:15")):
        if t < edge:
            return lbl


# ------------------------------------------------------------------ causal distributions
def dist(fut_sessions, opt_sessions):
    """Percentile inputs from PRIOR days only (per symbol). Futures statistics use every prior
    day (futures-mid reference); option statistics use prior NON-expiry days when available,
    because expiry-day premium swings inflate the option tails (Part 13)."""
    acc = {k: [] for k in ("d1", "r10", "r15", "r30", "r60", "r300", "acc", "o5", "o10", "syn5", "spread")}
    for s in fut_sessions:
        for i in range(len(s)):
            for k, lag in (("d1", 1), ("r10", 2), ("r15", 3), ("r30", 6), ("r60", 12), ("r300", 60)):
                v = mv(s, i, lag)
                if v is not None:
                    acc[k].append(abs(v))
            a, b = mv(s, i, 1), mv(s, i - 1, 1)
            if a is not None and b is not None:
                acc["acc"].append(abs(a - b))
    for s in opt_sessions:
        for i in range(len(s)):
            ce5, pe5 = opt_ret(s, ("CE", 0), i, 1), opt_ret(s, ("PE", 0), i, 1)
            ce10, pe10 = opt_ret(s, ("CE", 0), i, 2), opt_ret(s, ("PE", 0), i, 2)
            for v in (ce5, pe5):
                if v is not None:
                    acc["o5"].append(abs(v))
            for v in (ce10, pe10):
                if v is not None:
                    acc["o10"].append(abs(v))
            if ce5 is not None and pe5 is not None:
                acc["syn5"].append(abs(ce5 - pe5))
            for key in (("CE", 0), ("PE", 0)):
                qq = s.quote(key, i)
                if qq and qq.spread_pct is not None:
                    acc["spread"].append(qq.spread_pct)
    P = {}
    for k, v in acc.items():
        v = sorted(v)
        P[k] = {p: (percentile(v, p) if v else None) for p in (50, 75, 90, 95)}
        P[k]["_sorted"] = v
    return P


def prank(P, key, v):
    """Percentile rank of v within the prior-day distribution (0-100)."""
    arr = P[key]["_sorted"]
    if v is None or not arr:
        return None
    lo, hi = 0, len(arr)
    while lo < hi:
        m = (lo + hi) // 2
        if arr[m] < v:
            lo = m + 1
        else:
            hi = m
    return round(100.0 * lo / len(arr), 1)


# ------------------------------------------------------------------ impulse anatomy (Parts 2/4)
def anatomy(s, i, d, key, P, entry_i):
    """Pre-detection anatomy of a directional impulse ending at detection bar i."""
    lo = max(1, i - W)
    fav_f = lambda k: (fut(s, k) - fut(s, lo)) * d if fut(s, k) is not None and fut(s, lo) is not None else None
    # futures onset = most adverse point in the look-back (start of the impulse)
    onset_f = min(range(lo, i + 1), key=lambda k: fav_f(k) if fav_f(k) is not None else 1e18)
    om = lambda k: mid(s, key, k)
    valid_o = [k for k in range(lo, i + 1) if om(k)]
    onset_o = min(valid_o, key=lambda k: om(k)) if valid_o else None
    pre_f = (fut(s, i) - fut(s, onset_f)) * d if fut(s, i) is not None and fut(s, onset_f) is not None else None
    pre_o = ((om(i) - om(onset_o)) / om(onset_o) * 100.0) if onset_o is not None and om(i) and om(onset_o) else None
    # first significant directional step after each onset
    thr_f, thr_o = P["d1"][75], P["o5"][75]
    resp_f = next((k for k in range(onset_f + 1, i + 1) if mv(s, k, 1) is not None and mv(s, k, 1) * d >= thr_f), None)
    resp_o = None
    if onset_o is not None:
        resp_o = next((k for k in range(onset_o + 1, i + 1) if (opt_ret(s, key, k, 1) or 0) >= thr_o), None)
    # after detection (outcome measurement only)
    horizon = min(len(s) - 1, i + 60)
    after_f = [(k, (fut(s, k) - fut(s, i)) * d) for k in range(i + 1, horizon + 1) if fut(s, k) is not None and fut(s, i) is not None]
    mfe_f = max([v for _, v in after_f] + [0.0]) if after_f else None
    t_peak_f = next((k - i for k, v in after_f if v == mfe_f), None) if after_f and mfe_f and mfe_f > 0 else None
    after_o = [(k, om(k)) for k in range(i + 1, horizon + 1) if om(k)]
    mfe_o = max([(m - om(i)) / om(i) * 100.0 for _, m in after_o] + [0.0]) if after_o and om(i) else None
    # option late response: first significant step after detection within 30 s
    late_o = next((k for k in range(i + 1, min(len(s), i + 7)) if (opt_ret(s, key, k, 1) or 0) >= thr_o), None)
    # fade: option peak before entry vs value at entry
    peak_o = max((om(k) for k in range(onset_o, min(entry_i, len(s) - 1) + 1) if om(k)), default=None) if onset_o is not None else None
    fade = None
    if peak_o and onset_o is not None and om(onset_o) and om(entry_i) and peak_o > om(onset_o):
        fade = (peak_o - om(entry_i)) / (peak_o - om(onset_o))
    # futures + option acceleration strictly before the detection bar
    acc_f = any(mv(s, k, 1) is not None and mv(s, k, 1) * d >= P["d1"][90] for k in range(onset_f + 1, i))
    acc_o = any((opt_ret(s, key, k, 1) or 0) >= P["o5"][90] for k in range(max(lo, (onset_o or lo)) + 1, i))
    if resp_o is not None and resp_f is not None:
        lag = resp_o - resp_f
        cls = "SYNCHRONIZED" if abs(lag) <= 2 else ("OPTION_LEAD" if lag < 0 else "UNDERLYING_LEAD")
    elif resp_o is not None:
        cls = "FALSE_OPTION_MOVE"
    elif resp_f is not None:
        cls = "LAGGING_OPTION" if late_o is not None else "OPTION_NO_RESPONSE"
    else:
        cls = "NO_CLEAR_ONSET"
    tot_f = (pre_f or 0) + (mfe_f or 0)
    tot_o = (pre_o or 0) + (mfe_o or 0)
    return dict(onset_to_det_s=(i - onset_f) * 5, pre_fut=pre_f, fut_mfe_after=mfe_f,
                fut_consumed=(pre_f / tot_f) if (pre_f is not None and tot_f > 0) else None,
                pre_opt=pre_o, opt_mfe_after=mfe_o, opt_consumed=(pre_o / tot_o) if (pre_o is not None and tot_o > 0) else None,
                det_to_entry_opt=((om(entry_i) - om(i)) / om(i) * 100.0) if om(i) and om(entry_i) else None,
                t_fut_peak_after_det=(t_peak_f * 5) if t_peak_f else None,
                resp_f_before_det=resp_f is not None and resp_f < i, resp_o_before_det=resp_o is not None and resp_o < i,
                resp_lag_bars=(resp_o - resp_f) if (resp_o is not None and resp_f is not None) else None,
                acc_both_before=acc_f and acc_o, cls=cls, fade=(fade is not None and fade >= 0.5), fade_ratio=fade)


# ------------------------------------------------------------------ trade simulation for a trigger
def simulate(s, i, d, key, origin_i, cfg, delay, plan_ref_i=None):
    e = i + delay
    if e >= len(s):
        return None
    qe = s.quote(key, e)
    qd = s.quote(key, plan_ref_i if plan_ref_i is not None else i)
    if qe is None or not qe.valid or qd is None or not qd.valid:
        return None
    f_i, f_o = fut(s, i), fut(s, origin_i)
    disp = (f_i - f_o) if (f_i is not None and f_o is not None) else 0.0
    size = max(abs(disp), s.strike_step * 0.05)
    ev = Event(i, T.MOMENTUM_EVENT, T.STRONG, d, None, d * size, None, None, None, d * size, f_i - d * size)
    plan = plan_risk(ev, Selection(s.legs[key], qd, None, None, 0), cfg)
    x = simulate_exit(s, key, e, ev, plan, cfg)
    cf = track(s, key, e, d, cfg)
    ask = qe.ask
    fixed = {}
    for h in HOLDS:
        k = e + h // 5
        qk = s.quote(key, k) if k < len(s) else None
        fixed[h] = ((qk.bid - ask) / ask * 100.0) if qk and qk.valid else None
    path = []
    for k in range(e + 1, min(len(s), e + 25)):
        qk = s.quote(key, k)
        if qk and qk.valid:
            path.append(((k - e) * 5, (qk.bid - ask) / ask * 100.0))
    xq = s.quote(key, x.exit_index) if x.exit_index is not None else None
    return dict(entry_ask=ask, spread_in=qe.spread_pct, spread_out=xq.spread_pct if xq else None,
                pnl=x.pnl_pct if x.reason != OPEN else None, reason=x.reason, hold=x.hold_seconds,
                peak=x.peak_gain_pct, mfe=cf.mfe_pct if cf else None, mae=cf.mae_pct if cf else None,
                t_mfe=cf.t_mfe_s if cf else None, t_mae=cf.t_mae_s if cf else None, fixed=fixed, path=path,
                capture=(x.pnl_pct / cf.mfe_pct) if (cf and cf.mfe_pct and cf.mfe_pct > 0 and x.pnl_pct is not None) else None,
                plan_ask=plan.entry_ref_ask)


# ------------------------------------------------------------------ 12A-EARLY triggers (Part 3)
def early_triggers(s, P, cfg):
    out, last = [], {f: -10**9 for f in FAMILIES}
    cd = cfg.cooldown_seconds // cfg.bar_seconds
    for i in range(W + 1, len(s)):
        d1, d1p = mv(s, i, 1), mv(s, i - 1, 1)
        r10, r15, r60 = mv(s, i, 2), mv(s, i, 3), mv(s, i, 12)
        r60p = mv(s, i - 2, 12)
        if None in (d1, d1p, r10, r15, r60):
            continue
        ce5, pe5 = opt_ret(s, ("CE", 0), i, 1), opt_ret(s, ("PE", 0), i, 1)
        ce10, pe10 = opt_ret(s, ("CE", 0), i, 2), opt_ret(s, ("PE", 0), i, 2)
        cons3 = lambda dd: sum(1 for k in range(i - 2, i + 1) if (mv(s, k, 1) or 0) * dd > 0)
        cand = []
        if abs(r15) >= P["r15"][95] and cons3(1 if r15 > 0 else -1) >= 2:
            cand.append(("A_EARLY_MOMENTUM", 1 if r15 > 0 else -1))
        if abs(d1) >= P["d1"][95] and d1 * d1p >= 0 and abs(d1) > abs(d1p):
            cand.append(("B_ACCELERATION", 1 if d1 > 0 else -1))
        if ce5 is not None and pe5 is not None and abs(ce5 - pe5) >= P["syn5"][95] and abs(d1) <= P["d1"][75]:
            cand.append(("C_OPTION_LEADS", 1 if ce5 > pe5 else -1))
        prev_imp = [mv(s, i - k, 2) for k in (1, 2)]
        for dd in (1, -1):
            if any(v is not None and v * dd >= P["r10"][90] for v in prev_imp):
                o = opt_ret(s, leg_for(dd), i, 1)
                if o is not None and o >= P["o5"][75]:
                    cand.append(("D_UNDERLYING_LEADS", dd))
                    break
        dd = 1 if r10 > 0 else -1
        o10 = opt_ret(s, leg_for(dd), i, 2)
        if abs(r10) >= P["r10"][90] and o10 is not None and o10 >= P["o10"][90]:
            cand.append(("E_BOTH_CONFIRM", dd))
        if r60p is not None and abs(r60p) >= P["r60"][90] and r60p * r10 < 0 and abs(r10) >= P["r10"][90]:
            cand.append(("F_REVERSAL", dd))
        if abs(r60) >= P["r60"][90] and r60 * r10 > 0 and abs(r10) >= P["r10"][75]:
            steps = [mv(s, k, 1) for k in range(i - 11, i + 1)]
            steps = [v for v in steps if v]
            if steps and sum(1 for v in steps if v * r60 > 0) / len(steps) >= 0.6:
                cand.append(("G_CONTINUATION", 1 if r60 > 0 else -1))
        for fam, dd in cand:
            if i - last[fam] < cd:
                continue
            last[fam] = i
            out.append((fam, i, dd))
    return out


def approve(s, i, d, P, cfg, version=2):
    """Research approval checklist (causal, prior-day percentiles only). Returns (ok, reasons).

    v1 capped the move since onset at 2x the prior median 60 s move -- below the trigger
    thresholds themselves, so it could never pass (a logical defect found by diagnosis).
    v2 (logically consistent, fixed BEFORE looking at approved outcomes): the impulse must
    have started within the last 30 s and must not already be a top-5% one-minute move."""
    reasons = []
    t = (s.times[i] + timedelta(seconds=5)).time()
    if mode_of(t) != "MODE_A":
        reasons.append("WINDOW")
    if s.is_expiry_day and t >= time.fromisoformat(cfg.expiry_transition_zone_start):
        reasons.append("EXPIRY_ZONE")
    lo = max(1, i - W)
    onset = min(range(lo, i + 1), key=lambda k: ((fut(s, k) or 0) - (fut(s, lo) or 0)) * d)
    used = ((fut(s, i) or 0) - (fut(s, onset) or 0)) * d
    if version == 1:
        if used > P["r60"][50] * 2:
            reasons.append("NOT_EARLY")
    elif (i - onset) > 6 or used > P["r60"][95]:
        reasons.append("NOT_EARLY")
    syn = (opt_ret(s, ("CE", 0), i, 2) or 0) - (opt_ret(s, ("PE", 0), i, 2) or 0)
    if syn * d <= 0 or (mv(s, i, 2) or 0) * d <= 0:
        reasons.append("NO_DIRECTIONAL_AGREEMENT")
    o10 = opt_ret(s, leg_for(d), i, 2)
    if o10 is None or o10 < P["o10"][75]:
        reasons.append("OPTION_NOT_RESPONDING")
    qq = s.quote(leg_for(d), i)
    vol = sum((s.quote(leg_for(d), k).volume_delta or 0) for k in range(i - 2, i + 1) if s.quote(leg_for(d), k))
    if qq is None or not qq.valid or (qq.spread_pct or 99) > cfg.max_spread_pct or (qq.quote_age_s or 0) > cfg.max_quote_age_s or vol <= 0:
        reasons.append("LIQUIDITY")
    r300 = mv(s, i, 60)
    if r300 is not None and abs(r300) >= P["r300"][90] and r300 * d > 0:
        reasons.append("EXTENDED")
    return (not reasons), reasons


def components(s, i, d, P, cfg):
    lo = max(1, i - W)
    onset = min(range(lo, i + 1), key=lambda k: ((fut(s, k) or 0) - (fut(s, lo) or 0)) * d)
    used = ((fut(s, i) or 0) - (fut(s, onset) or 0)) * d
    peak = max((((fut(s, k) or 0) - (fut(s, onset) or 0)) * d for k in range(onset, i + 1)), default=0)
    t = (s.times[i] + timedelta(seconds=5))
    qq = s.quote(leg_for(d), i)
    d1, d1p = mv(s, i, 1), mv(s, i - 1, 1)
    o5, o5p = opt_ret(s, leg_for(d), i, 1), opt_ret(s, leg_for(d), i - 1, 1)
    syn = (opt_ret(s, ("CE", 0), i, 2) or 0) - (opt_ret(s, ("PE", 0), i, 2) or 0)
    return {
        "1_earlyness(-used/median60)": -(used / P["r60"][50]) if P["r60"][50] else None,
        "2_underlying_strength(r10 pctl)": prank(P, "r10", abs(mv(s, i, 2) or 0)),
        "3_acceleration(pctl)": prank(P, "acc", abs((d1 or 0) - (d1p or 0))) if (d1 or 0) * d > 0 else 0.0,
        "4_option_response(o10 pctl)": prank(P, "o10", max(0.0, opt_ret(s, leg_for(d), i, 2) or 0)),
        "5_option_acceleration(o5-o5prev)": ((o5 or 0) - (o5p or 0)),
        "6_direction_agreement": 1.0 if syn * d > 0 else 0.0,
        "7_liquidity(-spread%)": -(qq.spread_pct or 0) if qq else None,
        "8_extension(-r300 pctl)": -(prank(P, "r300", abs(mv(s, i, 60) or 0)) or 0),
        "9_reversal_risk(-retrace pts)": -(peak - used),
        "10_time_remaining_s": (time(15, 15).hour * 3600 + 15 * 60) - (t.hour * 3600 + t.minute * 60 + t.second),
    }


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
            for sym, ts, b, a in conn.execute(
                    "SELECT symbol, bar_ts, futures_bid, futures_ask FROM hr_option_transition_state WHERE session_id=%s", (sid[d],)).fetchall():
                if b and a:
                    mids[(d, sym, ts)] = (float(b) + float(a)) / 2.0
        fq = conn.execute("SELECT s.trading_date, h.symbol, round(100.0*avg(CASE WHEN h.trade_count=0 THEN 1 ELSE 0 END)::numeric,1), "
                          "round(avg(h.trade_count)::numeric,2) FROM hr_ohlc_5s h JOIN hr_capture_sessions s USING(session_id) "
                          "WHERE h.instrument_type='FUTIDX' GROUP BY 1,2 ORDER BY 2,1").fetchall()
        n_opt_obs = conn.execute("SELECT count(*) FROM hr_option_5s o JOIN hr_capture_sessions s USING(session_id) "
                                 "WHERE s.status LIKE 'COMPLETED%%'").fetchone()[0]
    expiries = {}
    for d in days:
        for sym, s in sessions[d].items():
            expiries.setdefault(sym, set()).add(s.expiry)
    lots = bt.lot_sizes(expiries)
    # research price reference: futures bid/ask MID (the last-trade price is stale for SENSEX:
    # no trade in 84-95% of 5 s bars). The current-12A replay keeps its own last-trade data.
    smid = {}
    for d in days:
        smid[d] = {}
        for sym in cfg.symbols:
            s0 = sessions[d][sym]
            m = [mids.get((d, sym, t)) for t in s0.times]
            smid[d][sym] = replace(s0, fut=m, fut_updated=[x is not None for x in m])

    # causal distributions / thresholds
    Pd, thr12 = {}, {}
    for n, d in enumerate(days):
        for sym in cfg.symbols:
            prior = [sessions[p][sym] for p in days[:n]]
            thr12[(d, sym)] = build_thresholds(prior, cfg)          # current 12A, unchanged
            pm = [smid[p][sym] for p in days[:n]]
            po = [x for x in pm if not x.is_expiry_day] or pm
            Pd[(d, sym)] = dist(pm, po) if len(pm) >= MIN_PRIOR else None
    evaluable = [d for d in days if all(Pd[(d, s)] for s in cfg.symbols)]

    # ---------------- current 12A (unchanged engine)
    cur = []
    cands_by_day = {}
    for d in days:
        res = evaluate_day(list(sessions[d].values()), {s: thr12[(d, s)] for s in cfg.symbols}, cfg)
        cands_by_day[d] = [c for r in res.values() for c in r.candidates]
    led_l, blk_l, _ = bt.account(cands_by_day, sessions, lots, cfg, "EXCHANGE_LOTS")
    traded_l = {(t["date"], t["symbol"], t["detection"]) for t in led_l}
    blocked_l = {(str(c.trading_date), c.symbol, bt.qclose(sessions[c.trading_date][c.symbol], c.bar_index).strftime("%H:%M:%S")): r
                 for c, r in blk_l}
    for d in evaluable:
        for c in cands_by_day[d]:
            s, P = sessions[d][c.symbol], Pd[(d, c.symbol)]
            sm_ = smid[d][c.symbol]
            dirn = c.event.direction
            own_key = (c.selection.leg.option_type, c.selection.leg.atm_offset) if c.selection and c.selection.leg else leg_for(dirn)
            origin = c.bar_index - (36 if c.event.event_type == T.CONTINUATION_EVENT else 6)
            det = bt.qclose(s, c.bar_index).strftime("%H:%M:%S")
            k = (str(d), c.symbol, det)
            reasons = [r for r in c.no_trade_reasons if r not in (T.POSITION_OPEN, T.DAILY_LIMIT_REACHED)]
            if k in blocked_l and blocked_l[k] not in reasons:
                reasons.append(blocked_l[k])
            rec = dict(date=str(d), symbol=c.symbol, time=det, i=c.bar_index, dir=dirn, family="CURRENT_12A_" + c.event.event_type,
                       strength=c.event.strength, mode=c.mode, window=window_of((s.times[c.bar_index] + timedelta(seconds=5)).time()),
                       expiry=s.is_expiry_day, passed=c.passed_gates, traded_lots=k in traded_l, reasons=reasons,
                       anat=anatomy(sm_, c.bar_index, dirn, leg_for(dirn), P, c.bar_index + 2),
                       sims={lbl: simulate(s, c.bar_index, dirn, leg_for(dirn), origin, cfg, dl) for lbl, dl in DELAYS.items()},
                       sim_own=simulate(s, c.bar_index, dirn, own_key, origin, cfg, 2),
                       cf_pnl=(c.counterfactual_exit.pnl_pct if c.counterfactual_exit and c.counterfactual_exit.reason != OPEN else None),
                       cf_mfe=c.counterfactual.mfe_pct if c.counterfactual else None,
                       cf_mae=c.counterfactual.mae_pct if c.counterfactual else None,
                       cf_tmfe=c.counterfactual.t_mfe_s if c.counterfactual else None,
                       cf_tmae=c.counterfactual.t_mae_s if c.counterfactual else None,
                       timing=c.opportunity.timing if c.opportunity else None, dq=c.data_quality)
            cur.append(rec)

    # ---------------- 12A-EARLY triggers
    early = []
    for d in evaluable:
        for sym in cfg.symbols:
            s, P = smid[d][sym], Pd[(d, sym)]
            for fam, i, dirn in early_triggers(s, P, cfg):
                ok, why = approve(s, i, dirn, P, cfg, version=2)
                ok1, why1 = approve(s, i, dirn, P, cfg, version=1)
                early.append(dict(date=str(d), symbol=sym, time=bt.qclose(s, i).strftime("%H:%M:%S"), i=i, dir=dirn, family=fam,
                                  mode=mode_of((s.times[i] + timedelta(seconds=5)).time()),
                                  window=window_of((s.times[i] + timedelta(seconds=5)).time()), expiry=s.is_expiry_day,
                                  approved=ok, reasons=why, approved_v1=ok1, reasons_v1=why1, comp=components(s, i, dirn, P, cfg),
                                  anat=anatomy(s, i, dirn, leg_for(dirn), P, i + 2),
                                  sims={lbl: simulate(s, i, dirn, leg_for(dirn), max(0, i - 3), cfg, dl) for lbl, dl in DELAYS.items()}))

    # ---------------- random baseline (Mode A, random direction, ATM, same exit engine, 5 s entry)
    rng = random.Random(12)
    rnd = []
    for d in evaluable:
        for sym in cfg.symbols:
            s = smid[d][sym]
            elig = [i for i, t in enumerate(s.times) if mode_of((t + timedelta(seconds=5)).time()) == "MODE_A" and i > W and i + 30 < len(s)
                    and not (s.is_expiry_day and (t + timedelta(seconds=5)).time() >= time.fromisoformat(cfg.expiry_transition_zone_start))]
            for i in rng.sample(elig, min(60, len(elig))):
                dd = rng.choice([1, -1])
                sm = simulate(s, i, dd, leg_for(dd), i - 3, cfg, 2)
                if sm:
                    rnd.append(dict(date=str(d), symbol=sym, sim=sm))

    # ---------------- expiry research: random ATM entries on ALL HR days (no thresholds needed)
    exp_rows = []
    rng2 = random.Random(7)
    for d in days:
        for sym in cfg.symbols:
            s = smid[d][sym]
            for i in range(W + 1, len(s) - 30, 3):
                t = (s.times[i] + timedelta(seconds=5)).time()
                if t < time(15, 0):
                    continue
                dd = rng2.choice([1, -1])
                sm = simulate(s, i, dd, leg_for(dd), i - 3, cfg, 2)
                if sm:
                    w = "15:00-15:10" if t < time(15, 10) else ("15:10-15:15" if t < time(15, 15) else "15:15+")
                    exp_rows.append(dict(date=str(d), symbol=sym, expiry=s.is_expiry_day, w=w, sim=sm))

    R = analyse(cfg, days, evaluable, sessions, lots, cur, early, rnd, exp_rows, n_opt_obs, Pd)
    R["futures_quality"] = [dict(date=str(a), symbol=b, no_trade_bar_pct=float(c), trades_per_bar=float(e)) for a, b, c, e in fq]
    R["early_v1"] = dict(approved=sum(r["approved_v1"] for r in early), reasons={})
    for r in early:
        for x in r["reasons_v1"]:
            R["early_v1"]["reasons"][x] = R["early_v1"]["reasons"].get(x, 0) + 1
    (OUT / "nextgen.json").write_text(json.dumps(R, default=str, indent=1), encoding="utf-8")
    for name, rows in (("current_candidates.csv", cur), ("early_triggers.csv", early)):
        flat = []
        for r in rows:
            f = {k: v for k, v in r.items() if k not in ("anat", "sims", "sim_own", "comp")}
            f.update({f"anat_{k}": v for k, v in r["anat"].items()})
            s5 = r["sims"].get("5s (i+2, current poller)") or {}
            f.update({f"sim5_{k}": v for k, v in s5.items() if k not in ("fixed", "path")})
            flat.append(f)
        with open(OUT / name, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(flat[0].keys()))
            w.writeheader()
            w.writerows(flat)
    REPORT.write_text(build_html(R, cfg), encoding="utf-8")
    print(json.dumps({k: R[k] for k in ("data", "decision_inputs")}, default=str, indent=1))


# ------------------------------------------------------------------ analysis
def sim_stats(recs, lbl="5s (i+2, current poller)"):
    sims = [r["sims"][lbl] if "sims" in r else r["sim"] for r in recs]
    sims = [x for x in sims if x]
    n = len(sims)
    pn = [x["pnl"] for x in sims if x["pnl"] is not None]
    return dict(n=n, pnl_mean=mean(pn), pnl_median=med(pn), profitable_pct=pct(sum(1 for v in pn if v > 0), len(pn)),
                mfe=med([x["mfe"] for x in sims]), mae=med([x["mae"] for x in sims]), mae_p10=q([x["mae"] for x in sims], 10),
                t_mfe=med([x["t_mfe"] for x in sims], 0), t_mae=med([x["t_mae"] for x in sims], 0),
                capture=med([x["capture"] for x in sims]), spread_in=med([x["spread_in"] for x in sims]),
                entry_ask=med([x["entry_ask"] for x in sims], 2),
                fixed={h: med([x["fixed"].get(h) for x in sims]) for h in HOLDS},
                fixed_pos={h: pct(sum(1 for x in sims if (x["fixed"].get(h) or -1) > 0), sum(1 for x in sims if x["fixed"].get(h) is not None)) for h in HOLDS})


def per_day(recs, lbl="5s (i+2, current poller)"):
    out = {}
    for d in sorted({r["date"] for r in recs}):
        sub = [r for r in recs if r["date"] == d]
        out[d] = sim_stats(sub, lbl)
    return out


def analyse(cfg, days, evaluable, sessions, lots, cur, early, rnd, exp_rows, n_opt_obs, Pd):
    R = {}
    strong = [r for r in cur if r["strength"] == T.STRONG]
    prof = [r for r in cur if (r["cf_pnl"] or 0) > 0 or (r["cf_mfe"] or 0) >= 2]
    R["data"] = dict(hr_days=len(days), days=[str(d) for d in days], evaluable=[str(d) for d in evaluable],
                     symbol_days=len(days) * len(cfg.symbols), evaluable_symbol_days=len(evaluable) * len(cfg.symbols),
                     current_events=len(cur), current_strong=len(strong), early_triggers=len(early),
                     early_approved=sum(r["approved"] for r in early), option_observations=n_opt_obs,
                     expiry_symbol_days=[f"{d} {s}" for d in days for s in cfg.symbols if sessions[d][s].is_expiry_day],
                     evaluable_expiry=[f"{d} {s}" for d in evaluable for s in cfg.symbols if sessions[d][s].is_expiry_day])

    # ---- Part 2
    def p2(pool):
        a = [r["anat"] for r in pool]
        return dict(n=len(pool),
                    onset_to_det_s=dict(p25=q([x["onset_to_det_s"] for x in a], 25), med=med([x["onset_to_det_s"] for x in a], 0), p75=q([x["onset_to_det_s"] for x in a], 75)),
                    pre_fut=dict(p25=q([x["pre_fut"] for x in a], 25), med=med([x["pre_fut"] for x in a], 2), p75=q([x["pre_fut"] for x in a], 75)),
                    fut_consumed=dict(p25=q([x["fut_consumed"] for x in a], 25), med=med([x["fut_consumed"] for x in a]), p75=q([x["fut_consumed"] for x in a], 75)),
                    pre_opt=dict(p25=q([x["pre_opt"] for x in a], 25), med=med([x["pre_opt"] for x in a], 2), p75=q([x["pre_opt"] for x in a], 75)),
                    opt_consumed=dict(p25=q([x["opt_consumed"] for x in a], 25), med=med([x["opt_consumed"] for x in a]), p75=q([x["opt_consumed"] for x in a], 75)),
                    det_to_entry_opt=dict(p25=q([x["det_to_entry_opt"] for x in a], 25), med=med([x["det_to_entry_opt"] for x in a], 2), p75=q([x["det_to_entry_opt"] for x in a], 75)),
                    opt_mfe_after=med([x["opt_mfe_after"] for x in a], 2), fut_mfe_after=med([x["fut_mfe_after"] for x in a], 2),
                    t_fut_peak_after_det=med([x["t_fut_peak_after_det"] for x in a], 0),
                    consumed_gt_25=pct(sum(1 for x in a if (x["opt_consumed"] or 0) > 0.25), len(a)),
                    consumed_gt_50=pct(sum(1 for x in a if (x["opt_consumed"] or 0) > 0.5), len(a)),
                    opt_resp_before_det=pct(sum(1 for x in a if x["resp_o_before_det"]), len(a)),
                    fut_resp_before_det=pct(sum(1 for x in a if x["resp_f_before_det"]), len(a)),
                    acc_both_before=pct(sum(1 for x in a if x["acc_both_before"]), len(a)),
                    fade=pct(sum(1 for x in a if x["fade"]), len(a)))
    R["part2"] = {"all current events": p2(cur), "strong": p2(strong), "profitable (cf>0 or MFE>=2%)": p2(prof),
                  "NIFTY": p2([r for r in cur if r["symbol"] == "NIFTY"]), "SENSEX": p2([r for r in cur if r["symbol"] == "SENSEX"])}

    # ---- Part 4: lead/lag classes (current + early)
    def classes(pool):
        c = {}
        for r in pool:
            c[r["anat"]["cls"]] = c.get(r["anat"]["cls"], 0) + 1
        return dict(counts=c, fade=sum(1 for r in pool if r["anat"]["fade"]), n=len(pool),
                    outcome={k: sim_stats([r for r in pool if r["anat"]["cls"] == k]) for k in c})
    R["part4"] = {"current 12A events": classes(cur), "12A-EARLY triggers": classes(early)}

    # ---- Part 3 / 16: architecture comparison (5 s entry, ATM leg for all)
    cur_pass = [r for r in cur if r["passed"]]
    comp = {"1. Current 12A - gate-passing (own leg)": dict(sim_stats([dict(sims={"x": r["sim_own"]}) for r in cur_pass], "x"), days=None),
            "1b. Current 12A - gate-passing (ATM leg)": sim_stats(cur_pass),
            "1c. Current 12A - all strong events (ATM)": sim_stats(strong),
            "2. Random entries, Mode A (ATM)": sim_stats(rnd),
            "4. 12A-EARLY - all triggers (ATM)": sim_stats(early),
            "4b. 12A-EARLY - approved, Mode A (ATM)": sim_stats([r for r in early if r["approved"]])}
    for fam in FAMILIES:
        comp[f"   family {fam} (all)"] = sim_stats([r for r in early if r["family"] == fam])
        comp[f"   family {fam} (approved)"] = sim_stats([r for r in early if r["family"] == fam and r["approved"]])
    R["comparison"] = comp
    R["stability"] = {"Current 12A gate-passing (ATM)": per_day(cur_pass), "Random": {d: sim_stats([r for r in rnd if r["date"] == d]) for d in sorted({r["date"] for r in rnd})},
                      "12A-EARLY approved": per_day([r for r in early if r["approved"]]), "12A-EARLY all": per_day(early)}
    R["consumed_at_entry"] = {
        "Current 12A all": med([r["anat"]["fut_consumed"] for r in cur]),
        "Current 12A gate-passing": med([r["anat"]["fut_consumed"] for r in cur_pass]),
        "12A-EARLY all": med([r["anat"]["fut_consumed"] for r in early]),
        "12A-EARLY approved": med([r["anat"]["fut_consumed"] for r in early if r["approved"]])}
    R["early_reject_reasons"] = {}
    for r in early:
        for x in r["reasons"]:
            R["early_reject_reasons"][x] = R["early_reject_reasons"].get(x, 0) + 1

    # ---- Part 5: entry timing
    R["part5"] = {grp: {lbl: sim_stats(pool, lbl) for lbl in DELAYS} for grp, pool in
                  (("Current 12A gate-passing", cur_pass), ("Current 12A all strong", strong), ("12A-EARLY approved", [r for r in early if r["approved"]]),
                   ("12A-EARLY all", early))}

    # ---- Part 7: component contribution, chronological sign stability
    comp_rows = [r for r in early if r["mode"] == "MODE_A"]
    names = list(comp_rows[0]["comp"].keys()) if comp_rows else []
    part7 = {}
    for nm in names:
        by = {}
        for d in sorted({r["date"] for r in comp_rows}):
            sub = [r for r in comp_rows if r["date"] == d]
            y = [(r["sims"]["5s (i+2, current poller)"] or {}).get("pnl") for r in sub]
            by[d] = spearman([r["comp"][nm] for r in sub], y)
        signs = [v[0] for v in by.values() if v[0] is not None]
        part7[nm] = dict(by_day=by, stable_sign=(len(signs) == len(by) and len(signs) > 1 and (all(v > 0 for v in signs) or all(v < 0 for v in signs))))
    R["part7"] = part7

    # ---- Part 9: sizing
    def lot_of(r):
        s = sessions[next(d for d in evaluable if str(d) == r["date"])][r["symbol"]]
        return lots.get((r["symbol"], s.expiry), (None, ""))[0]
    size_rows = []
    for grp, pool in (("Current 12A gate-passing", cur_pass), ("12A-EARLY approved", [r for r in early if r["approved"]])):
        for r in pool:
            sm = r["sims"]["5s (i+2, current poller)"]
            if not sm:
                continue
            lot = lot_of(r)
            ask = sm["plan_ask"]
            size_rows.append(dict(group=grp, date=r["date"], time=r["time"], symbol=r["symbol"], premium=ask, lot=lot,
                                  stop_dist=round(ask * cfg.stop_pct / 100, 2), risk_lot=round(ask * cfg.stop_pct / 100 * lot, 2),
                                  cap_lot=round(ask * lot, 2), risk_pct_acct=round(ask * cfg.stop_pct / 100 * lot / cfg.starting_capital * 100, 2),
                                  cap_pct_acct=round(ask * lot / cfg.starting_capital * 100, 1)))
    R["part9_rows"] = size_rows
    scen = []
    for grp, pool in (("Current 12A gate-passing", cur_pass), ("12A-EARLY approved", [r for r in early if r["approved"]])):
        for ml in (300, 400, 500, 600):
            for mc in (6000, 7500, 10000):
                scen.append(dict(group=grp, max_loss=ml, max_cap=mc, **account_sim(pool, lot_of, ml, mc, cfg)))
    R["part9_scenarios"] = scen

    # ---- Part 10: exits
    ex_pool = [r["sims"]["5s (i+2, current poller)"] for r in strong + early] + [r["sim"] for r in rnd]
    ex_pool = [x for x in ex_pool if x]
    good = [x for x in ex_pool if any(v >= 2.0 for t, v in x["path"] if t <= 120)]
    bad = [x for x in ex_pool if not any(v >= 1.0 for t, v in x["path"] if t <= 120)]
    abandon = {}
    for t in (5, 10, 15, 20, 30, 45, 60):
        uw = lambda x: next((v for tt, v in x["path"] if tt == t), None)
        g = [uw(x) for x in good if uw(x) is not None]
        b = [uw(x) for x in bad if uw(x) is not None]
        abandon[t] = dict(good_underwater_pct=pct(sum(1 for v in g if v < 0), len(g)), bad_underwater_pct=pct(sum(1 for v in b if v < 0), len(b)),
                          good_n=len(g), bad_n=len(b), good_below_minus1_pct=pct(sum(1 for v in g if v <= -1), len(g)),
                          bad_below_minus1_pct=pct(sum(1 for v in b if v <= -1), len(b)))
    first_hit = {}
    for x_pct in (0.5, 1.0, 2.0):
        ts = [next((t for t, v in x["path"] if v >= x_pct), None) for x in good]
        first_hit[x_pct] = dict(median_s=med(ts, 0), p75_s=q(ts, 75), n=len([t for t in ts if t is not None]))
    R["part10"] = dict(pool=len(ex_pool), good=len(good), bad=len(bad), abandon=abandon, first_hit=first_hit,
                       fixed_all={h: med([x["fixed"].get(h) for x in ex_pool]) for h in HOLDS},
                       fixed_good={h: med([x["fixed"].get(h) for x in good]) for h in HOLDS},
                       fixed_bad={h: med([x["fixed"].get(h) for x in bad]) for h in HOLDS},
                       active_exit_reasons={k: sum(1 for x in ex_pool if x["reason"] == k) for k in sorted({x["reason"] for x in ex_pool})})

    # ---- Part 11: missed opportunities
    miss = []
    for r in cur:
        if r["traded_lots"]:
            continue
        if not ((r["cf_pnl"] or 0) > 0 or (r["cf_mfe"] or 0) >= 2):
            continue
        rs = r["reasons"]
        if r["dq"] != "GOOD":
            cls = "DATA_QUALITY"
        elif any(x in rs for x in (T.EXPIRY_DAY_CLOSE_VETO, T.EXPIRY_TRANSITION_ZONE)):
            cls = "EXPIRY_RISK"
        elif any(x in rs for x in (T.TIME_WINDOW_CLOSED, T.MODE_B_RESEARCH_ONLY)):
            cls = "WINDOW_RESTRICTION"
        elif T.RISK_TOO_LARGE in rs:
            cls = "RISK_TOO_LARGE"
        elif T.OPTION_NOT_RESPONDING in rs and not any(x in rs for x in (T.WEAK_MOMENTUM, T.NO_CONFIRMATION)):
            cls = "OPTION_DID_NOT_RESPOND"
        elif ((r["cf_mae"] or 0) <= -cfg.stop_pct and (r["cf_tmae"] or 1e9) < (r["cf_tmfe"] or 0)) or (r["cf_pnl"] or 0) <= 0:
            cls = "FALSE_OPPORTUNITY"           # the option moved, but not capturably by a scalp (active exit lost)
        elif (r["cf_mfe"] or 0) < 1.0:
            cls = "MOVE_TOO_SMALL"
        elif r["timing"] in ("DETECTED_LATE", "NO_FOLLOW_THROUGH"):
            cls = "LATE_TRADE"
        else:
            cls = "GOOD_MISSED_TRADE"
        prior_early = [e for e in early if e["date"] == r["date"] and e["symbol"] == r["symbol"] and e["dir"] == r["dir"]
                       and 0 <= r["i"] - e["i"] <= 12]
        first = min(prior_early, key=lambda e: e["i"]) if prior_early else None
        miss.append(dict(date=r["date"], time=r["time"], symbol=r["symbol"], dir="UP" if r["dir"] > 0 else "DOWN", mode=r["mode"],
                         first_reason=rs[0] if rs else "-", cls=cls, cf_pnl=r["cf_pnl"], mfe=r["cf_mfe"], mae=r["cf_mae"],
                         t_mfe=r["cf_tmfe"], t_mae=r["cf_tmae"], timing=r["timing"],
                         early_trigger=(f"{first['family']} at {first['time']} ({(r['i'] - first['i']) * 5} s earlier)" if first else "none"),
                         early_approved=bool(first and first["approved"])))
    R["part11"] = miss

    # ---- Part 12: windows x event class (early triggers)
    def evcls(r):
        s5 = r["sims"]["5s (i+2, current poller)"] or {}
        if (s5.get("pnl") or 0) <= 0 and (r["anat"]["fut_mfe_after"] or 0) <= (Pd[(next(d for d in evaluable if str(d) == r["date"]), r["symbol"])]["d1"][75] or 0):
            return "NOISE"
        return {"F_REVERSAL": "REVERSAL", "G_CONTINUATION": "CONTINUATION"}.get(r["family"], "EARLY_IMPULSE")
    wins = {}
    for r in early:
        k = (r["window"], evcls(r))
        wins.setdefault(k, []).append(r)
    R["part12"] = {f"{w} | {c}": dict(n=len(v), **{k: sim_stats(v)[k] for k in ("pnl_median", "profitable_pct", "mfe", "mae")})
                   for (w, c), v in sorted(wins.items())}

    # ---- Part 13: expiry
    R["part13"] = {}
    for ex in (False, True):
        for w in ("15:00-15:10", "15:10-15:15", "15:15+"):
            sub = [x["sim"] for x in exp_rows if x["expiry"] == ex and x["w"] == w]
            R["part13"][f"{'EXPIRY' if ex else 'NORMAL'} | {w}"] = dict(
                n=len(sub), symbol_days=len({(x['date'], x['symbol']) for x in exp_rows if x['expiry'] == ex and x['w'] == w}),
                mae=med([x["mae"] for x in sub]), mae_p10=q([x["mae"] for x in sub], 10), mfe=med([x["mfe"] for x in sub]),
                fixed60=med([x["fixed"].get(60) for x in sub]), fixed120=med([x["fixed"].get(120) for x in sub]),
                spread=med([x["spread_in"] for x in sub]))

    # ---- Part 14: symbols
    R["part14"] = {sym: {"current strong": sim_stats([r for r in strong if r["symbol"] == sym]),
                         "current gate-passing": sim_stats([r for r in cur_pass if r["symbol"] == sym]),
                         "early all": sim_stats([r for r in early if r["symbol"] == sym]),
                         "early approved": sim_stats([r for r in early if r["symbol"] == sym and r["approved"]]),
                         "random": sim_stats([r for r in rnd if r["symbol"] == sym])} for sym in cfg.symbols}

    ea = comp["4b. 12A-EARLY - approved, Mode A (ATM)"]
    R["decision_inputs"] = dict(current=comp["1. Current 12A - gate-passing (own leg)"], random=comp["2. Random entries, Mode A (ATM)"],
                                early_all=comp["4. 12A-EARLY - all triggers (ATM)"], early_approved=ea, consumed=R["consumed_at_entry"],
                                opt_before=R["part2"]["all current events"]["opt_resp_before_det"])
    return R


def account_sim(pool, lot_of, max_loss, max_cap, cfg):
    trades, blocked = [], 0
    for d in sorted({r["date"] for r in pool}):
        open_until, n, realised = None, 0, 0.0
        for r in sorted([r for r in pool if r["date"] == d], key=lambda r: r["time"]):
            sm = r["sims"]["5s (i+2, current poller)"] if "sims" in r else None
            if not sm or sm["pnl"] is None:
                continue
            if open_until is not None and r["time"] < open_until:
                continue
            if n >= cfg.max_trades_per_day or realised <= -cfg.max_daily_loss:
                continue
            lot = lot_of(r)
            ask = sm["plan_ask"]
            lots_n = min(math.floor(max_loss / (ask * cfg.stop_pct / 100 * lot)), math.floor(max_cap / (ask * lot))) if lot else 0
            if lots_n < 1:
                blocked += 1
                continue
            qty = lots_n * lot
            pnl = sm["pnl"] / 100 * sm["entry_ask"] * qty
            realised += pnl
            n += 1
            t_exit = (timedelta(hours=int(r["time"][:2]), minutes=int(r["time"][3:5]), seconds=int(r["time"][6:])) + timedelta(seconds=10 + (sm["hold"] or 0)))
            open_until = f"{t_exit.seconds // 3600:02d}:{(t_exit.seconds // 60) % 60:02d}:{t_exit.seconds % 60:02d}"
            trades.append(dict(date=d, pnl=pnl, mfe=sm["mfe"], pnl_pct=sm["pnl"]))
    pn = [t["pnl"] for t in trades]
    bal, peak, mdd, streak, worst_streak = 0.0, 0.0, 0.0, 0, 0
    for p in pn:
        bal += p
        peak = max(peak, bal)
        mdd = max(mdd, peak - bal)
        streak = streak + 1 if p <= 0 else 0
        worst_streak = max(worst_streak, streak)
    wins, losses = [p for p in pn if p > 0], [p for p in pn if p <= 0]
    caps = [t["pnl_pct"] / t["mfe"] for t in trades if t["mfe"] and t["mfe"] > 0]
    return dict(trades=len(pn), blocked=blocked, expectancy=round(st.mean(pn), 2) if pn else None,
                win_rate=pct(len(wins), len(pn)), avg_win=round(st.mean(wins), 2) if wins else None,
                avg_loss=round(st.mean(losses), 2) if losses else None, net=round(sum(pn), 2), max_dd=round(mdd, 2),
                max_consec_losses=worst_streak, capture=med(caps), risk_adj=round(st.mean(pn) / st.pstdev(pn), 3) if len(pn) > 1 and st.pstdev(pn) > 0 else None,
                by_day={d: round(sum(t["pnl"] for t in trades if t["date"] == d), 2) for d in sorted({t["date"] for t in trades})})


# ------------------------------------------------------------------ report
def _v(x, nd=2, pct_=False):
    if x is None:
        return "&ndash;"
    if isinstance(x, bool):
        return "Yes" if x else "No"
    if isinstance(x, float):
        return (f"{x:+.{nd}f}%" if pct_ else f"{x:,.{nd}f}")
    return str(x)


def _t(h, rows):
    return "<table><tr>" + "".join(f"<th>{x}</th>" for x in h) + "</tr>" + "".join(
        "<tr>" + "".join(f"<td>{v}</td>" for v in r) + "</tr>" for r in rows) + "</table>"


def build_html(R, cfg):
    from nextgen_report import render   # separate module keeps this file readable
    return render(R, cfg, _v, _t, HOLDS, DELAYS, FAMILIES)


if __name__ == "__main__":
    main()
