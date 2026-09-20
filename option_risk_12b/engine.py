"""Assemble the 15:00-15:30 option risk & closing-state view for one symbol-day.

Pure function of its inputs (no DB, no clock). Used by the research runner and by the
read-only backend endpoint. Every value at minute m is computed only from snapshots
at minutes <= m and candles that ended at or before m (see tests: truncation invariance).
"""

from datetime import datetime

from option_risk_12b.closing_state import (LIVE, MISSING, STALE, UNCERTAIN, closing_state, combination_state,
                                           implied_spot, option_activity, underlying_states)
from option_risk_12b.config import DEFAULT, VERSION
from option_risk_12b.option_pressure import directional_pressure
from option_risk_12b.option_risk import assess
from option_risk_12b.option_snapshot import (minute_key, minute_range, minute_series, offset_strike, parse_snapshot,
                                             resolve_atm, shift, strike_window)
from option_risk_12b.option_state import leg_state
from option_risk_12b.option_trajectory import leg_trajectories, pcr_fn, trajectory

CAVEAT = ("Research / advisory only. The underlying index print can stop updating after about 15:15 and reappear near "
          "15:30; this view describes what the option chain was doing meanwhile. Option-implied spot is a put-call-parity "
          "research indicator -- not the official spot, not the close, and not a trading signal. Risk states are advisory: "
          "the 11D exit engine remains authoritative and nothing here closes or opens a position.")


def prepare(snapshots: list[dict], candles: list[dict]) -> tuple[dict, dict]:
    parsed = [parse_snapshot(s["fetched_at"], s.get("spot"), s.get("expiry"), s.get("payload") or {}) for s in snapshots]
    series = minute_series(parsed)
    cmap = {minute_key(c["timestamp"]): c for c in candles}
    return series, cmap


def truncate(series: dict, candles: dict, minute: str) -> tuple[dict, dict]:
    """Information observable at `minute`: snapshots up to `minute`, candles that ENDED by `minute`."""
    return ({k: v for k, v in series.items() if k <= minute},
            {k: v for k, v in candles.items() if shift(k, 1) <= minute})


def _flags(series, m, atm, und, act, ce, pe, traj, cfg):
    f = []
    if m not in series:
        f.append("MISSING_OPTION_DATA")
    elif act["status"] == "STALE_OPTION_DATA":
        f.append("STALE_OPTION_DATA")
    if und["state"] == MISSING:
        f.append("MISSING_UNDERLYING")
    elif und["state"] in (STALE, UNCERTAIN):
        f.append("STALE_UNDERLYING")
    s = series.get(m)
    if s and atm is not None:
        for k in strike_window(s, atm, cfg.display_strikes_each_side):
            if any((s["legs"].get((t, k)) or {}).get("greeks_status") in ("INVALID", "UNAVAILABLE") for t in ("CE", "PE")):
                f.append("INVALID_GREEKS")
                break
    if any(x.get("spread_pct") is not None and x["spread_pct"] >= cfg.wide_spread_pct for x in (ce, pe)):
        f.append("WIDE_SPREAD")
    if traj and traj["ce_premium"]["label"] == "INSUFFICIENT_DATA":
        f.append("INSUFFICIENT_HISTORY")
    return f


def minute_view(series, candles, m, und_all, session_date, symbol, cfg, positions=()) -> dict:
    und = und_all[m]
    s = series.get(m)
    atm, atm_method = resolve_atm(s) if s else (None, "UNAVAILABLE")
    act = option_activity(series, m, atm, cfg)
    ce = leg_state(series, m, "CE", atm) if atm is not None else dict(status="MISSING")
    pe = leg_state(series, m, "PE", atm) if atm is not None else dict(status="MISSING")
    traj = leg_trajectories(series, m, atm, cfg) if atm is not None else None
    if atm is not None and s:
        traj["pcr"] = trajectory(pcr_fn(series, strike_window(s, atm, cfg.strikes_each_side)), m, "pct",
                                 cfg.flat_pct["pcr"], cfg.accel_min_pct, cfg.horizons_min)
    pres = directional_pressure(series, m, atm, cfg) if atm is not None else dict(label="INSUFFICIENT_DATA")
    past = und_all.get(shift(m, -3))
    und_move = (und["value"] - past["value"]) if (past and und["state"] == LIVE and past["state"] == LIVE) else None
    combo, market_state = combination_state(und, und_move, pres.get("label"), cfg.underlying_move_pts.get(symbol, 5.0))
    imp = implied_spot(series, m, atm, und, cfg, session_date)
    ladder = []
    if s and atm is not None:
        for off in range(-cfg.display_strikes_each_side, cfg.display_strikes_each_side + 1):
            k = offset_strike(s, atm, off)
            if k is not None:
                ladder.append(dict(offset=off, strike=k, ce=leg_state(series, m, "CE", k), pe=leg_state(series, m, "PE", k)))
    risk = []
    for p in positions:
        if p["entry_minute"] <= m and (p.get("exit_minute") is None or m <= p["exit_minute"]):
            r = assess(series, m, p, und, cfg, p.get("entry_spread_pct"))
            r["position_label"] = p.get("label")
            risk.append(r)
    return dict(minute=m, segment="ACTUAL_UNDERLYING" if m < cfg.window_start else "CLOSING_STALE_UNDERLYING_OPTION_CONTINUATION",
                snapshot_present=s is not None, snapshot_fetched_at=s["fetched_at"].isoformat() if s else None,
                expiry=str(s["expiry"]) if s else None, atm_strike=atm, atm_method=atm_method,
                underlying=und, option_activity=act, closing_state=closing_state(und["state"], act["status"]),
                combination_state=combo, market_state=market_state, underlying_move_3m=und_move,
                ce=ce, pe=pe, trajectory=traj, pressure=pres, implied=imp, ladder=ladder, position_risk=risk,
                data_quality=_flags(series, m, atm, und, act, ce, pe, traj, cfg))


