"""Interpretable, decomposable option pressure metrics (neutral names; no "smart money").

Each side's pressure is the MEAN of the components that are available, each bounded
to [-1, 1] by tanh(x / scale). Positive = that side's options are strengthening.
Every component is returned with its raw input so the score can be taken apart.

No hard-coded winner:
* OI is never read alone -- it is only interpreted together with the premium move
  of the same side (build-up / covering / unwinding conventions);
* IV is reported, never used as directional evidence;
* volume acceleration is signed by the premium move it accompanies (volume on its own
  has no direction).
"""

import math

from option_risk_12b.option_snapshot import offset_strike, shift, strike_window
from option_risk_12b.option_state import diff, leg, pct


def _t(x, scale):
    return None if x is None else math.tanh(x / scale)


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def side_premium_pct(series, minute, typ, strikes, h):
    ch = []
    for k in strikes:
        a, b = leg(series, minute, typ, k), leg(series, shift(minute, -h), typ, k)
        if a and b:
            ch.append(pct(a["mid"], b["mid"]))
    return _mean(ch)


def side_sum(series, minute, typ, strikes, field):
    s = series.get(minute)
    if not s:
        return None
    xs = [s["legs"].get((typ, k)) for k in strikes]
    xs = [q[field] for q in xs if q and q[field] is not None]
    return sum(xs) if xs else None


def side_flow(series, minute, typ, strikes):
    return diff(side_sum(series, minute, typ, strikes, "volume"), side_sum(series, shift(minute, -1), typ, strikes, "volume"))


def oi_price_state(oi_pct, prem_pct, oi_flat=0.1, prem_flat=0.5):
    """Conditional OI reading (never OI alone). Returns (label, signed value in [-1, 1])."""
    if oi_pct is None or prem_pct is None:
        return "INSUFFICIENT_DATA", None
    if abs(oi_pct) < oi_flat or abs(prem_pct) < prem_flat:
        return "NO_CLEAR_OI_PRICE_RELATION", 0.0
    mag = math.tanh(abs(oi_pct) / 0.5)
    if oi_pct > 0 and prem_pct > 0:
        return "LONG_BUILDUP", mag
    if oi_pct < 0 and prem_pct > 0:
        return "SHORT_COVERING", 0.5 * mag
    if oi_pct > 0 and prem_pct < 0:
        return "SHORT_BUILDUP", -mag
    return "LONG_UNWINDING", -0.5 * mag


def side_pressure(series, minute, typ, atm, cfg) -> dict:
    s = series.get(minute)
    if not s or atm is None:
        return dict(pressure=None, components={}, status="MISSING")
    near = [k for k in (offset_strike(s, atm, o) for o in (-1, 0, 1)) if k is not None]
    band = strike_window(s, atm, cfg.display_strikes_each_side)
    prem3 = side_premium_pct(series, minute, typ, near, 3)
    comp = {}
    comp["premium"] = dict(raw_pct_3m=prem3, value=_t(prem3, cfg.scale_premium_pct))
    f_now = side_flow(series, minute, typ, band)
    trail = [side_flow(series, shift(minute, -k), typ, band) for k in range(1, 6)]
    trail = [x for x in trail if x is not None]
    base = (sum(trail) / len(trail)) if trail else None
    accel = (f_now / base - 1) if (f_now is not None and base) else None
    sgn = 0 if (prem3 is None or abs(prem3) < cfg.flat_pct["premium"]) else (1 if prem3 > 0 else -1)
    comp["volume_acceleration"] = dict(raw_ratio_minus_1=accel, premium_sign=sgn,
                                       value=(_t(accel, cfg.scale_volume_accel) * sgn) if accel is not None else None)
    oi_now, oi_3 = side_sum(series, minute, typ, band, "oi"), side_sum(series, shift(minute, -3), typ, band, "oi")
    oi_pct = pct(oi_now, oi_3)
    lab, v = oi_price_state(oi_pct, prem3, cfg.flat_pct["oi"], cfg.flat_pct["premium"])
    comp["oi_price"] = dict(raw_oi_pct_3m=oi_pct, relation=lab, value=v)
    bq, aq = side_sum(series, minute, typ, band, "bid_qty"), side_sum(series, minute, typ, band, "ask_qty")
    imb = (bq - aq) / (bq + aq) if (bq is not None and aq is not None and (bq + aq) > 0) else None
    comp["bid_ask_imbalance"] = dict(raw=imb, value=imb)
    d_now, d_3 = leg(series, minute, typ, atm), leg(series, shift(minute, -3), typ, atm)
    dchg = diff(d_now["delta"] if d_now else None, d_3["delta"] if d_3 else None)
    if dchg is not None and typ == "PE":
        dchg = -dchg                      # a put strengthens when its (negative) delta falls further
    comp["delta_change"] = dict(raw_3m=dchg, value=_t(dchg, cfg.scale_delta_change))
    p = _mean([c["value"] for c in comp.values()])
    return dict(pressure=p, components=comp, status="OK" if p is not None else "INSUFFICIENT_DATA")


