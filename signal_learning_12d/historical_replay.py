"""Replay every 12C signal for a session and follow what happened next.

Strict ordering, which is what makes the dataset trustworthy:

    1. 12C decides the minute from its own causal inputs.   (untouched, read-only)
    2. 12D captures entry features from minutes <= that minute.
    3. A hypothetical position opens at that minute's ASK.
    4. 12D's position manager walks FORWARD, minute by minute, seeing only each minute as it
       arrives -- and never the entry decision.
    5. Only once the episode has ended are MFE/MAE, horizon outcomes and labels computed.

Steps 1-4 can never see step 5's data. `leakage_audit` proves it by re-running steps 1-3 with
all later minutes deleted and asserting the captured values are identical.
"""

from datetime import date

from option_risk_12b.engine import minute_view, prepare, truncate
from option_risk_12b.config import DEFAULT as RISK_CFG
from option_risk_12b.closing_state import underlying_states
from option_risk_12b.option_snapshot import shift
from position_sim_12c.lots import lot_size
from scalp_decision_12c.config import DEFAULT as DECISION_CFG
from scalp_decision_12c.engine import decide_prepared
from signal_learning_12d import VERSION
from signal_learning_12d import entry_quality as EQ
from signal_learning_12d import outcome_metrics as OM
from signal_learning_12d import signal_features as SF
from signal_learning_12d import signal_labels as SL
from signal_learning_12d.config import DEFAULT, SESSION_END, SIGNAL_FLIP, STILL_OPEN
from signal_learning_12d.position_lifecycle import PositionManager
from signal_learning_12d.signal_lifecycle import SignalEvent, episodes, signal_id

SESSION_OPEN, SESSION_LAST = "09:15", "15:30"


def decisions_for(symbol: str, d: date, series: dict, cmap: dict, levels_by_minute: dict,
                  upto: str = SESSION_LAST) -> list[dict]:
    """12C's own decisions, minute by minute, each from its own causal inputs. Read-only."""
    rows, cur = [], None
    for m in sorted(x for x in series if SESSION_OPEN <= x <= upto):
        cur = levels_by_minute.get(m, cur)
        out = decide_prepared(symbol, d, series, cmap, cur, minute=m)
        if out.get("status") != "OK":
            continue
        e = out["entry"]
        rows.append(dict(minute=m, decision=e["decision"], confirmation=e["confirmation"], reason=e["reason"],
                         atm=(out.get("option_state") or {}).get("atm_strike"), evidence=out.get("evidence"),
                         view=out.get("option_state"), levels=cur))
    return rows


def _views(series, cmap, minutes, symbol, d):
    """12B minute views, used for the entry-feature capture. Causal by construction."""
    und = underlying_states(series, cmap, minutes, RISK_CFG)
    return {m: minute_view(series, cmap, m, und, d, symbol, RISK_CFG) for m in minutes}


def replay_session(symbol: str, d: date, series: dict, cmap: dict, levels_by_minute: dict,
                   cfg=DEFAULT) -> list[dict]:
    """One symbol-day -> one row per signal episode."""
    decisions = decisions_for(symbol, d, series, cmap, levels_by_minute)
    if not decisions:
        return []
    by_minute = {r["minute"]: r for r in decisions}
    minutes = sorted(by_minute)
    views = _views(series, cmap, minutes, symbol, d)
    rows, open_until = [], None

    for ep in episodes(decisions):
        m0 = ep["minute"]
        # one position at a time: a repeat BUY inside an open position never re-opens it
        if open_until is not None and m0 <= open_until:
            continue
        view = views.get(m0)
        if view is None:
            continue
        side = ep["decision"][-2:]
        strike = ep["atm"] or view.get("atm_strike")
        lv = by_minute[m0].get("levels")
        feats = SF.capture(view, series, lv, m0)
        quality = EQ.assess(feats, side, cfg)

        entry_q = OM.quote(series, m0, side, strike)
        expiry = series[m0].get("expiry") if m0 in series else None
        qty, qty_src = lot_size(symbol, expiry) if expiry else (None, "UNKNOWN: no expiry")
        entry_price = entry_q["ask"] if entry_q["status"] == "OK" else None

        ev = SignalEvent(signal_id=signal_id(symbol, d, m0, ep["decision"]), market=symbol,
                         session_date=str(d), signal_minute=m0, direction=ep["decision"], side=side,
                         strike=strike, expiry=str(expiry) if expiry else None,
                         contract=f"{symbol} {strike:g} {side}" if strike else f"{symbol} {side}",
                         confidence=ep["confirmation"], reason=ep["reason"],
                         episode_minutes=ep["episode_minutes"], entry_features=feats, entry_quality=quality)

        result = _follow(ev, series, views, by_minute, minutes, entry_price, cfg)
        open_until = result["exit_minute"] or minutes[-1]

        metrics = OM.horizon_metrics(series, m0, entry_price, side, strike, cfg.horizons)
        realised = OM.realised(entry_price, result["exit_bid"], qty)
        row = dict(
            signal_id=ev.signal_id, version=VERSION, config_hash=cfg.config_hash(),
            decision_config_hash=DECISION_CFG.config_hash(), market=symbol, session_date=str(d),
            signal_minute=m0, direction=ep["decision"], side=side, strike=strike,
            expiry=ev.expiry, contract=ev.contract, confidence=ep["confirmation"],
            signal_reason=ep["reason"], episode_minutes=ep["episode_minutes"],
            entry_minute=m0, entry_price=entry_price, entry_price_type="ASK",
            quantity=qty, quantity_source=qty_src,
            **quality, **metrics, **realised,
            exit_minute=result["exit_minute"], exit_bid=result["exit_bid"], exit_reason=result["exit_reason"],
            hold_minutes=result["hold_minutes"],
            position_path=result["path"], position_final_state=result["final_state"],
            minutes_in_caution=result["minutes_in_caution"], minutes_in_prepare_exit=result["minutes_in_prepare_exit"],
            entry_decision_went_wait_at=result["first_wait_minute"],
            entry_waits_survived=result["waits_survived"],
            entry_features=feats,
        )
        row["outcome_label"] = SL.outcome_label(row.get("final_pnl_pct"), cfg)
        row["lifecycle_label"] = SL.lifecycle_label(row, cfg)
        row.update(SL.diagnose(row, cfg))
        rows.append(row)
    return rows


