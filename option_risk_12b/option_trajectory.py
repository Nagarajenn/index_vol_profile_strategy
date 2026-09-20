"""1m / 3m / 5m trajectories and acceleration for option metrics (same contract / same
strike across time). Label vocabulary: RISING FALLING ACCELERATING DECELERATING FLAT
INSUFFICIENT_DATA. A label is a description of the past, not a forecast."""

from option_risk_12b.option_snapshot import shift
from option_risk_12b.option_state import diff, leg, pct, val

INSUFFICIENT = "INSUFFICIENT_DATA"


def label(ch1, ch3, ch1_prev, flat: float, accel_min: float) -> str:
    if ch3 is None:
        return INSUFFICIENT
    if abs(ch3) < flat:
        return "FLAT"
    direction = 1 if ch3 > 0 else -1
    if ch1 is not None and ch1_prev is not None:
        acc = ch1 - ch1_prev
        if abs(acc) >= accel_min and ch1 * direction > 0:
            return "ACCELERATING" if acc * direction > 0 else "DECELERATING"
    return "RISING" if direction > 0 else "FALLING"


def _metric_fn(series, typ, strike, field):
    def f(m):
        if field == "flow":
            return diff(val(series, m, typ, strike, "volume"), val(series, shift(m, -1), typ, strike, "volume"))
        return val(series, m, typ, strike, field)
    return f


def straddle_fn(series, strike):
    def f(m):
        ce, pe = leg(series, m, "CE", strike), leg(series, m, "PE", strike)
        return ce["mid"] + pe["mid"] if (ce and pe and ce["mid"] and pe["mid"]) else None
    return f


def pcr_fn(series, strikes):
    def f(m):
        s = series.get(m)
        if not s or not strikes:
            return None
        ce = [s["legs"].get(("CE", k)) for k in strikes]
        pe = [s["legs"].get(("PE", k)) for k in strikes]
        co = sum(q["oi"] for q in ce if q and q["oi"] is not None)
        po = sum(q["oi"] for q in pe if q and q["oi"] is not None)
        return po / co if co else None
    return f


def trajectory(fn, minute: str, kind: str, flat: float, accel_min: float, horizons=(1, 3, 5)) -> dict:
    """kind 'pct' (relative %) or 'pts' (absolute points, e.g. IV)."""
    now = fn(minute)
    ch = {}
    for h in horizons:
        past = fn(shift(minute, -h))
        ch[h] = pct(now, past) if kind == "pct" else diff(now, past)
    prev1 = None
    a, b = fn(shift(minute, -1)), fn(shift(minute, -2))
    prev1 = pct(a, b) if kind == "pct" else diff(a, b)
    acc = diff(ch.get(1), prev1)
    return dict(value=now, **{f"chg_{h}m": ch[h] for h in horizons}, acceleration=acc,
                label=label(ch.get(1), ch.get(3), prev1, flat, accel_min))


def leg_trajectories(series, minute, strike, cfg) -> dict:
    f = cfg.flat_pct
    out = {}
    for typ in ("CE", "PE"):
        t = typ.lower()
        out[f"{t}_premium"] = trajectory(_metric_fn(series, typ, strike, "mid"), minute, "pct", f["premium"], cfg.accel_min_pct, cfg.horizons_min)
        out[f"{t}_volume"] = trajectory(_metric_fn(series, typ, strike, "flow"), minute, "pct", f["volume"], 10 * cfg.accel_min_pct, cfg.horizons_min)
        out[f"{t}_oi"] = trajectory(_metric_fn(series, typ, strike, "oi"), minute, "pct", f["oi"], 0.05, cfg.horizons_min)
        out[f"{t}_iv"] = trajectory(_metric_fn(series, typ, strike, "iv"), minute, "pts", f["iv"], 0.2, cfg.horizons_min)
    out["straddle"] = trajectory(straddle_fn(series, strike), minute, "pct", f["straddle"], cfg.accel_min_pct, cfg.horizons_min)
    return out
