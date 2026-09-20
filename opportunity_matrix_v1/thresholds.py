"""Chronological validation utilities (Step 11): prior-day-only percentile thresholds and
the expanding walk-forward split. Every threshold object records the days it came from;
the leakage audit asserts they are all strictly earlier than the target day."""

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

from config.settings import IST
from opportunity_matrix_v1 import features as F


def percentile(sorted_vals: list, p: float):
    if not sorted_vals:
        return None
    pos = (len(sorted_vals) - 1) * p / 100.0
    lo = int(pos)
    hi = min(lo + 1, len(sorted_vals) - 1)
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (pos - lo)


@dataclass
class Dist:
    values: list
    def p(self, q):
        return percentile(self.values, q)

    def rank(self, v):
        if v is None or not self.values:
            return None
        lo, hi = 0, len(self.values)
        while lo < hi:
            m = (lo + hi) // 2
            if self.values[m] < v:
                lo = m + 1
            else:
                hi = m
        return 100.0 * lo / len(self.values)

    def bucket(self, v, pcts):
        """Largest descriptor percentile that |v| reaches (e.g. 'p90'), or '<p50'."""
        if v is None:
            return None
        hit = [q for q in pcts if self.p(q) is not None and abs(v) >= self.p(q)]
        return f"p{int(max(hit))}" if hit else f"<p{int(min(pcts))}"


@dataclass
class Thresholds:
    target_day: date
    source_days: tuple
    dists: dict = field(default_factory=dict)

    def __getitem__(self, k) -> Dist:
        return self.dists[k]


def hr_thresholds(target: date, prior_days: list, cfg) -> Thresholds | None:
    """prior_days: DayData for ONE symbol on HR days strictly before target."""
    prior = [d for d in prior_days if d.trade_date < target]
    if len(prior) < cfg.min_prior_hr_days:
        return None
    opt_src = [d for d in prior if not d.is_expiry] or prior
    acc = {k: [] for k in ("d1", "r10", "r15", "r30", "r60", "r300", "o5", "o10", "syn10", "implied10", "gap")}
    for d in prior:
        for i in range(len(d)):
            for k, lag in (("d1", 1), ("r10", 2), ("r15", 3), ("r30", 6), ("r60", 12), ("r300", 60)):
                v = F.fmove(d, i, lag)
                if v is not None:
                    acc[k].append(abs(v))
            if d.times[i].time() >= time(15, 15):
                t0, t2 = d.trans[i], d.trans[i - 2] if i >= 2 else None
                if t0 and t2 and t0.get("implied_spot") and t2.get("implied_spot"):
                    acc["implied10"].append(abs(t0["implied_spot"] - t2["implied_spot"]))
                if t0 and t0.get("implied_spot") and d.fut_mid[i]:
                    acc["gap"].append(abs(t0["implied_spot"] - d.fut_mid[i]))
    for d in opt_src:
        for i in range(len(d)):
            ce5, pe5 = F.oret(d, ("CE", 0), i, 1), F.oret(d, ("PE", 0), i, 1)
            ce10, pe10 = F.oret(d, ("CE", 0), i, 2), F.oret(d, ("PE", 0), i, 2)
            acc["o5"] += [abs(x) for x in (ce5, pe5) if x is not None]
            acc["o10"] += [abs(x) for x in (ce10, pe10) if x is not None]
            if ce10 is not None and pe10 is not None:
                acc["syn10"].append(abs(ce10 - pe10))
    return Thresholds(target, tuple(sorted(d.trade_date for d in prior)), {k: Dist(sorted(v)) for k, v in acc.items()})


def minute_thresholds(target: date, prior_candles: dict, bin_size: float, cfg) -> Thresholds:
    """prior_candles: {date: 1-min candles DataFrame} for trading days strictly before target."""
    acc = {k: [] for k in ("dist_vwap_atr", "velocity", "range15", "volume_accel", "ret5")}
    rv = {}
    days = sorted(d for d in prior_candles if d < target)
    for d in days:
        c = prior_candles[d]
        for m in range(0, 30):
            T = datetime.combine(d, time(14, 30), tzinfo=IST) + timedelta(minutes=m)
            f = F.minute_features(c, T, bin_size, cfg)
            if f.get("data_quality") != "GOOD":
                continue
            for k, src in (("dist_vwap_atr", "dist_vwap_atr"), ("velocity", "velocity"), ("range15", "range15"), ("volume_accel", "volume_accel")):
                if f.get(src) is not None:
                    acc[k].append(abs(f[src]) if k != "range15" and k != "volume_accel" else f[src])
            if f.get("velocity") is not None:
                acc["ret5"].append(abs(f["velocity"]) / f["price"] * 100)
            rv.setdefault(T.time(), []).append(f["volume15"])
    th = Thresholds(target, tuple(days), {k: Dist(sorted(v)) for k, v in acc.items()})
    th.rvol_baseline = {t: sum(v) / len(v) for t, v in rv.items() if v}
    return th


def day_roles(hr_days: list, cfg) -> dict:
    """Expanding walk-forward roles. Seed days only build thresholds; they are never
    reported as out-of-sample. Evaluable days are split chronologically, never shuffled."""
    days = sorted(hr_days)
    roles = {d: "SEED" for d in days[:cfg.min_prior_hr_days]}
    ev = days[cfg.min_prior_hr_days:]
    n = len(ev)
    if n == 0:
        return roles
    if n < 3:
        for k, d in enumerate(ev):
            roles[d] = ["TRAIN", "VALIDATION"][min(k, 1)]
        return roles
    n_tr = max(1, round(n * cfg.split_fractions[0]))
    n_va = max(1, round(n * cfg.split_fractions[1]))
    for k, d in enumerate(ev):
        roles[d] = "TRAIN" if k < n_tr else ("VALIDATION" if k < n_tr + n_va else "UNSEEN")
    return roles
