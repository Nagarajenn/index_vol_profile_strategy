"""Parse existing 1-minute option_chain_raw payloads into per-minute leg records.

No interpolation, no forward-fill. A minute without a snapshot is simply absent
from the series and reported as MISSING by the callers. Greeks that are missing,
zero or degenerate are marked, never repaired or replaced by zero.
"""

from datetime import date, datetime, time

GREEK_KEYS = ("delta", "gamma", "theta", "vega")


def minute_key(ts: datetime) -> str:
    return ts.strftime("%H:%M")


def _num(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v


def parse_leg(raw: dict | None) -> dict | None:
    if not raw:
        return None
    bid, ask = _num(raw.get("top_bid_price")), _num(raw.get("top_ask_price"))
    two_sided = bid is not None and ask is not None and bid > 0 and ask > 0 and ask >= bid
    mid = (bid + ask) / 2 if two_sided else None
    g = raw.get("greeks") or {}
    greeks = {k: _num(g.get(k)) for k in GREEK_KEYS}
    iv = _num(raw.get("implied_volatility"))
    if not g or all(v is None for v in greeks.values()):
        gstatus = "UNAVAILABLE"
    elif iv is None or iv <= 0 or greeks["delta"] in (None, 0.0) or any(v is None for v in greeks.values()):
        gstatus = "INVALID"          # e.g. deep ITM puts published with zero IV / greeks -- not repaired
    else:
        gstatus = "VALID"
    valid = gstatus == "VALID"
    return dict(ltp=_num(raw.get("last_price")), bid=bid if two_sided else None, ask=ask if two_sided else None, mid=mid,
                spread=(ask - bid) if two_sided else None, spread_pct=((ask - bid) / mid * 100) if mid else None,
                bid_qty=_num(raw.get("top_bid_quantity")), ask_qty=_num(raw.get("top_ask_quantity")),
                volume=_num(raw.get("volume")), oi=_num(raw.get("oi")), iv=iv if valid else None, iv_raw=iv,
                delta=greeks["delta"] if valid else None, gamma=greeks["gamma"] if valid else None,
                theta=greeks["theta"] if valid else None, vega=greeks["vega"] if valid else None,
                greeks_status=gstatus)


def parse_snapshot(fetched_at: datetime, spot, expiry, payload: dict) -> dict:
    """payload = option_chain_raw.raw_payload ({'oc': {strike: {'ce':..,'pe':..}}, 'last_price', 'expiry'})."""
    oc = (payload or {}).get("oc") or {}
    legs = {}
    for k, v in oc.items():
        s = _num(k)
        if s is None:
            continue
        legs[("CE", s)] = parse_leg((v or {}).get("ce"))
        legs[("PE", s)] = parse_leg((v or {}).get("pe"))
    if isinstance(expiry, str):
        expiry = date.fromisoformat(expiry)
    return dict(fetched_at=fetched_at, minute=minute_key(fetched_at), spot=_num(spot if spot is not None else (payload or {}).get("last_price")),
                expiry=expiry, strikes=sorted({s for _, s in legs}), legs=legs)


def minute_series(snapshots: list[dict]) -> dict[str, dict]:
    """{HH:MM: parsed snapshot}; when several snapshots fall in one minute the LAST one
    (latest information available within that minute) is kept."""
    out = {}
    for s in sorted(snapshots, key=lambda x: x["fetched_at"]):
        out[s["minute"]] = s
    return out


def minute_range(start: str, end: str) -> list[str]:
    h, m = map(int, start.split(":"))
    eh, em = map(int, end.split(":"))
    out = []
    while (h, m) <= (eh, em):
        out.append(f"{h:02d}:{m:02d}")
        m += 1
        if m == 60:
            h, m = h + 1, 0
    return out


def shift(minute: str, delta: int) -> str:
    h, m = map(int, minute.split(":"))
    t = h * 60 + m + delta
    return f"{t // 60:02d}:{t % 60:02d}"


def resolve_atm(snap: dict) -> tuple[float | None, str]:
    """ATM from the ACTUAL snapshot: the listed strike where CE and PE mids are closest
    (put-call parity; stays valid while the underlying print is frozen). Falls back to the
    strike nearest the snapshot's underlying value when parity is unavailable."""
    best = None
    for s in snap["strikes"]:
        ce, pe = snap["legs"].get(("CE", s)), snap["legs"].get(("PE", s))
        if ce and pe and ce["mid"] and pe["mid"]:
            gap = abs(ce["mid"] - pe["mid"])
            if best is None or gap < best[0]:
                best = (gap, s)
    if best:
        return best[1], "PARITY"
    if snap["spot"] is not None and snap["strikes"]:
        return min(snap["strikes"], key=lambda s: abs(s - snap["spot"])), "NEAREST_UNDERLYING"
    return None, "UNAVAILABLE"


def strike_window(snap: dict, atm: float, n: int) -> list[float]:
    ks = snap["strikes"]
    if atm not in ks:
        return []
    i = ks.index(atm)
    return ks[max(0, i - n): i + n + 1]


def offset_strike(snap: dict, atm: float, off: int) -> float | None:
    ks = snap["strikes"]
    if atm not in ks:
        return None
    j = ks.index(atm) + off
    return ks[j] if 0 <= j < len(ks) else None
