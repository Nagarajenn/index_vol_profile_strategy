"""The 13A decision: BUY CE / BUY PE / WAIT, with a complete audit trail.

Gate order matters and is fixed, because the FIRST failure becomes PRIMARY_REJECTION_REASON
(spec 30). The order runs from cheapest and most decisive to most specific:

    risk lock -> base signal -> position open -> critical data -> regime -> underlying
    -> option -> timing -> spread -> economics -> quality

13A consumes 12C's BUY CE / BUY PE as a CANDIDATE and never re-derives it. 12C is unmodified;
13A only decides whether that candidate survives its own gates. A 12C WAIT is simply not a
candidate, which is recorded as NO_BASE_SIGNAL rather than silently dropped.
"""

from option_risk_12b.option_snapshot import shift
from live_scalping_13a import VERSION
from live_scalping_13a import features as FE
from live_scalping_13a import gates as G
from live_scalping_13a import risk_brake as RB
from live_scalping_13a.config import BUY_CE, BUY_PE, DEFAULT, LOCKED, NO_TRADE, WAIT


def decide(series: dict, minute: str, base_decision: str | None, base_confirmation: str | None,
           strike: float | None, risk_state: RB.RiskState, position_open: bool = False,
           quantity: int | None = None, cfg=DEFAULT) -> dict:
    """One minute, one verdict. Pure: no clock, no DB, no network."""
    risk = RB.evaluate(risk_state, cfg)
    audit = dict(version=VERSION, config_hash=cfg.config_hash(), minute=minute,
                 base_decision=base_decision, base_confirmation=base_confirmation,
                 risk_state=risk["state"])

    def wait(reason, **extra):
        # `extra` may legitimately restate a key already in `audit` (side, for instance), so the
        # dicts are merged rather than splatted -- a duplicate keyword would be a TypeError.
        return {**audit, "decision": WAIT, "quality": NO_TRADE,
                "primary_rejection_reason": reason, "risk": risk, **extra}

    # ---- 1. risk lock outranks everything -------------------------------------------------
    if risk["state"] == LOCKED:
        return wait("RISK_LOCKED", reason_note="; ".join(risk["lock_reasons"]))

    # ---- 2. is there a candidate at all? -----------------------------------------------------
    if base_decision not in (BUY_CE, BUY_PE):
        return wait("NO_BASE_SIGNAL", reason_note=f"12C says {base_decision or 'nothing'} this minute.")
    side = "CE" if base_decision == BUY_CE else "PE"

    # ---- 3. one position at a time (spec 14) ---------------------------------------------------
    if position_open:
        return wait("POSITION_OPEN", side=side,
                    reason_note="A simulated position is already open; repeated signals are "
                                "continuation evidence, not a new trade.")

    f = FE.build(series, minute, side, strike, cfg)
    audit["features"] = f
    audit["side"] = side

    # ---- 4. critical data ---------------------------------------------------------------------------
    cd = G.critical_data(f)
    if not cd["ok"]:
        return wait("CRITICAL_DATA_MISSING", side=side, checks=dict(critical_data=cd),
                    reason_note=cd["note"])

    # ---- 5. regime -------------------------------------------------------------------------------------
    rg = G.regime(f, cfg)
    allowed, rej = G.regime_allows(rg["state"], side, cfg)
    checks = dict(critical_data=cd, regime=dict(**rg, ok=allowed))
    if not allowed:
        return wait(rej, side=side, checks=checks, regime=rg, reason_note=rg["note"])

    # ---- 6. underlying confirmation ------------------------------------------------------------------------
    uc = G.underlying_confirms(f, side, cfg)
    checks["underlying"] = uc
    if not uc["ok"]:
        return wait("UNDERLYING_NOT_CONFIRMED", side=side, checks=checks, regime=rg,
                    reason_note=uc["note"])

    # ---- 7. option confirmation ---------------------------------------------------------------------------------
    oc = G.option_confirms(f, side, cfg)
    checks["option"] = oc
    if not oc["ok"]:
        return wait("OPTION_NOT_CONFIRMED", side=side, checks=checks, regime=rg,
                    reason_note=oc["note"])

    # ---- 8. entry timing --------------------------------------------------------------------------------------------
    tm = G.entry_timing(f, side, cfg)
    tm["ok"] = tm["state"] != "EXTENDED" or not cfg.gates.enable_timing_filter
    checks["timing"] = tm
    if not tm["ok"]:
        return wait("TIMING_EXTENDED", side=side, checks=checks, regime=rg, timing=tm,
                    reason_note=tm["note"])

    # ---- 9. spread ---------------------------------------------------------------------------------------------------
    sp = G.spread_gate(f, cfg)
    checks["spread"] = sp
    if not sp["ok"]:
        return wait("SPREAD_TOO_WIDE", side=side, checks=checks, regime=rg, reason_note=sp["note"])

    # ---- 10. economics -------------------------------------------------------------------------------------------------
    ec = G.economics(f, side, cfg)
    checks["economics"] = ec
    if not ec["ok"]:
        return wait("ECONOMICS_INSUFFICIENT", side=side, checks=checks, regime=rg,
                    reason_note=ec["note"])

    # ---- 11. IV and quality -----------------------------------------------------------------------------------------------
    prev_iv = FE.quote(series, shift(minute, -3), side, strike)["iv"]
    iv = G.iv_state(f, prev_iv, cfg)
    q = G.trade_quality(checks, iv, cfg)
    entry_value = (f["ask"] * quantity) if (f.get("ask") and quantity) else None
    size_ok, size_rej = RB.position_allowed(risk_state, entry_value, cfg)
    if not size_ok:
        return wait(size_rej, side=side, checks=checks, regime=rg, iv=iv, quality=q,
                    reason_note=f"Entry value {entry_value} exceeds the position cap."
                                if entry_value else "Entry value cannot be computed.")
    if not G.quality_allows(q["grade"], cfg):
        return wait("QUALITY_TOO_LOW", side=side, checks=checks, regime=rg, iv=iv, quality=q,
                    reason_note=f"Trade quality {q['grade']}; minimum to buy is "
                                f"{cfg.gates.min_quality_to_buy}. {q['note']}")

    return {**audit, "decision": base_decision, "side": side, "quality": q["grade"],
            "primary_rejection_reason": None, "risk": risk, "checks": checks, "regime": rg,
            "iv": iv, "timing": tm, "economics": ec, "spread": sp, "entry_value": entry_value,
            "quantity": quantity,
            "reason_note": f"{rg['note']} {uc['note']} {oc['note']} {ec['note']}"}


