"""Minute option state for one leg (CE or PE at a fixed strike).

All changes are between CONSECUTIVE minute snapshots of the SAME contract. If the
previous minute is missing the change is None -- never bridged, never filled.

IMPORTANT: Dhan's ``previous_oi`` is the prior-day OI. It is NOT used here.
Intraday OI change = current_oi - previous_snapshot_oi (consecutive snapshots).
"""

from option_risk_12b.option_snapshot import shift


def leg(series: dict, minute: str, typ: str, strike):
    s = series.get(minute)
    return s["legs"].get((typ, strike)) if s and strike is not None else None


def val(series, minute, typ, strike, field):
    q = leg(series, minute, typ, strike)
    return q.get(field) if q else None


def pct(a, b):
    return (a / b - 1) * 100 if (a is not None and b not in (None, 0)) else None


def diff(a, b):
    return a - b if (a is not None and b is not None) else None


def flow(series, minute, typ, strike):
    """Traded volume during the minute ending at `minute` = cumulative(t) - cumulative(t-1)."""
    return diff(val(series, minute, typ, strike, "volume"), val(series, shift(minute, -1), typ, strike, "volume"))


def leg_state(series: dict, minute: str, typ: str, strike) -> dict:
    q = leg(series, minute, typ, strike)
    prev_m = shift(minute, -1)
    if q is None:
        return dict(type=typ, strike=strike, status="MISSING")
    p = leg(series, prev_m, typ, strike)
    vol_chg = diff(q["volume"], p["volume"]) if p else None
    prev_vol_chg = flow(series, prev_m, typ, strike)
    return dict(type=typ, strike=strike, status="OK", ltp=q["ltp"], bid=q["bid"], ask=q["ask"], mid=q["mid"],
                spread=q["spread"], spread_pct=q["spread_pct"], volume=q["volume"], volume_change=vol_chg,
                volume_acceleration=diff(vol_chg, prev_vol_chg),
                oi=q["oi"], intraday_oi_change=diff(q["oi"], p["oi"]) if p else None,
                iv=q["iv"], delta=q["delta"], gamma=q["gamma"], theta=q["theta"], vega=q["vega"],
                greeks_status=q["greeks_status"],
                premium_change_pts=diff(q["mid"], p["mid"]) if p else None,
                premium_change_pct=pct(q["mid"], p["mid"]) if p else None,
                bid_qty=q["bid_qty"], ask_qty=q["ask_qty"])
