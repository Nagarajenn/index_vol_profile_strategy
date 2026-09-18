"""Step 2: 1-minute historical research for 12A (chronological split).

Source: option_chain_raw (one full chain snapshot ~per minute, with bid/ask,
greeks, volume). Window 14:30-15:30, grouped into PRE / MODE_A / MODE_B.

What this can establish: CANDIDATE RANGES at 1-minute resolution for option
premium response, MFE/MAE, holding duration (1-5 min), spread cost,
target/stop behaviour, option selection (moneyness) and expiry-day tails.

What it CANNOT establish: anything about 5-second event thresholds,
15-60 s behaviour or the momentum-failure exit. Those need HR data.

Method guards:
* chronological split: thresholds and grid choices are fitted on the TRAIN
  days only and then read out on the later TEST days;
* entry = ASK of the snapshot AFTER the trigger snapshot; exits on the BID;
* one trigger per symbol per 3 snapshots (cooldown), statistics aggregated
  per day before pooling, so minutes are never treated as independent;
* a random baseline (random time, random direction) with identical mechanics;
* index is never used as a signal: the trigger is the ATM synthetic
  (CE mid - PE mid) move, which stays live when the index freezes at 15:15.
"""

import random
import statistics as st
from dataclasses import dataclass, field
from datetime import date, datetime, time

STEP = {"NIFTY": 50.0, "SENSEX": 100.0}
HOLDS = (1, 2, 3, 5)
MONEYNESS = (-2, -1, 0, 1, 2)
TARGETS = (2.0, 3.0, 5.0, 8.0, 12.0)
STOPS = (3.0, 5.0, 8.0, 12.0)
MAX_HOLDS = (1, 2, 3, 5)
COOLDOWN_SNAPSHOTS = 3
TRIGGER_PERCENTILE = 90.0


@dataclass
class Snap:
    ts: datetime
    spot: float
    expiry: date | None
    oc: dict


@dataclass
class Trade:
    date: date
    symbol: str
    ts: datetime
    mode: str
    is_expiry: bool
    kind: str               # EVENT / RANDOM
    direction: int
    moneyness: int
    trigger_x: float | None
    response_pct: float | None
    entry_ask: float
    entry_spread_pct: float
    delta: float | None
    mfe: dict = field(default_factory=dict)   # hold min -> %
    mae: dict = field(default_factory=dict)
    exit: dict = field(default_factory=dict)
    bids: list = field(default_factory=list)  # (minutes_after_entry, bid)
    t_mfe_min: float | None = None


def mode_of(t: time) -> str:
    if t < time(15, 0):
        return "PRE"
    if t < time(15, 15):
        return "MODE_A"
    return "MODE_B"


def leg(oc: dict, strike: float, typ: str) -> dict | None:
    for k, v in oc.items():
        if abs(float(k) - strike) < 1e-6:
            x = v.get(typ.lower())
            return x if x else None
    return None


def mid(x: dict | None) -> float | None:
    if not x:
        return None
    b, a = x.get("top_bid_price"), x.get("top_ask_price")
    if b and a and b > 0 and a >= b:
        return (a + b) / 2.0
    return None


def percentile(vals, p):
    s = sorted(vals)
    if not s:
        return None
    pos = (len(s) - 1) * p / 100.0
    lo = int(pos)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def load_snaps(conn, symbol: str, d: date) -> list[Snap]:
    rows = conn.execute(
        "SELECT fetched_at, spot, expiry, raw_payload FROM option_chain_raw WHERE symbol=%s AND fetched_at::date=%s "
        "AND fetched_at::time BETWEEN '14:28' AND '15:31' ORDER BY fetched_at", (symbol, d)).fetchall()
    out = []
    for ts, spot, exp, p in rows:
        oc = p.get("oc") if isinstance(p, dict) else None
        s = spot or (p.get("last_price") if isinstance(p, dict) else None)
        if oc and s:
            out.append(Snap(ts, float(s), exp, oc))
    return out


def synthetic_x(prev: Snap, cur: Snap, step: float):
    """ATM synthetic move between two snapshots at the SAME strike, / straddle."""
    k = round(prev.spot / step) * step
    ce0, pe0 = mid(leg(prev.oc, k, "CE")), mid(leg(prev.oc, k, "PE"))
    ce1, pe1 = mid(leg(cur.oc, k, "CE")), mid(leg(cur.oc, k, "PE"))
    if None in (ce0, pe0, ce1, pe1) or (ce0 + pe0) <= 0:
        return None, k
    return ((ce1 - pe1) - (ce0 - pe0)) / (ce0 + pe0), k


