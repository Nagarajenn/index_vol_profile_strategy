"""ADVISORY position-risk monitor for an open (paper) long-option position.

This is NOT the 11D risk engine and never closes anything. The 11D exit engine
remains authoritative. Negative signals are grouped into INDEPENDENT evidence families
(config.families); the number of families -- not the number of correlated signals --
maps to POSITION_SUPPORT / RISK state / RISK_ACTION, always with explicit reasons.

For BUY CE the "own" leg is the held CE and the "opposite" leg is the PE at the same
strike; for BUY PE the roles are reversed. Nothing assumes CE = bullish by rule --
support is always judged relative to the leg actually held.
"""

import math

from option_risk_12b.closing_state import LIVE
from option_risk_12b.option_pressure import oi_price_state, side_flow
from option_risk_12b.option_snapshot import shift
from option_risk_12b.option_state import diff, leg, pct

SUPPORT = ("STRONG", "NORMAL", "WEAK", "CONTRADICTED", "UNKNOWN")
RISK = ("LOW", "NORMAL", "ELEVATED", "HIGH", "EXTREME")
ACTION = ("HOLD", "CAUTION", "PREPARE_EXIT", "BREAK_EXIT")


def _chg(series, minute, typ, k, h, field="mid", kind="pct"):
    a, b = leg(series, minute, typ, k), leg(series, shift(minute, -h), typ, k)
    if not a or not b:
        return None
    return pct(a[field], b[field]) if kind == "pct" else diff(a[field], b[field])


def _flow_ratio(series, minute, typ, k):
    f = side_flow(series, minute, typ, [k])
    trail = [side_flow(series, shift(minute, -j), typ, [k]) for j in range(1, 6)]
    trail = [x for x in trail if x is not None]
    base = sum(trail) / len(trail) if trail else None
    return (f / base) if (f is not None and base) else None


