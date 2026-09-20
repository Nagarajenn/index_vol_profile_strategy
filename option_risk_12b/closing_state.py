"""Underlying reference state, closing-state description, option activity and the
option-implied spot research indicator.

We DESCRIBE observations, we do not name a mechanism: nothing here labels a minute
"AUCTION". A frozen underlying value is never presented as live.
"""

import math
import statistics
from datetime import datetime, time

from option_risk_12b.option_snapshot import shift, strike_window

LIVE, STALE, MISSING, UNCERTAIN = "LIVE", "STALE", "MISSING", "CLOSING_STATE_UNCERTAIN"


def underlying_value(series, candles, minute):
    """Value observable at `minute`: the option snapshot's underlying print (same fetch as the
    options), else the close of the 1-min candle that ENDED at `minute` (start = minute-1)."""
    s = series.get(minute)
    if s and s["spot"] is not None:
        return s["spot"], "SNAPSHOT"
    c = candles.get(shift(minute, -1))
    if c and c.get("close") is not None:
        return c["close"], "CANDLE"
    return None, None


def underlying_states(series, candles, minutes, cfg) -> dict:
    """Causal: the state at minute m uses values at minutes <= m and candles that ended <= m."""
    out, run, prev, last_live = {}, 0, None, None
    ws = cfg.window_start
    for m in minutes:
        v, src = underlying_value(series, candles, m)
        c = candles.get(shift(m, -1))
        flat_candle = bool(c and c.get("high") is not None and c["high"] == c["low"] and v is not None and c["close"] == v)
        if v is None:
            st, run = MISSING, 0
            new_print = False
        else:
            run = run + 1 if (prev is not None and v == prev) else 1
            new_print = prev is not None and v != prev and bool(out) and list(out.values())[-1]["state"] in (STALE, UNCERTAIN)
            if run >= cfg.stale_after_minutes + 1 or (flat_candle and m >= ws):
                st = STALE
            elif new_print and m >= ws:
                st = UNCERTAIN            # a new value after a frozen stretch: cannot tell continuous from computed
            elif run == 2:
                st = UNCERTAIN            # one repeated print: cannot yet tell live from frozen
            else:
                st = LIVE
            prev = v
        if st == LIVE:
            last_live = (m, v)
        age = None
        if last_live:
            h1, m1 = map(int, last_live[0].split(":"))
            h2, m2 = map(int, m.split(":"))
            age = (h2 * 60 + m2) - (h1 * 60 + m1)
        out[m] = dict(minute=m, state=st, value=v, source=src, unchanged_run=run, flat_candle=flat_candle,
                      new_print=bool(v is not None and new_print), last_reliable_value=last_live[1] if last_live else None,
                      last_reliable_minute=last_live[0] if last_live else None, age_minutes=age)
    return out


def option_activity(series, minute, atm, cfg) -> dict:
    s, p = series.get(minute), series.get(shift(minute, -1))
    if not s:
        return dict(status="MISSING_OPTION_DATA", changed_legs=None, legs=None)
    if atm is None:
        return dict(status="MISSING_OPTION_DATA", changed_legs=None, legs=None)
    ks = strike_window(s, atm, cfg.strikes_each_side)
    if not p:
        return dict(status="NO_PREVIOUS_MINUTE", changed_legs=None, legs=2 * len(ks))
    changed = total = 0
    for k in ks:
        for typ in ("CE", "PE"):
            a, b = s["legs"].get((typ, k)), p["legs"].get((typ, k))
            if a and b and a["mid"] is not None and b["mid"] is not None:
                total += 1
                changed += a["mid"] != b["mid"]
    if total == 0:
        st = "MISSING_OPTION_DATA"
    elif changed == 0:
        st = "STALE_OPTION_DATA"
    elif changed >= cfg.active_min_changed_legs:
        st = "ACTIVE"
    else:
        st = "LOW_ACTIVITY"
    return dict(status=st, changed_legs=changed, legs=total)