def directional_pressure(series, minute, atm, cfg) -> dict:
    ce = side_pressure(series, minute, "CE", atm, cfg)
    pe = side_pressure(series, minute, "PE", atm, cfg)
    s = series.get(minute)
    near = [k for k in (offset_strike(s, atm, o) for o in (-1, 0, 1)) if k is not None] if (s and atm is not None) else []
    ce3, pe3 = side_premium_pct(series, minute, "CE", near, 3), side_premium_pct(series, minute, "PE", near, 3)
    rel = diff(ce3, pe3)
    crs = _t(rel, cfg.scale_rel_strength_pct)
    parts = [ce["pressure"], -pe["pressure"] if pe["pressure"] is not None else None, crs]
    odp = _mean(parts)
    thr = cfg.directional_threshold
    if odp is None:
        lab = "INSUFFICIENT_DATA"
    elif (ce["pressure"] or 0) >= thr and (pe["pressure"] or 0) >= thr:
        lab = "MIXED"                     # both sides strengthening (e.g. premium / IV expansion)
    elif (ce["pressure"] or 0) <= -thr and (pe["pressure"] or 0) <= -thr:
        lab = "MIXED"                     # both sides weakening (e.g. decay)
    elif odp >= thr:
        lab = "UP"
    elif odp <= -thr:
        lab = "DOWN"
    else:
        lab = "NEUTRAL"
    up, down = [], []
    if ce3 is not None:
        (up if ce3 > 0 else down).append(f"CE premium {ce3:+.2f}% over 3m (ATM+/-1)")
    if pe3 is not None:
        (down if pe3 > 0 else up).append(f"PE premium {pe3:+.2f}% over 3m (ATM+/-1)")
    for side, sp in (("CE", ce), ("PE", pe)):
        c = sp["components"]
        va = c.get("volume_acceleration", {}).get("value")
        if va:
            ((up if (va > 0) == (side == "CE") else down)).append(f"{side} volume acceleration signed {va:+.2f}")
        rel_lab = c.get("oi_price", {}).get("relation")
        if rel_lab in ("LONG_BUILDUP", "SHORT_COVERING", "SHORT_BUILDUP", "LONG_UNWINDING"):
            strengthening = rel_lab in ("LONG_BUILDUP", "SHORT_COVERING")
            ((up if strengthening == (side == "CE") else down)).append(f"{side} OI/premium: {rel_lab}")
        imb = c.get("bid_ask_imbalance", {}).get("value")
        if imb is not None and abs(imb) >= 0.2:
            ((up if (imb > 0) == (side == "CE") else down)).append(f"{side} bid/ask quantity imbalance {imb:+.2f}")
    return dict(CE_PRESSURE=ce["pressure"], PE_PRESSURE=pe["pressure"], CALL_RELATIVE_STRENGTH=crs,
                PUT_RELATIVE_STRENGTH=-crs if crs is not None else None, OPTION_DIRECTIONAL_PRESSURE=odp,
                label=lab, ce_components=ce["components"], pe_components=pe["components"],
                ce_premium_pct_3m=ce3, pe_premium_pct_3m=pe3, up_evidence=up, down_evidence=down)