def audit_row(out: dict) -> dict:
    """One flat row for 13A_DECISION_LOG.csv (spec 30). Every decision, including WAIT."""
    f = out.get("features") or {}
    checks = out.get("checks") or {}
    return dict(
        minute=out.get("minute"), decision=out.get("decision"), quality=out.get("quality"),
        base_decision=out.get("base_decision"), base_confirmation=out.get("base_confirmation"),
        side=out.get("side"), strike=f.get("strike"), underlying=f.get("underlying"),
        regime=(out.get("regime") or {}).get("state"),
        regime_lookback_pct=(out.get("regime") or {}).get("lookback_pct"),
        und_pre_1m=f.get("und_pre_1m"), und_pre_3m=f.get("und_pre_3m"), und_pre_5m=f.get("und_pre_5m"),
        opt_pre_3m=f.get("opt_pre_3m"), opt_pre_5m=f.get("opt_pre_5m"),
        bid=f.get("bid"), ask=f.get("ask"), ltp=f.get("ltp"), spread=f.get("spread"),
        spread_pct=(checks.get("spread") or {}).get("spread_pct"),
        delta=f.get("delta"), iv=f.get("iv"), theta=f.get("theta"), gamma=f.get("gamma"),
        vega=f.get("vega"), volume=f.get("volume"), oi=f.get("oi"),
        volume_ratio=f.get("volume_ratio"), oi_pct_3m=f.get("oi_pct_3m"),
        option_categories=len((checks.get("option") or {}).get("categories") or []),
        entry_timing=(out.get("timing") or {}).get("state"),
        iv_state=(out.get("iv") or {}).get("state"),
        iv_change_pct=(out.get("iv") or {}).get("change_pct"),
        expected_move=(out.get("economics") or {}).get("expected_move"),
        economics_ratio=(out.get("economics") or {}).get("ratio"),
        entry_value=out.get("entry_value"), quantity=out.get("quantity"),
        risk_state=out.get("risk_state"),
        primary_rejection_reason=out.get("primary_rejection_reason"),
        reason_note=(out.get("reason_note") or "")[:400],
        version=out.get("version"), config_hash=out.get("config_hash"),
    )