def build_trade(snaps, i, d, symbol, direction, m, kind, x, is_expiry) -> Trade | None:
    """Trigger at snapshot i; entry at snapshot i+1 ASK; bids from i+2.. ."""
    if i + 1 >= len(snaps):
        return None
    step = STEP[symbol]
    k_atm = round(snaps[i].spot / step) * step
    typ = "CE" if direction > 0 else "PE"
    strike = k_atm + m * step if typ == "CE" else k_atm - m * step
    e = leg(snaps[i + 1].oc, strike, typ)
    if not e:
        return None
    b, a = e.get("top_bid_price"), e.get("top_ask_price")
    if not (b and a and b > 0 and a >= b):
        return None
    if (snaps[i + 1].ts - snaps[i].ts).total_seconds() > 120:
        return None
    resp = None
    prev_leg, cur_leg = (leg(snaps[i - 1].oc, strike, typ) if i > 0 else None), leg(snaps[i].oc, strike, typ)
    if mid(prev_leg) and mid(cur_leg):
        resp = (mid(cur_leg) - mid(prev_leg)) / mid(prev_leg) * 100.0
    t = Trade(d, symbol, snaps[i].ts, mode_of(snaps[i].ts.time()), is_expiry, kind, direction, m, x, resp, float(a),
              (a - b) / a * 100.0, (e.get("greeks") or {}).get("delta"))
    t0 = snaps[i + 1].ts
    for j in range(i + 2, len(snaps)):
        mins = (snaps[j].ts - t0).total_seconds() / 60.0
        if mins > max(HOLDS) + 0.5:
            break
        x2 = leg(snaps[j].oc, strike, typ)
        if x2 and x2.get("top_bid_price"):
            t.bids.append((mins, float(x2["top_bid_price"])))
    for h in HOLDS:
        within = [bid for mn, bid in t.bids if mn <= h + 0.25]
        if within:
            t.mfe[h] = (max(within) - a) / a * 100.0
            t.mae[h] = (min(within) - a) / a * 100.0
            t.exit[h] = (within[-1] - a) / a * 100.0
    if t.bids:
        best = max(t.bids, key=lambda p: p[1])
        t.t_mfe_min = best[0]
    return t if t.exit else None


def simulate_grid(t: Trade, target: float, stop: float, max_hold: int) -> float | None:
    """1-minute-granular target/stop/max-hold. Stop exits at the (worse) observed bid;
    target exits capped at the target (the touch time inside the minute is unknown)."""
    a = t.entry_ask
    last = None
    for mn, bid in t.bids:
        if mn > max_hold + 0.25:
            break
        r = (bid - a) / a * 100.0
        last = r
        if r <= -stop:
            return r
        if r >= target:
            return target
    return last


def day_mean(trades, fn):
    by_day = {}
    for t in trades:
        v = fn(t)
        if v is not None:
            by_day.setdefault((t.date, t.symbol), []).append(v)
    return {k: st.mean(v) for k, v in by_day.items()}


def summarize(vals):
    vals = [v for v in vals if v is not None]
    if not vals:
        return None
    return dict(n=len(vals), median=round(st.median(vals), 3), mean=round(st.mean(vals), 3),
                p10=round(percentile(vals, 10), 3), p90=round(percentile(vals, 90), 3),
                pos=round(sum(1 for v in vals if v > 0) / len(vals), 3))


def bootstrap_ci(day_values: list[float], seed=7, n=2000):
    if len(day_values) < 2:
        return None
    rng = random.Random(seed)
    means = sorted(st.mean(rng.choices(day_values, k=len(day_values))) for _ in range(n))
    return round(means[int(0.025 * n)], 3), round(means[int(0.975 * n)], 3)


