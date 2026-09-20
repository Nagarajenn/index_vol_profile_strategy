"""Assembles one 12C decision at minute T from data already in the platform.

Pure function of its inputs (no DB, no clock, no network). Strict no-lookahead: the
option series and the candles are truncated at T before anything is computed, so a
later snapshot, a later candle or any end-of-day value cannot reach the decision.
"""

from dataclasses import replace
from datetime import datetime

from option_risk_12b.closing_state import underlying_states
from option_risk_12b.config import DEFAULT as RISK_DEFAULT
from option_risk_12b.engine import _clean, minute_view, prepare, truncate
from option_risk_12b.option_snapshot import minute_range, shift
from scalp_decision_12c import brake as BRAKE
from scalp_decision_12c import entry as ENTRY
from scalp_decision_12c import evidence as EV
from scalp_decision_12c.config import DEFAULT, VERSION

CONTEXT_MINUTES = 20          # history needed for 5-minute trajectories and 5-minute volume baselines
AGE_LOOKBACK = 10             # how far back to measure "this decision has held for N minutes"
CLOSING_START, CLOSING_END = "15:15", "15:30"
ADVISORY = ("ADVISORY ONLY. Rule-based, no prediction and no probability: this panel reports what the evidence "
            "available at this minute says. It never places, modifies or cancels an order and never opens or closes "
            "a position. The 11D exit engine and the trader remain authoritative.")


def _risk_cfg(t: str):
    """A 12B config whose window covers [T-20min, T], so the same minute-view primitives can be
    used at any time of day. 12B itself is untouched."""
    start = max(shift(t, -CONTEXT_MINUTES), "09:15")
    return replace(RISK_DEFAULT, lookback_start=max(shift(start, -6), "09:15"), context_start=start, window_end=t)


def latest_minute(series: dict, as_of: str | None) -> str | None:
    ms = [m for m in sorted(series) if as_of is None or m <= as_of]
    return ms[-1] if ms else None


def decide_at(symbol: str, session_date, snapshots: list[dict], candles: list[dict], levels: dict | None = None,
              position: dict | None = None, cfg=DEFAULT, as_of: str | None = None, minute: str | None = None) -> dict:
    """snapshots / candles: the 12B shapes. levels: the latest levels_snapshots row at or before T
    (close, vwap_now, today_poc, today_vah, today_val, support_*, resistance_*, trend_label) or None.
    position: {'option_type': 'CE'|'PE', 'strike': float, 'entry_spread_pct': float|None, ...} or None."""
    series_all, cmap_all = prepare(snapshots, candles)
    return decide_prepared(symbol, session_date, series_all, cmap_all, levels, position, cfg, as_of, minute)