def assess(series: dict, minute: str, position: dict, und: dict, cfg, entry_spread_pct=None) -> dict:
    own_t = position["option_type"]
    opp_t = "PE" if own_t == "CE" else "CE"
    k = position["strike"]
    own, opp = leg(series, minute, own_t, k), leg(series, minute, opp_t, k)
    neg, pos, reasons, ctx = [], [], [], []
    if own is None or own["mid"] is None:
        why = "held option has no two-sided quote this minute" if own else "no option snapshot for the held contract this minute"
        return dict(minute=minute, position_support="UNKNOWN", risk_state="EXTREME", risk_action="PREPARE_EXIT",
                    negative=["DATA_UNRELIABLE"], positive=[], n_negative=1, n_positive=0, negative_families=["DATA"],
                    reasons=[f"DATA_UNRELIABLE: {why} -- support cannot be verified (action capped at PREPARE_EXIT)"],
                    own_mid=None, advisory_only=True)
    o2 = _chg(series, minute, own_t, k, 2)
    p2 = _chg(series, minute, opp_t, k, 2)
    o1, o1p = _chg(series, minute, own_t, k, 1), _chg(series, shift(minute, -1), own_t, k, 1)
    if o2 is None:
        return dict(minute=minute, position_support="UNKNOWN", risk_state="NORMAL", risk_action="HOLD", negative=[], positive=[],
                    n_negative=0, n_positive=0, reasons=["INSUFFICIENT_HISTORY: fewer than 2 prior minutes for the held contract"],
                    own_mid=own["mid"], advisory_only=True)

    def add(lst, code, text):
        lst.append(code)
        reasons.append(f"{code}: {text}")

    if o2 <= cfg.adverse_premium_pct:
        add(neg, "OWN_PREMIUM_FALLING", f"{own_t} premium {o2:+.2f}% over 2 minutes")
    elif o2 >= cfg.favourable_premium_pct:
        add(pos, "OWN_PREMIUM_RISING", f"{own_t} premium {o2:+.2f}% over 2 minutes")
    if p2 is not None and p2 >= cfg.opposite_rise_pct:
        add(neg, "OPPOSITE_PREMIUM_RISING", f"{opp_t} premium {p2:+.2f}% over 2 minutes")
    elif p2 is not None and p2 <= -cfg.opposite_rise_pct:
        add(pos, "OPPOSITE_PREMIUM_FALLING", f"{opp_t} premium {p2:+.2f}% over 2 minutes")
    if o1 is not None and o1p is not None and o1 < 0 and (o1 - o1p) <= -cfg.accel_min_pct:
        add(neg, "OWN_ACCELERATION_NEGATIVE", f"{own_t} 1m change {o1:+.2f}% after {o1p:+.2f}%")
    b2 = _chg(series, minute, own_t, k, 2, "bid", "pts")
    bq2 = _chg(series, minute, own_t, k, 2, "bid_qty", "pct")
    if b2 is not None and bq2 is not None and b2 < 0 and bq2 < 0:
        add(neg, "OWN_BID_WEAKENING", f"{own_t} bid {b2:+.2f} pts and bid quantity {bq2:+.0f}% over 2 minutes")
    sp = own["spread_pct"]
    liquidity_break = sp is not None and sp >= 2 * cfg.wide_spread_pct
    if sp is not None and (sp >= cfg.wide_spread_pct or (entry_spread_pct and sp >= cfg.spread_expansion_ratio * entry_spread_pct)):
        add(neg, "OWN_SPREAD_EXPANDING", f"{own_t} spread {sp:.2f}%" + (f" vs {entry_spread_pct:.2f}% at entry" if entry_spread_pct else ""))
    fr_own, fr_opp = _flow_ratio(series, minute, own_t, k), _flow_ratio(series, minute, opp_t, k)
    if fr_own is not None and fr_own < 0.67 and o2 <= 0:
        add(neg, "OWN_VOLUME_WEAKENING", f"{own_t} 1m volume {fr_own:.2f}x its 5m average while premium not rising")
    elif fr_own is not None and fr_own >= 1.5 and o2 > 0:
        add(pos, "OWN_VOLUME_ACCELERATING", f"{own_t} 1m volume {fr_own:.2f}x its 5m average with premium rising")
    if fr_opp is not None and fr_opp >= 1.5 and (p2 or 0) > 0:
        add(neg, "OPPOSITE_VOLUME_ACCELERATING", f"{opp_t} 1m volume {fr_opp:.2f}x its 5m average with premium rising")
    if p2 is not None:
        rs = math.tanh((o2 - p2) / cfg.scale_rel_strength_pct)
        if rs <= -cfg.directional_threshold:
            add(neg, "RELATIVE_STRENGTH_AGAINST", f"{own_t} minus {opp_t} premium change {o2 - p2:+.2f} pct-pts over 2 minutes")
        elif rs >= cfg.directional_threshold:
            add(pos, "RELATIVE_STRENGTH_FOR", f"{own_t} minus {opp_t} premium change {o2 - p2:+.2f} pct-pts over 2 minutes")
    iv2 = _chg(series, minute, own_t, k, 2, "iv", "pts")
    if iv2 is not None and iv2 <= cfg.iv_collapse_pts and o2 < 0:
        add(neg, "IV_COLLAPSE_WITH_WEAK_PREMIUM", f"{own_t} IV {iv2:+.2f} pts while premium {o2:+.2f}%")
    oi3, pr3 = _chg(series, minute, own_t, k, 3, "oi"), _chg(series, minute, own_t, k, 3)
    rel, _ = oi_price_state(oi3, pr3, cfg.flat_pct["oi"], cfg.flat_pct["premium"])
    if rel in ("SHORT_BUILDUP", "LONG_UNWINDING"):
        add(neg, "OWN_OI_PRICE_ADVERSE", f"{own_t} OI {oi3:+.2f}% with premium {pr3:+.2f}% over 3m ({rel})")
    elif rel in ("LONG_BUILDUP", "SHORT_COVERING"):
        add(pos, "OWN_OI_PRICE_SUPPORTIVE", f"{own_t} OI {oi3:+.2f}% with premium {pr3:+.2f}% over 3m ({rel})")
    st2 = None
    if opp and opp["mid"]:
        po, pp = leg(series, shift(minute, -2), own_t, k), leg(series, shift(minute, -2), opp_t, k)
        if po and pp and po["mid"] and pp["mid"]:
            st2 = pct(own["mid"] + opp["mid"], po["mid"] + pp["mid"])
    if st2 is not None and st2 <= -cfg.flat_pct["straddle"] and o2 < 0:
        add(neg, "STRADDLE_CONTRADICTS", f"straddle {st2:+.2f}% over 2m while {own_t} premium falls (decay dominating)")
    if und.get("state") != LIVE:
        ctx.append(f"CONTEXT: underlying reference {und.get('state')} (age {und.get('age_minutes')} min) -- "
                   "the option chain is the available live evidence")

    n_neg, n_pos = len(neg), len(pos)
    fam = sorted({f for f, codes in cfg.families.items() if any(c in neg for c in codes)})
    core = [f for f in fam if f in cfg.core_families]
    nf = len(fam)
    if nf >= cfg.high_min_families and core and nf > n_pos:
        support = "CONTRADICTED"
    elif (nf >= 2 and nf > n_pos) or (core and n_pos == 0):
        support = "WEAK"
    elif n_pos >= cfg.strong_min_positive and n_neg == 0:
        support = "STRONG"
    else:
        support = "NORMAL"
    if ((nf >= cfg.extreme_min_families and len(core) == len(cfg.core_families))
            or (liquidity_break and nf >= cfg.high_min_families and core)):
        risk = "EXTREME"
    elif nf >= cfg.high_min_families and core:
        risk = "HIGH"
    elif len(core) >= cfg.elevated_min_families or nf >= 2:
        risk = "ELEVATED"
    elif support == "STRONG":
        risk = "LOW"
    else:
        risk = "NORMAL"
    if risk == "LOW" and und.get("state") != LIVE:
        risk = "NORMAL"
        ctx.append("CONTEXT: LOW risk not assigned because the underlying cannot confirm the option evidence")
    action = {"LOW": "HOLD", "NORMAL": "HOLD", "ELEVATED": "CAUTION", "HIGH": "PREPARE_EXIT", "EXTREME": "BREAK_EXIT"}[risk]
    return dict(minute=minute, position_support=support, risk_state=risk, risk_action=action, negative=neg, positive=pos,
                reasons=reasons + ctx, n_negative=n_neg, n_positive=n_pos, negative_families=fam, own_mid=own["mid"], own_premium_pct_2m=o2,
                opposite_premium_pct_2m=p2, own_spread_pct=sp, advisory_only=True)