def build_session(symbol: str, session_date, snapshots: list[dict], candles: list[dict], positions=(), cfg=DEFAULT,
                  as_of: str | None = None) -> dict:
    """snapshots: [{fetched_at (tz-aware IST), spot, expiry, payload}]; candles: [{timestamp (minute start, IST),
    open, high, low, close, volume}]; positions: [{option_type, strike, entry_minute, exit_minute, entry_spread_pct, label}].
    as_of: 'HH:MM' -- minutes after it are not produced (live view)."""
    series, cmap = prepare(snapshots, candles)
    last = cfg.window_end if as_of is None else min(cfg.window_end, as_of)
    minutes = [m for m in minute_range(cfg.context_start, cfg.window_end) if m <= last]
    lead = minute_range(cfg.lookback_start, shift(cfg.context_start, -1))
    und_all = underlying_states(series, cmap, lead + minutes, cfg)
    rows = [minute_view(series, cmap, m, und_all, session_date, symbol, cfg, positions) for m in minutes]
    return _clean(dict(version=VERSION, config_hash=cfg.config_hash(), symbol=symbol, session_date=str(session_date),
                       as_of=last, minutes=rows, summary=summarize(rows, series, cfg), positions=list(positions),
                       ltp_series=ltp_series(series, cfg, last), caveat=CAVEAT, advisory_only=True))


def ltp_series(series: dict, cfg, last: str) -> list[dict]:
    """ATM CE / PE last traded price per minute from cfg.ltp_chart_start (earlier than the risk window).
    The ATM contract is resolved from each minute's own snapshot, so the strike is carried with the price:
    when the ATM moves, the price steps, and the strike is what explains it. LTP falls back to the two-sided
    mid only when the snapshot carries no last trade. A missing minute stays missing."""
    out = []
    for m in minute_range(cfg.ltp_chart_start, last):
        s = series.get(m)
        if not s:
            out.append(dict(minute=m, present=False))
            continue
        atm, _ = resolve_atm(s)
        ce, pe = (s["legs"].get(("CE", atm)), s["legs"].get(("PE", atm))) if atm is not None else (None, None)
        out.append(dict(minute=m, present=True, atm_strike=atm,
                        ce_ltp=(ce or {}).get("ltp") or (ce or {}).get("mid"),
                        pe_ltp=(pe or {}).get("ltp") or (pe or {}).get("mid")))
    return out


def summarize(rows: list[dict], series: dict, cfg) -> dict:
    win = [r for r in rows if r["minute"] >= cfg.window_start]
    missing = [r["minute"] for r in win if not r["snapshot_present"]]
    stale = [r for r in win if r["underlying"]["state"] in (STALE, UNCERTAIN, MISSING)]
    active_stale = [r for r in stale if r["option_activity"]["status"] == "ACTIVE"]
    new_print = next((r for r in win if r["underlying"]["new_print"]), None)
    latest = next((r for r in reversed(rows) if r["snapshot_present"]), rows[-1] if rows else None)
    if not latest:
        return dict(status="NO_DATA", caveat=CAVEAT)
    u = latest["underlying"]
    imp = latest["implied"]
    odp = latest["pressure"].get("label")
    derived = {"UP": "CE", "DOWN": "PE", "NEUTRAL": "NEUTRAL", "MIXED": "MIXED"}.get(odp, "UNKNOWN")
    if imp.get("quality") == "INVALID" or imp.get("implied_spot") is None:
        conf = "UNKNOWN"
    elif imp["quality"] == "OK" and latest["option_activity"]["status"] == "ACTIVE":
        conf = "MODERATE"
    else:
        conf = "LOW"
    s = series.get(latest["minute"])
    raw = []
    if s and latest["atm_strike"] is not None:
        for k in strike_window(s, latest["atm_strike"], cfg.strikes_each_side):
            raw.append(dict(strike=k, ce=leg_state(series, latest["minute"], "CE", k), pe=leg_state(series, latest["minute"], "PE", k)))
    return dict(status="OK", latest_minute=latest["minute"], underlying_state=u["state"], underlying_value=u["value"],
                last_reliable_underlying=u["last_reliable_value"], last_reliable_minute=u["last_reliable_minute"],
                underlying_age_minutes=u["age_minutes"], closing_state=latest["closing_state"],
                options_state="ACTIVE" if latest["option_activity"]["status"] == "ACTIVE" else latest["option_activity"]["status"],
                option_derived_state=derived, implied_spot=imp.get("implied_spot"), implied_gap_points=imp.get("gap_points"),
                implied_gap_percent=imp.get("gap_percent"), implied_quality=imp.get("quality"), confidence=conf,
                window_minutes=len(win), missing_option_minutes=missing, stale_minutes=len(stale),
                options_active_while_stale=len(active_stale), first_stale_minute=stale[0]["minute"] if stale else None,
                new_print_minute=new_print["minute"] if new_print else None,
                new_print_value=new_print["underlying"]["value"] if new_print else None, ladder_raw=raw, caveat=CAVEAT)


def _clean(x):
    if isinstance(x, float):
        return round(x, 6)
    if isinstance(x, dict):
        return {str(k) if not isinstance(k, str) else k: _clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_clean(v) for v in x]
    if isinstance(x, datetime):
        return x.isoformat()
    return x