def decide_prepared(symbol: str, session_date, series_all: dict, cmap_all: dict, levels: dict | None = None,
                    position: dict | None = None, cfg=DEFAULT, as_of: str | None = None, minute: str | None = None) -> dict:
    """Same as decide_at with the snapshots already parsed once (option_risk_12b.engine.prepare),
    which is what a minute-by-minute replay should use."""
    t = minute or latest_minute(series_all, as_of)
    if t is None:
        return _clean(dict(version=VERSION, config_hash=cfg.config_hash(), symbol=symbol, session_date=str(session_date),
                           minute=None, status="NO_DATA", decision="WAIT", confirmation="NONE",
                           reason="WAIT. No option-chain snapshot is available for this session yet.",
                           advisory_only=True, notice=ADVISORY))
    series, cmap = truncate(series_all, cmap_all, t)      # nothing after T can be read
    rcfg = _risk_cfg(t)
    und_all = underlying_states(series, cmap, minute_range(rcfg.lookback_start, t), rcfg)
    pos_list = [dict(position, entry_minute=position.get("entry_minute", rcfg.context_start), exit_minute=None,
                     label=position.get("label", f"POSITION BUY {position['option_type']}"))] if position else []
    view = minute_view(series, cmap, t, und_all, session_date, symbol, rcfg, pos_list)
    ev = EV.build(view, series, und_all, levels, symbol, cfg, (position or {}).get("entry_spread_pct"))
    entry = ENTRY.decide(ev, cfg)
    entry["held_minutes"] = _decision_age(series_all, cmap_all, t, session_date, symbol, cfg, entry["decision"], levels)
    risk = BRAKE.assess(ev, position, cfg) if position else None
    out = dict(version=VERSION, config_hash=cfg.config_hash(), option_state_version=view.get("version", "12B-option-risk-v1"),
               symbol=symbol, session_date=str(session_date), minute=t, status="OK",
               position_state="NONE" if not position else f"BUY_{position['option_type']}",
               entry=entry, risk_brake=risk, evidence=ev, summary=_summary(ev, entry, risk, view),
               option_state=dict(atm_strike=view["atm_strike"], ce=view["ce"], pe=view["pe"],
                                 trajectory=view["trajectory"], pressure_label=view["pressure"].get("label"),
                                 implied=view["implied"], underlying=view["underlying"],
                                 option_activity=view["option_activity"], closing_state=view["closing_state"]),
               closing_state=closing_strip(series, cmap, und_all, session_date, symbol, rcfg, t),
               levels=levels, advisory_only=True, notice=ADVISORY)
    out["trace"] = trace(out)
    return _clean(out)


def _decision_age(series_all, cmap_all, t, session_date, symbol, cfg, decision, levels=None) -> int:
    """How many consecutive earlier minutes produced the SAME entry decision (capped at AGE_LOOKBACK).
    Each earlier minute is recomputed from its own truncated inputs, so this stays causal."""
    age = 0
    for k in range(1, AGE_LOOKBACK + 1):
        m = shift(t, -k)
        if m not in series_all:
            break
        series, cmap = truncate(series_all, cmap_all, m)
        rcfg = _risk_cfg(m)
        und = underlying_states(series, cmap, minute_range(rcfg.lookback_start, m), rcfg)
        v = minute_view(series, cmap, m, und, session_date, symbol, rcfg)
        # the levels row is only reused for an earlier minute when it was already published by then
        lv = levels if (levels and levels.get("as_of") and levels["as_of"] <= m) else None
        if ENTRY.decide(EV.build(v, series, und, lv, symbol, cfg), cfg)["decision"] != decision:
            break
        age += 1
    return age


def _summary(ev, entry, risk, view) -> dict:
    """The five-second read: direction, decision, action, data state."""
    return dict(direction=ev["underlying"]["state"], underlying_state=ev["underlying"]["detail"].get("underlying_state",
                                                                                                     ev["underlying"]["state"]),
                options=ev["data_quality"]["detail"]["options"], decision=entry["decision"], confirmation=entry["confirmation"],
                reason=entry["reason"], risk_level=(risk or {}).get("risk_level"), risk_action=(risk or {}).get("risk_action"),
                risk_summary=(risk or {}).get("summary"), held_minutes=entry.get("held_minutes"),
                evidence_row={"DIRECTION": ev["underlying"]["state"].replace("UNDERLYING_", ""),
                              "CE_VS_PE": ev["option_relative"]["state"],
                              "CE_MOMENTUM": ev["ce_momentum"]["state"], "PE_MOMENTUM": ev["pe_momentum"]["state"],
                              "PARTICIPATION": ev["participation"]["state"],
                              "OI": f"CE {ev['oi']['detail']['ce_relation']} / PE {ev['oi']['detail']['pe_relation']}",
                              "STRADDLE": ev["straddle"]["state"],
                              "LIQUIDITY": f"CE {ev['liquidity_ce']['state']} / PE {ev['liquidity_pe']['state']}",
                              "UNDERLYING_DATA": ev["data_quality"]["detail"]["underlying_state"]},
                data_quality=ev["data_quality"]["detail"]["flags"])