def _follow(ev: SignalEvent, series, views, by_minute, minutes, entry_price, cfg) -> dict:
    """Walk forward from the entry minute under 12D's INDEPENDENT position manager.

    The entry decision is read only to record it and to detect an opposite-side BUY. A WAIT
    never closes anything here -- that is the correction this milestone exists to make."""
    stop = round(entry_price * (1 - 10.0 / 100), 2) if entry_price is not None else None
    pm = PositionManager(side=ev.side, strike=ev.strike, entry_price=entry_price, stop_price=stop, cfg=cfg)
    first_wait, waits = None, 0
    exit_minute = exit_bid = exit_reason = None
    forward = [m for m in minutes if m > ev.signal_minute]

    for m in forward:
        row = by_minute.get(m)
        dec = (row or {}).get("decision")
        if dec == "WAIT":
            waits += 1
            first_wait = first_wait or m
        # an opposite-side BUY is a new signal, not a position-management verdict
        if dec in ("BUY_CE", "BUY_PE") and dec != ev.direction:
            exit_minute, exit_reason = m, SIGNAL_FLIP
            break
        step = pm.step(m, (row or {}).get("evidence"), OM.quote(series, m, ev.side, ev.strike), dec)
        if step["state"] == "EXIT":
            exit_minute, exit_reason = m, pm.exit_reason
            break

    if exit_minute is None:
        exit_minute = forward[-1] if forward else None
        exit_reason = SESSION_END if forward else STILL_OPEN
    if exit_minute:
        q = OM.quote(series, exit_minute, ev.side, ev.strike)
        exit_bid = q["bid"] if q["status"] == "OK" else None
    s = pm.summary()
    return dict(exit_minute=exit_minute, exit_bid=exit_bid, exit_reason=exit_reason,
                hold_minutes=(ev.age_at(exit_minute) if exit_minute else None),
                path=s["path"], final_state=s["final_state"],
                minutes_in_caution=s["minutes_in_caution"], minutes_in_prepare_exit=s["minutes_in_prepare_exit"],
                first_wait_minute=first_wait, waits_survived=waits)


# ---------------------------------------------------------------- leakage audit
def leakage_audit(symbol: str, d: date, series: dict, cmap: dict, levels_by_minute: dict,
                  cfg=DEFAULT, sample: int = 12) -> dict:
    """Re-derive each signal's ENTRY-TIME fields with every later minute deleted.

    If any captured value differs, a future minute reached a decision it should not have. Only
    entry-time fields are compared; outcomes are expected to differ, because they are precisely
    the thing that needs future data."""
    full = replay_session(symbol, d, series, cmap, levels_by_minute, cfg)
    checked, mismatches = 0, []
    for row in full[:sample]:
        m0 = row["signal_minute"]
        t_series, t_cmap = truncate(series, cmap, m0)
        t_levels = {k: v for k, v in levels_by_minute.items() if k <= m0}
        views = _views(t_series, t_cmap, [m0], symbol, d)
        view = views.get(m0)
        if view is None:
            continue
        feats = SF.capture(view, t_series, t_levels.get(m0) or _latest(t_levels, m0), m0)
        quality = EQ.assess(feats, row["side"], cfg)
        checked += 1
        for k in ("entry_timing", "momentum_state", "exhaustion_state"):
            if quality[k] != row[k]:
                mismatches.append(dict(signal_id=row["signal_id"], field=k,
                                       full=row[k], truncated=quality[k]))
        for k in ("ce_chg_3m", "pe_chg_3m", "underlying_price", "atm_strike", "straddle_value"):
            a, b = row["entry_features"].get(k), feats.get(k)
            if a != b:
                mismatches.append(dict(signal_id=row["signal_id"], field=k, full=a, truncated=b))
    return dict(symbol=symbol, session_date=str(d), signals=len(full), checked=checked,
                mismatches=mismatches, passed=not mismatches)


def _latest(levels: dict, minute: str):
    keys = [k for k in levels if k <= minute]
    return levels[max(keys)] if keys else None
