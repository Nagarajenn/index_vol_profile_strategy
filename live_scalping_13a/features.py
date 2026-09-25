"""Everything the gates are allowed to look at, measured at the signal minute.

Strictly causal: every value comes from `series[m]` for m <= `minute`. Nothing here reads a
later minute, and `replay.leakage_audit` proves it by recomputing from truncated inputs.

13A deliberately builds its own feature row rather than importing 12E's, so the live decision
path does not depend on a research package. It shares only the primitive option-chain readers
in option_risk_12b, which every milestone uses.
"""

from option_risk_12b.option_snapshot import shift
from option_risk_12b.option_state import leg
from live_scalping_13a.config import DEFAULT


def _pct(now, then):
    if now is None or then in (None, 0):
        return None
    return (now - then) / abs(then) * 100


def spot_at(series, m):
    s = series.get(m)
    return s.get("spot") if s else None


def quote(series, minute, side, strike) -> dict:
    """The full executable picture for one leg. Missing values stay missing."""
    if strike is None or minute not in series:
        return dict(ok=False, bid=None, ask=None, ltp=None, mid=None, spread=None, spread_pct=None,
                    delta=None, iv=None, theta=None, gamma=None, vega=None, volume=None, oi=None,
                    bid_qty=None, ask_qty=None, greeks_status=None)
    q = leg(series, minute, side, strike) or {}
    bid, ask = q.get("bid"), q.get("ask")
    return dict(ok=bid is not None and ask is not None, bid=bid, ask=ask, ltp=q.get("ltp"),
                mid=q.get("mid"), spread=(ask - bid) if (bid is not None and ask is not None) else None,
                spread_pct=q.get("spread_pct"), delta=q.get("delta"), iv=q.get("iv"),
                theta=q.get("theta"), gamma=q.get("gamma"), vega=q.get("vega"),
                volume=q.get("volume"), oi=q.get("oi"), bid_qty=q.get("bid_qty"),
                ask_qty=q.get("ask_qty"), greeks_status=q.get("greeks_status"))


def premium_range_position(series, minute, side, strike, window=10) -> float | None:
    """Where the premium sits inside its own recent range, 0-100. Used by the timing gate."""
    if strike is None:
        return None
    vals = []
    for k in range(window + 1):
        s = series.get(shift(minute, -k))
        if not s:
            continue
        lgx = (s.get("legs") or {}).get((side, strike))
        if lgx and lgx.get("mid") is not None:
            vals.append(lgx["mid"])
    if len(vals) < 3:
        return None
    now, hi, lo = vals[0], max(vals), min(vals)
    return round((now - lo) / (hi - lo) * 100, 1) if hi > lo else None


def build(series: dict, minute: str, side: str, strike: float | None, cfg=DEFAULT) -> dict:
    """The complete causal feature row for one candidate."""
    g = cfg.gates
    other = "PE" if side == "CE" else "CE"
    spot = spot_at(series, minute)
    own, opp = quote(series, minute, side, strike), quote(series, minute, other, strike)

    f = dict(minute=minute, side=side, strike=strike, underlying=spot,
             expiry=str(series[minute].get("expiry")) if minute in series else None,
             bid=own["bid"], ask=own["ask"], ltp=own["ltp"], mid=own["mid"],
             spread=own["spread"], spread_pct=own["spread_pct"],
             bid_qty=own["bid_qty"], ask_qty=own["ask_qty"],
             delta=own["delta"], iv=own["iv"], theta=own["theta"], gamma=own["gamma"],
             vega=own["vega"], volume=own["volume"], oi=own["oi"],
             greeks_status=own["greeks_status"], quote_ok=own["ok"],
             other_mid=opp["mid"], other_iv=opp["iv"])

    # ---- underlying, backwards only ------------------------------------------------------
    for k in (1, 3, 5):
        f[f"und_pre_{k}m"] = _pct(spot, spot_at(series, shift(minute, -k)))
        f[f"opt_pre_{k}m"] = _pct(own["mid"], quote(series, shift(minute, -k), side, strike)["mid"])
        f[f"other_pre_{k}m"] = _pct(opp["mid"], quote(series, shift(minute, -k), other, strike)["mid"])

    # momentum and acceleration of the underlying itself
    u1, u3 = f["und_pre_1m"], f["und_pre_3m"]
    f["und_momentum"] = u3
    f["und_acceleration"] = (u1 - (u3 - u1) / 2) if (u1 is not None and u3 is not None) else None

    # ---- regime, from the underlying only ---------------------------------------------------
    back = spot_at(series, shift(minute, -g.regime_lookback_min))
    f["regime_lookback_pct"] = _pct(spot, back)
    f["regime_recent_pct"] = _pct(spot, spot_at(series, shift(minute, -3)))

    # ---- distance from the recent local extreme (timing) --------------------------------------
    spots = [spot_at(series, shift(minute, -k)) for k in range(0, 16)]
    spots = [s for s in spots if s is not None]
    if len(spots) >= 5 and spot:
        f["dist_from_local_high_pct"] = (spot - max(spots)) / max(spots) * 100
        f["dist_from_local_low_pct"] = (spot - min(spots)) / min(spots) * 100
    else:
        f["dist_from_local_high_pct"] = f["dist_from_local_low_pct"] = None
    f["premium_range_position"] = premium_range_position(series, minute, side, strike)

    # ---- participation: this minute's traded volume vs its own trailing average -----------------
    trail = []
    for k in range(1, 6):
        a = quote(series, shift(minute, -k + 1), side, strike)["volume"]
        b = quote(series, shift(minute, -k), side, strike)["volume"]
        if a is not None and b is not None and a - b >= 0:
            trail.append(a - b)
    prev = quote(series, shift(minute, -1), side, strike)["volume"]
    this = own["volume"]
    delta_v = (this - prev) if (this is not None and prev is not None and this - prev >= 0) else None
    base = (sum(trail) / len(trail)) if trail else None
    f["volume_delta"] = delta_v
    f["volume_ratio"] = (delta_v / base) if (delta_v is not None and base) else None

    # ---- open interest, read with premium ------------------------------------------------------------
    oi3 = quote(series, shift(minute, -3), side, strike)["oi"]
    f["oi_pct_3m"] = _pct(own["oi"], oi3)
    return f