def closing_strip(series, cmap, und_all, session_date, symbol, rcfg, t) -> list[dict]:
    """Compact 15:15-15:30 option-pressure rows (reuses the existing 12B capture; no new capture)."""
    if t < CLOSING_START:
        return []
    rows = []
    for m in minute_range(CLOSING_START, min(t, CLOSING_END)):
        if m not in series:
            rows.append(dict(minute=m, present=False))
            continue
        v = minute_view(series, cmap, m, und_all, session_date, symbol, rcfg)
        lab = {"UP": "BULLISH", "DOWN": "BEARISH", "NEUTRAL": "NEUTRAL", "MIXED": "MIXED"}.get(v["pressure"].get("label"), "UNKNOWN")
        tr = v["trajectory"] or {}
        rows.append(dict(minute=m, present=True, ce_premium=v["ce"].get("mid"), pe_premium=v["pe"].get("mid"),
                         ce_1m=v["ce"].get("premium_change_pct"), pe_1m=v["pe"].get("premium_change_pct"),
                         relative=lab, ce_volume=v["ce"].get("volume_change"), pe_volume=v["pe"].get("volume_change"),
                         ce_oi=v["ce"].get("intraday_oi_change"), pe_oi=v["pe"].get("intraday_oi_change"),
                         straddle=(tr.get("straddle") or {}).get("value"),
                         underlying_state=v["underlying"]["state"], options=v["option_activity"]["status"]))
    return rows


def trace(out: dict) -> dict:
    """Reproducible decision record (see README for the format). Values only -- no free text beyond `reason`."""
    ev, e, r = out["evidence"], out["entry"], out["risk_brake"]
    return dict(timestamp=out["minute"], session_date=out["session_date"], symbol=out["symbol"],
                version=out["version"], config_hash=out["config_hash"],
                underlying_state=ev["data_quality"]["detail"]["underlying_state"], position_state=out["position_state"],
                decision=e["decision"], confirmation=e["confirmation"],
                risk_level=(r or {}).get("risk_level"), risk_action=(r or {}).get("risk_action"),
                underlying_signal=ev["underlying"]["state"],
                ce_relative_strength=ev["option_relative"]["detail"].get("ce_3m"),
                pe_relative_strength=ev["option_relative"]["detail"].get("pe_3m"),
                option_relative_state=ev["option_relative"]["state"],
                ce_momentum=ev["ce_momentum"]["state"], pe_momentum=ev["pe_momentum"]["state"],
                ce_momentum_3m=ev["ce_momentum"]["detail"].get("chg_3m"), pe_momentum_3m=ev["pe_momentum"]["detail"].get("chg_3m"),
                ce_persistent=ev["ce_momentum"]["detail"].get("persistent"), pe_persistent=ev["pe_momentum"]["detail"].get("persistent"),
                ce_volume_signal=ev["participation"]["detail"].get("ce_ratio"), pe_volume_signal=ev["participation"]["detail"].get("pe_ratio"),
                participation_state=ev["participation"]["state"],
                ce_oi_signal=ev["oi"]["detail"].get("ce_relation"), pe_oi_signal=ev["oi"]["detail"].get("pe_relation"),
                liquidity_signal=f"CE {ev['liquidity_ce']['state']} / PE {ev['liquidity_pe']['state']}",
                ce_spread_pct=ev["liquidity_ce"]["detail"].get("spread_pct"), pe_spread_pct=ev["liquidity_pe"]["detail"].get("spread_pct"),
                straddle_signal=ev["straddle"]["state"], straddle_3m=ev["straddle"]["detail"].get("chg_3m"),
                supporting=[c for c, _ in e["supporting"]], contradicting=[c for c, _ in e["contradicting"]],
                blocking=[c for c, _ in e["blocking"]],
                families_against=(r or {}).get("families_against"), n_against=(r or {}).get("n_against"),
                data_quality_flags=ev["data_quality"]["detail"]["flags"], held_minutes=e.get("held_minutes"),
                reason=e["reason"] if not r else f"{e['reason']} | RISK: {r['reason']}")