def closing_state(und_state: str, opt_status: str) -> str:
    if und_state == MISSING:
        return "UNDERLYING_MISSING"
    if und_state == STALE:
        return "OPTIONS_ACTIVE_UNDERLYING_STALE" if opt_status == "ACTIVE" else "UNDERLYING_STALE"
    if und_state == UNCERTAIN:
        return "CLOSING_STATE_UNCERTAIN"
    return "NORMAL_CONTINUOUS"


def combination_state(und: dict, und_move, odp_label: str, sym_move_pts: float) -> tuple[str, str]:
    """(combination state, market-state description). Underlying direction is used only when the
    underlying is LIVE at both ends of the comparison."""
    if und["state"] != LIVE:
        if odp_label in ("UP", "DOWN"):
            return "UNDERLYING_UNAVAILABLE_OPTIONS_AVAILABLE", "OPTIONS_LED_WHILE_UNDERLYING_STALE"
        if odp_label in ("NEUTRAL", "MIXED"):
            return "UNDERLYING_UNAVAILABLE_OPTIONS_AVAILABLE", f"OPTIONS_{odp_label}_WHILE_UNDERLYING_STALE"
        return "INSUFFICIENT_DATA", "NO_USABLE_REFERENCE"
    u = 0 if (und_move is None or abs(und_move) < sym_move_pts) else (1 if und_move > 0 else -1)
    o = {"UP": 1, "DOWN": -1}.get(odp_label, 0)
    if u == 0 and o == 0:
        return "NEITHER_DIRECTIONAL", "QUIET"
    if u != 0 and o == u:
        return "OPTIONS_CONFIRM", "UNDERLYING_AND_OPTIONS_ALIGNED"
    if u != 0 and o == 0:
        return "UNDERLYING_CONFIRMS", "UNDERLYING_MOVING_OPTIONS_NOT_DIRECTIONAL"
    return "DIVERGENCE", "UNDERLYING_AND_OPTIONS_DISAGREE" if u != 0 else "OPTIONS_MOVING_UNDERLYING_FLAT"


def implied_spot(series, minute, atm, und: dict, cfg, session_date) -> dict:
    """RESEARCH INDICATOR, NOT OFFICIAL SPOT, NOT A TRADING SIGNAL.
    S ~= (C_mid - P_mid) + K * exp(-r T) per strike (European parity, no dividend term), median over ATM +/- 5 two-sided legs."""
    s = series.get(minute)
    empty = dict(implied_spot=None, n=0, iqr=None, quality="INVALID", underlying_last_reference=und.get("last_reliable_value"),
                 gap_points=None, gap_percent=None, minute=minute)
    if not s or atm is None or s["expiry"] is None:
        return empty
    h, mm = map(int, minute.split(":"))
    now = datetime.combine(session_date, time(h, mm))
    exp = datetime.combine(s["expiry"], time(15, 30))
    T = max((exp - now).total_seconds(), 0) / (365 * 86400)
    disc = math.exp(-cfg.risk_free_rate * T)
    est = []
    for k in strike_window(s, atm, cfg.strikes_each_side):
        ce, pe = s["legs"].get(("CE", k)), s["legs"].get(("PE", k))
        if ce and pe and ce["mid"] and pe["mid"] and ce["spread_pct"] <= cfg.implied_max_spread_pct and pe["spread_pct"] <= cfg.implied_max_spread_pct:
            est.append((ce["mid"] - pe["mid"]) + k * disc)
    if len(est) < 2:
        return empty
    med = statistics.median(est)
    q = statistics.quantiles(est, n=4) if len(est) >= 2 else [med, med, med]
    iqr = q[2] - q[0]
    if len(est) < cfg.implied_min_strikes:
        quality = "INVALID"
    elif iqr > med * cfg.implied_max_iqr_pct / 100:
        quality = "LOW"
    else:
        quality = "OK"
    ref = und.get("last_reliable_value")
    gap = med - ref if (ref is not None and quality != "INVALID") else None
    return dict(implied_spot=med if quality != "INVALID" else None, implied_spot_raw=med, n=len(est), iqr=iqr, quality=quality,
                underlying_last_reference=ref, gap_points=gap, gap_percent=(gap / ref * 100) if gap is not None else None,
                minute=minute, time_to_expiry_years=T)
