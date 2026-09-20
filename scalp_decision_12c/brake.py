"""Risk brake for an EXISTING position: HOLD / CAUTION / PREPARE_EXIT / EXIT.

ADVISORY ONLY -- nothing here closes a position or sends an order; the 11D exit engine
and the trader stay authoritative.

Evidence against the position is grouped into INDEPENDENT families (MOMENTUM, RELATIVE,
PARTICIPATION, POSITIONING, LIQUIDITY, UNDERLYING). Correlated signals inside one family
count once, so a single noisy minute can never reach EXIT.
"""

from scalp_decision_12c.config import CAUTION, EXIT, HOLD, PREPARE_EXIT
from scalp_decision_12c.evidence import BEARISH, BULLISH, MISSING, STALE, CALL_RS, PUT_RS, oi_vote

FAMILIES = ("MOMENTUM", "RELATIVE", "PARTICIPATION", "POSITIONING", "LIQUIDITY", "UNDERLYING")


def assess(ev, position: dict, cfg) -> dict:
    side = position["option_type"]
    other = "PE" if side == "CE" else "CE"
    want_up = side == "CE"
    own, opp = ev[f"{side.lower()}_momentum"], ev[f"{other.lower()}_momentum"]
    u, rel, part, liq, strd = ev["underlying"], ev["option_relative"], ev["participation"], ev[f"liquidity_{side.lower()}"], ev["straddle"]
    against, supporting = [], []

    def add(lst, family, text):
        lst.append(dict(family=family, text=text))

    # ---- MOMENTUM (the position's own premium) -------------------------------------------
    c3, c1 = own["detail"].get("chg_3m"), own["detail"].get("chg_1m")
    persistent_break = bool(c3 is not None and c3 <= -cfg.premium_move_pct and own["detail"].get("persistent"))
    if own["detail"].get("status") == "MISSING" or c3 is None:
        add(against, "MOMENTUM", f"no usable {side} quote history this minute; support cannot be verified")
    elif persistent_break:
        add(against, "MOMENTUM", f"{side} premium {c3:+.2f}% over 3 minutes and falling persistently")
    elif c3 <= -cfg.premium_move_pct:
        add(against, "MOMENTUM", f"{side} premium {c3:+.2f}% over 3 minutes (not yet persistent)")
    elif c3 >= cfg.premium_move_pct:
        add(supporting, "MOMENTUM", f"{side} premium {c3:+.2f}% over 3 minutes")
    if own["state"] == "DECELERATING" and (c3 or 0) > 0:
        add(against, "MOMENTUM", f"{side} momentum is slowing ({c1:+.2f}% in the last minute)")

    # ---- RELATIVE (the other side) ------------------------------------------------------------
    opp3 = opp["detail"].get("chg_3m")
    adverse_rel = (PUT_RS if want_up else CALL_RS)
    if rel["state"] == adverse_rel:
        add(against, "RELATIVE", f"{other} relative strength is increasing ({rel['note']})")
    elif rel["state"] == (CALL_RS if want_up else PUT_RS):
        add(supporting, "RELATIVE", rel["note"])
    if opp3 is not None and opp3 >= cfg.strong_premium_pct and opp["detail"].get("persistent"):
        add(against, "RELATIVE", f"{other} premium is accelerating ({opp3:+.2f}% over 3 minutes)")

    # ---- PARTICIPATION -------------------------------------------------------------------------
    if part["state"] == f"{other}_STRONG":
        add(against, "PARTICIPATION", f"{other} volume is the stronger side")
    elif part["state"] == f"{side}_STRONG":
        add(supporting, "PARTICIPATION", f"{side} volume remains elevated")
    own_ratio = part["detail"].get(f"{side.lower()}_ratio")
    if own_ratio is not None and own_ratio <= cfg.volume_weak_ratio:
        add(against, "PARTICIPATION", f"{side} volume has fallen to {own_ratio:.2f}x its 5-minute average")

    # ---- POSITIONING (OI read with premium) ------------------------------------------------------
    v = oi_vote(ev["oi"], side)
    if v == "CONTRADICTING":
        add(against, "POSITIONING", f"{side} OI/premium relationship is adverse ({ev['oi']['detail'][side.lower() + '_relation']})")
    elif v == "CONFIRMING":
        add(supporting, "POSITIONING", f"{side} OI and premium are still building together")

    # ---- LIQUIDITY / execution ---------------------------------------------------------------------
    if liq["state"] == "POOR":
        add(against, "LIQUIDITY", liq["note"])
    elif liq["state"] == "GOOD":
        add(supporting, "LIQUIDITY", liq["note"])
    if liq["detail"].get("widened_vs_entry"):
        add(against, "LIQUIDITY", "spread has widened materially since entry")

    # ---- UNDERLYING ---------------------------------------------------------------------------------
    if u["state"] == (BEARISH if want_up else BULLISH):
        add(against, "UNDERLYING", f"underlying is moving against the position ({u['note']})")
    elif u["state"] == (BULLISH if want_up else BEARISH):
        add(supporting, "UNDERLYING", u["note"])
    elif u["state"] in (STALE, MISSING):
        add(against, "UNDERLYING", f"underlying reference is {u['state'].replace('UNDERLYING_', '').lower()}; it cannot confirm the position")
    px, vwap, poc = u["detail"].get("price"), u["detail"].get("vwap"), u["detail"].get("poc")
    if px and vwap and ((px < vwap) if want_up else (px > vwap)) and u["state"] not in (STALE, MISSING):
        add(against, "UNDERLYING", f"price has crossed to the wrong side of VWAP ({px:.0f} vs {vwap:.0f})")
    if px and poc and ((px < poc) if want_up else (px > poc)) and u["state"] not in (STALE, MISSING):
        add(against, "UNDERLYING", f"price is on the wrong side of today's POC ({px:.0f} vs {poc:.0f})")

    fams = sorted({x["family"] for x in against})
    core = [f for f in fams if f in cfg.core_families]
    n = len(fams)
    sup_fams = sorted({x["family"] for x in supporting})
    if n >= cfg.exit_min_families and core and (persistent_break or not cfg.exit_requires_broken_thesis):
        risk, action = "EXTREME", EXIT
    elif n >= cfg.prepare_exit_min_families and core:
        risk, action = "HIGH", PREPARE_EXIT
    elif n >= cfg.caution_min_families and core:
        risk, action = "ELEVATED", CAUTION
    elif n >= 2:
        risk, action = "ELEVATED", CAUTION
    elif n == 1:
        risk, action = "NORMAL", HOLD
    elif len(sup_fams) >= cfg.low_risk_min_support and u["state"] not in (STALE, MISSING):
        risk, action = "LOW", HOLD
    else:
        risk, action = "NORMAL", HOLD
    if action == EXIT and not persistent_break and cfg.exit_requires_broken_thesis:
        risk, action = "HIGH", PREPARE_EXIT
    summary = (f"{n} independent signal{'s' if n != 1 else ''} against the position"
               f" / {len(sup_fams)} supporting" + (f" ({', '.join(fams)})" if fams else ""))
    reason = {HOLD: "Option and underlying evidence still supports the position.",
              CAUTION: "One meaningful independent contradiction has appeared.",
              PREPARE_EXIT: "Several independent categories now contradict the position.",
              EXIT: "Multiple independent categories contradict the position and its premium trend has broken."}[action]
    return dict(position=f"BUY {side} {position.get('strike')}".strip(), option_type=side, risk_level=risk, risk_action=action,
                against=against, supporting=supporting, families_against=fams, families_supporting=sup_fams,
                n_against=n, n_supporting=len(sup_fams), thesis_broken=persistent_break, summary=summary,
                reason=f"{action.replace('_', ' ')}. {reason} {summary}.", advisory_only=True)