def run(conn, symbols=("NIFTY", "SENSEX"), train_fraction=0.65, seed=12):
    days = [r[0] for r in conn.execute(
        "SELECT DISTINCT fetched_at::date d FROM option_chain_raw WHERE fetched_at::date >= '2026-08-03' "
        "AND fetched_at::time >= '15:29' ORDER BY d").fetchall()]
    n_train = max(1, int(round(len(days) * train_fraction)))
    train_days, test_days = days[:n_train], days[n_train:]
    rng = random.Random(seed)

    snaps = {(d, s): load_snaps(conn, s, d) for d in days for s in symbols}

    # 1. trigger threshold from TRAIN days only (per symbol)
    thr = {}
    for s in symbols:
        xs = []
        for d in train_days:
            sn = snaps[(d, s)]
            for i in range(1, len(sn)):
                if (sn[i].ts - sn[i - 1].ts).total_seconds() <= 90:
                    x, _ = synthetic_x(sn[i - 1], sn[i], STEP[s])
                    if x is not None:
                        xs.append(abs(x))
        thr[s] = percentile(xs, TRIGGER_PERCENTILE)

    trades: list[Trade] = []
    for d in days:
        for s in symbols:
            sn = snaps[(d, s)]
            if len(sn) < 10:
                continue
            is_exp = bool(sn[0].expiry and sn[0].expiry == d)
            last = -99
            n_ev = 0
            for i in range(1, len(sn) - 1):
                if sn[i].ts.time() < time(14, 30) or i - last < COOLDOWN_SNAPSHOTS:
                    continue
                if (sn[i].ts - sn[i - 1].ts).total_seconds() > 90:
                    continue
                x, _ = synthetic_x(sn[i - 1], sn[i], STEP[s])
                if x is None or abs(x) < thr[s]:
                    continue
                last = i
                n_ev += 1
                direction = 1 if x > 0 else -1
                for m in MONEYNESS:
                    t = build_trade(sn, i, d, s, direction, m, "EVENT", x, is_exp)
                    if t:
                        trades.append(t)
            eligible = [i for i in range(1, len(sn) - 1) if sn[i].ts.time() >= time(14, 30)]
            for i in rng.sample(eligible, min(len(eligible), max(3 * n_ev, 6))):
                t = build_trade(sn, i, d, s, rng.choice([1, -1]), 0, "RANDOM", None, is_exp)
                if t:
                    trades.append(t)

    def sel(kind, split, m=0, mode=None, expiry=None):
        ds = set(train_days if split == "train" else test_days if split == "test" else days)
        return [t for t in trades if t.kind == kind and t.date in ds and t.moneyness == m
                and (mode is None or t.mode == mode) and (expiry is None or t.is_expiry == expiry)]

    out = dict(days=[str(d) for d in days], train_days=[str(d) for d in train_days],
               test_days=[str(d) for d in test_days], trigger_threshold={s: thr[s] for s in symbols},
               trigger_percentile=TRIGGER_PERCENTILE)

    # 2. holding duration / MFE / MAE by mode (events vs random), day-grouped
    hold = {}
    for split in ("train", "test"):
        for kind in ("EVENT", "RANDOM"):
            for mode in ("PRE", "MODE_A", "MODE_B"):
                rows = sel(kind, split, 0, mode)
                hold[f"{split}|{kind}|{mode}"] = {
                    h: dict(exit=summarize(list(day_mean(rows, lambda t, h=h: t.exit.get(h)).values())),
                            mfe=summarize(list(day_mean(rows, lambda t, h=h: t.mfe.get(h)).values())),
                            mae=summarize(list(day_mean(rows, lambda t, h=h: t.mae.get(h)).values())),
                            n_trades=len([t for t in rows if h in t.exit]))
                    for h in HOLDS}
    out["holding"] = hold
    out["t_mfe_min"] = {kind: summarize([t.t_mfe_min for t in sel(kind, "all") if t.t_mfe_min is not None])
                        for kind in ("EVENT", "RANDOM")}

    # 3. option selection (moneyness) on TRAIN, confirmed on TEST
    out["moneyness"] = {split: {m: dict(
        exit3=summarize([t.exit.get(3) for t in sel("EVENT", split, m)]),
        mfe3=summarize([t.mfe.get(3) for t in sel("EVENT", split, m)]),
        mae3=summarize([t.mae.get(3) for t in sel("EVENT", split, m)]),
        spread=summarize([t.entry_spread_pct for t in sel("EVENT", split, m)]),
        premium=summarize([t.entry_ask for t in sel("EVENT", split, m)]),
        response=summarize([t.response_pct for t in sel("EVENT", split, m)]),
        delta=summarize([abs(t.delta) for t in sel("EVENT", split, m) if t.delta is not None]))
        for m in MONEYNESS} for split in ("train", "test")}

    # 4. premium response vs outcome: tercile cut-offs from TRAIN
    tr_resp = [t.response_pct for t in sel("EVENT", "train") if t.response_pct is not None]
    cuts = (percentile(tr_resp, 33.3), percentile(tr_resp, 66.7)) if tr_resp else (None, None)
    resp = {}
    for split in ("train", "test"):
        rows = [t for t in sel("EVENT", split) if t.response_pct is not None]
        groups = {"low": [t for t in rows if t.response_pct < cuts[0]],
                  "mid": [t for t in rows if cuts[0] <= t.response_pct < cuts[1]],
                  "high": [t for t in rows if t.response_pct >= cuts[1]]}
        resp[split] = {g: dict(exit2=summarize([t.exit.get(2) for t in v]), mfe2=summarize([t.mfe.get(2) for t in v]),
                               mae2=summarize([t.mae.get(2) for t in v]), n=len(v)) for g, v in groups.items()}
    out["response"] = dict(cuts=cuts, by_split=resp)

    # 5. spread cost (entry spread; round trip ~= entry + exit spread)
    out["spread"] = {mode: summarize([t.entry_spread_pct for t in trades if t.mode == mode and abs(t.moneyness) <= 2])
                     for mode in ("PRE", "MODE_A", "MODE_B")}

    # 6. target/stop/max-hold grid: fit on TRAIN (day-mean of ATM events, MODE_A + PRE), read out on TEST
    fit_modes = ("PRE", "MODE_A")
    grid = []
    for tg in TARGETS:
        for sp in STOPS:
            for mh in MAX_HOLDS:
                def f(t, tg=tg, sp=sp, mh=mh):
                    return simulate_grid(t, tg, sp, mh)
                tr_ev = [t for t in sel("EVENT", "train") if t.mode in fit_modes]
                te_ev = [t for t in sel("EVENT", "test") if t.mode in fit_modes]
                tr_rd = [t for t in sel("RANDOM", "train") if t.mode in fit_modes]
                te_rd = [t for t in sel("RANDOM", "test") if t.mode in fit_modes]
                dm = lambda rows: list(day_mean(rows, f).values())
                grid.append(dict(target=tg, stop=sp, max_hold=mh,
                                 train_event=round(st.mean(dm(tr_ev)), 3) if dm(tr_ev) else None,
                                 train_random=round(st.mean(dm(tr_rd)), 3) if dm(tr_rd) else None,
                                 test_event=round(st.mean(dm(te_ev)), 3) if dm(te_ev) else None,
                                 test_random=round(st.mean(dm(te_rd)), 3) if dm(te_rd) else None,
                                 test_event_ci=bootstrap_ci(dm(te_ev)), test_random_ci=bootstrap_ci(dm(te_rd)),
                                 test_event_days=len(dm(te_ev))))
    valid = [g for g in grid if g["train_event"] is not None]
    best = max(valid, key=lambda g: (g["train_event"], -g["stop"])) if valid else None
    out["grid"] = grid
    out["grid_best_on_train"] = best

    # leave-one-day-out influence on the chosen cell's TEST event mean
    if best:
        f = lambda t: simulate_grid(t, best["target"], best["stop"], best["max_hold"])
        te = [t for t in sel("EVENT", "test") if t.mode in fit_modes]
        dm = day_mean(te, f)
        base = st.mean(dm.values()) if dm else None
        lodo = {f"{k[0]}|{k[1]}": round(st.mean([v for kk, v in dm.items() if kk != k]) - base, 3)
                for k in dm if len(dm) > 1}
        out["lodo_test_influence"] = dict(base=base, deltas=lodo,
                                          max_abs=max((abs(v) for v in lodo.values()), default=None))
        out["by_symbol_test"] = {s: summarize([f(t) for t in te if t.symbol == s]) for s in symbols}

    # 7. expiry-day behaviour: 3-min MAE by time bucket, ATM, events + random pooled
    def bucket(t: Trade) -> str:
        tt = t.ts.time()
        if tt < time(15, 0):
            return "14:30-15:00"
        if tt < time(15, 10):
            return "15:00-15:10"
        if tt < time(15, 15):
            return "15:10-15:15"
        return "15:15-15:30"
    exp = {}
    for flag in (True, False):
        for b in ("14:30-15:00", "15:00-15:10", "15:10-15:15", "15:15-15:30"):
            rows = [t for t in trades if t.moneyness == 0 and t.is_expiry == flag and bucket(t) == b]
            exp[f"{'expiry' if flag else 'non_expiry'}|{b}"] = dict(
                mae3=summarize([t.mae.get(3) for t in rows]), mfe3=summarize([t.mfe.get(3) for t in rows]),
                exit3=summarize([t.exit.get(3) for t in rows]),
                days=len({(t.date, t.symbol) for t in rows}))
    out["expiry"] = exp
    out["n_trades"] = {kind: len([t for t in trades if t.kind == kind and t.moneyness == 0]) for kind in ("EVENT", "RANDOM")}
    return out
