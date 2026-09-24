"""Everything observable AT the signal minute, captured once and never revised.

Leakage rule for this module, without exception: every value comes from `series[m]` for
m <= signal_minute, or from the levels row published at or before the signal minute. Nothing
here may read a later minute. `historical_replay.leakage_audit` re-derives these fields from
truncated inputs and asserts they are bit-identical, which is what makes the rule enforceable
rather than aspirational.
"""

from option_risk_12b.option_snapshot import shift
from option_risk_12b.option_state import leg, pct


def _minute_index(minute: str) -> int:
    h, m = (int(x) for x in minute.split(":"))
    return h * 60 + m


def _leg_features(series: dict, minute: str, typ: str, strike: float | None) -> dict:
    """One side's complete observable state, with its 1/3/5-minute premium changes."""
    if strike is None:
        return {f"{typ.lower()}_{k}": None for k in
                ("premium", "chg_1m", "chg_3m", "chg_5m", "volume", "volume_chg", "oi", "oi_chg_3m",
                 "bid", "ask", "spread_pct", "bid_qty", "ask_qty", "iv", "delta", "gamma", "theta", "vega")}
    now = leg(series, minute, typ, strike) or {}
    out = {
        f"{typ.lower()}_premium": now.get("mid"),
        f"{typ.lower()}_bid": now.get("bid"), f"{typ.lower()}_ask": now.get("ask"),
        f"{typ.lower()}_spread_pct": now.get("spread_pct"),
        f"{typ.lower()}_bid_qty": now.get("bid_qty"), f"{typ.lower()}_ask_qty": now.get("ask_qty"),
        f"{typ.lower()}_volume": now.get("volume"), f"{typ.lower()}_oi": now.get("oi"),
        f"{typ.lower()}_iv": now.get("iv"), f"{typ.lower()}_delta": now.get("delta"),
        f"{typ.lower()}_gamma": now.get("gamma"), f"{typ.lower()}_theta": now.get("theta"),
        f"{typ.lower()}_vega": now.get("vega"),
    }
    for k in (1, 3, 5):
        past = leg(series, shift(minute, -k), typ, strike)
        out[f"{typ.lower()}_chg_{k}m"] = pct(now.get("mid"), past.get("mid")) if (now and past) else None
    prev = leg(series, shift(minute, -1), typ, strike) or {}
    # traded volume is cumulative, so a negative difference means the two snapshots are not
    # comparable; it is dropped as unavailable rather than shown as negative participation.
    v = (now.get("volume") - prev.get("volume")) if (now.get("volume") is not None
                                                     and prev.get("volume") is not None) else None
    out[f"{typ.lower()}_volume_chg"] = v if (v is None or v >= 0) else None
    past3 = leg(series, shift(minute, -3), typ, strike) or {}
    out[f"{typ.lower()}_oi_chg_3m"] = pct(now.get("oi"), past3.get("oi")) if (now and past3) else None
    return out


def capture(view: dict, series: dict, levels: dict | None, minute: str, session_open: str = "09:15",
            session_close: str = "15:30") -> dict:
    """The complete entry-time feature row for one signal minute.

    `view` is 12C/12B's own minute view for that minute -- already causal by construction, and
    consumed read-only. Nothing here recomputes a 12C value."""
    strike = view.get("atm_strike")
    und = view.get("underlying") or {}
    pres = view.get("pressure") or {}
    traj = view.get("trajectory") or {}
    straddle = traj.get("straddle") or {}
    lv = levels or {}
    spot = und.get("value")
    vwap, poc = lv.get("vwap_now"), lv.get("today_poc")

    feats = {
        # -- direction -----------------------------------------------------------------------
        "atm_strike": strike,
        "directional_state": view.get("market_state") or view.get("combination_state"),
        "option_directional_pressure": pres.get("label"),
        "ce_vs_pe_relative": pres.get("CALL_RELATIVE_STRENGTH"),
        "ce_premium_pct_3m": pres.get("ce_premium_pct_3m"),
        "pe_premium_pct_3m": pres.get("pe_premium_pct_3m"),
        # -- market ---------------------------------------------------------------------------
        "underlying_price": spot,
        "underlying_state": und.get("state"),
        "underlying_age_minutes": und.get("age_minutes"),
        "underlying_move_3m": view.get("underlying_move_3m"),
        "vwap": vwap, "poc": poc, "vah": lv.get("today_vah"), "val": lv.get("today_val"),
        "vs_vwap": (spot - vwap) if (spot is not None and vwap is not None) else None,
        "vs_poc": (spot - poc) if (spot is not None and poc is not None) else None,
        "trend_label": lv.get("trend_label"),
        "support_high": lv.get("support_high"), "resistance_low": lv.get("resistance_low"),
        # -- straddle ---------------------------------------------------------------------------
        "straddle_value": straddle.get("value"),
        "straddle_chg_1m": straddle.get("chg_1m"), "straddle_chg_3m": straddle.get("chg_3m"),
        "straddle_chg_5m": straddle.get("chg_5m"), "straddle_state": straddle.get("label"),
        # -- timing -------------------------------------------------------------------------------
        "hour": int(minute.split(":")[0]), "minute_of_hour": int(minute.split(":")[1]),
        "minutes_since_open": _minute_index(minute) - _minute_index(session_open),
        "minutes_to_close": _minute_index(session_close) - _minute_index(minute),
        # -- data quality ----------------------------------------------------------------------------
        "data_quality_flags": list(view.get("data_quality") or []),
        "snapshot_present": view.get("snapshot_present"),
        "option_activity": (view.get("option_activity") or {}).get("status"),
    }
    feats.update(_leg_features(series, minute, "CE", strike))
    feats.update(_leg_features(series, minute, "PE", strike))
    # acceleration comes from 12B's own trajectory, read-only
    for typ in ("ce", "pe"):
        feats[f"{typ}_acceleration"] = (traj.get(f"{typ}_premium") or {}).get("acceleration")
        feats[f"{typ}_momentum_label"] = (traj.get(f"{typ}_premium") or {}).get("label")
    return feats
