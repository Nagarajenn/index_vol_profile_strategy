"""Entry decision: BUY CE / BUY PE / WAIT, from the evidence categories.

WAIT is a normal, frequent and valid outcome. A BUY needs several INDEPENDENT categories
to agree; any blocking condition (poor execution, unclear direction, non-persistent move,
insufficient data) produces WAIT regardless of how attractive the rest looks.
"""

from scalp_decision_12c.config import BUY_CE, BUY_PE, WAIT
from scalp_decision_12c.evidence import (BALANCED, BEARISH, BULLISH, CALL_RS, CONTRACTION, EXPANSION, INSUFFICIENT,
                                          MISSING, NEUTRAL, PUT_RS, STALE, oi_vote)

ORDER = {"NONE": 0, "WEAK": 1, "MODERATE": 2, "STRONG": 3}


def candidate(ev) -> str | None:
    """The side the option chain itself is pointing at (None when it points nowhere)."""
    st = ev["option_relative"]["state"]
    if st == CALL_RS:
        return "CE"
    if st == PUT_RS:
        return "PE"
    return None


def evaluate(ev, side: str, cfg) -> dict:
    """Ten independent checks for buying `side`. Returns supporting / contradicting / blocking lists."""
    other = "PE" if side == "CE" else "CE"
    own_mom, opp_mom = ev[f"{side.lower()}_momentum"], ev[f"{other.lower()}_momentum"]
    u, rel, part, liq, strd, dq = (ev["underlying"], ev["option_relative"], ev["participation"],
                                   ev[f"liquidity_{side.lower()}"], ev["straddle"], ev["data_quality"])
    want_up = side == "CE"
    sup, con, block = [], [], []

    # 1 underlying direction
    if u["state"] == (BULLISH if want_up else BEARISH):
        sup.append(("UNDERLYING", u["note"]))
    elif u["state"] == (BEARISH if want_up else BULLISH):
        block.append(("UNDERLYING", f"underlying is {u['state'].replace('UNDERLYING_', '').lower()}, against a {side} entry"))
    elif u["state"] in (STALE, MISSING):
        con.append(("UNDERLYING", u["note"]))
    if u["detail"].get("at_level") == ("AT_RESISTANCE" if want_up else "AT_SUPPORT"):
        con.append(("UNDERLYING_LEVEL", f"price is at {u['detail']['at_level'].replace('AT_', '').lower()}"))

    # 2 option relative strength
    if rel["state"] == (CALL_RS if want_up else PUT_RS):
        sup.append(("OPTION_RELATIVE", rel["note"]))
    elif rel["state"] in (EXPANSION, CONTRACTION):
        block.append(("OPTION_RELATIVE", rel["note"]))
    elif rel["state"] in (BALANCED, INSUFFICIENT):
        block.append(("OPTION_RELATIVE", "neither side is clearly outperforming"))
    else:
        block.append(("OPTION_RELATIVE", rel["note"]))

    # 3 / 4 own premium momentum, and it must persist
    c3 = own_mom["detail"].get("chg_3m")
    if own_mom["detail"].get("spike"):
        block.append((f"{side}_MOMENTUM", own_mom["note"]))
    elif c3 is None:
        block.append((f"{side}_MOMENTUM", "no momentum reading yet"))
    elif c3 >= cfg.premium_move_pct and own_mom["detail"].get("persistent"):
        sup.append((f"{side}_MOMENTUM", own_mom["note"]))
        if c3 >= cfg.strong_premium_pct and own_mom["state"] == "ACCELERATING":
            sup.append((f"{side}_ACCELERATION", f"{side} premium is accelerating"))
    elif c3 >= cfg.premium_move_pct:
        block.append((f"{side}_MOMENTUM", f"{side} move is not persistent across the last minutes"))
    else:
        block.append((f"{side}_MOMENTUM", f"{side} premium is not rising over 3 minutes"))

    # 5 participation
    if part["state"] == f"{side}_STRONG":
        sup.append(("PARTICIPATION", part["note"]))
    elif part["state"] == f"{other}_STRONG":
        con.append(("PARTICIPATION", f"{other} participation is the stronger side"))
    elif part["state"] == "WEAK":
        con.append(("PARTICIPATION", "option participation is weak on both sides"))

    # 6 OI / premium relationship
    v = oi_vote(ev["oi"], side)
    if v == "CONFIRMING":
        sup.append(("OI_RELATIONSHIP", f"{side} OI and premium are building together"))
    elif v == "CONTRADICTING":
        con.append(("OI_RELATIONSHIP", f"{side} OI/premium relationship is adverse ({ev['oi']['detail'][side.lower() + '_relation']})"))

    # 7 execution quality
    if liq["state"] == "POOR":
        block.append(("LIQUIDITY", liq["note"]))
    elif liq["state"] == "GOOD":
        sup.append(("LIQUIDITY", liq["note"]))

    # 8 straddle / premium expansion
    if strd["detail"].get("severe_contraction"):
        block.append(("STRADDLE", strd["note"]))
    elif strd["state"] == "EXPANDING":
        sup.append(("STRADDLE", strd["note"]))
    elif strd["state"] == "CONTRACTING":
        con.append(("STRADDLE", strd["note"]))

    # 9 opposite-side contradiction
    opp3 = opp_mom["detail"].get("chg_3m")
    if opp3 is not None and opp3 >= cfg.strong_premium_pct and opp_mom["detail"].get("persistent"):
        block.append((f"{other}_MOMENTUM", f"{other} premium is rising strongly at the same time ({opp3:+.2f}%)"))
    elif opp3 is not None and opp3 <= -cfg.premium_move_pct:
        sup.append((f"{other}_WEAKNESS", f"{other} premium is weakening ({opp3:+.2f}%)"))

    # 10 data quality
    if dq["state"] == "INSUFFICIENT":
        block.append(("DATA_QUALITY", "no option snapshot for this minute"))
    return dict(side=side, supporting=sup, contradicting=con, blocking=block)


def confirmation(res, ev, cfg) -> str:
    if res["blocking"]:
        return "NONE"
    n_sup, n_con = len(res["supporting"]), len(res["contradicting"])
    if n_sup >= cfg.strong_support and n_con == 0 and ev["underlying"]["state"] not in (STALE, MISSING):
        return "STRONG"
    if n_sup >= cfg.min_support_for_entry and n_con <= cfg.max_contradictions_for_entry:
        return "MODERATE"
    if n_sup >= 3 and n_con <= cfg.max_contradictions_for_entry:
        return "WEAK"
    return "NONE"


def decide(ev, cfg) -> dict:
    side = candidate(ev)
    evaluations = {s: evaluate(ev, s, cfg) for s in ("CE", "PE")}
    if side is None:
        st = ev["option_relative"]["state"].replace("_", " ").lower()
        why = ev["option_relative"]["note"]
        return dict(decision=WAIT, confirmation="NONE", side=None, supporting=[], contradicting=[],
                    blocking=[("OPTION_RELATIVE", why)], evaluations=evaluations,
                    reason=f"WAIT - {st}. {why} A new scalp entry needs one side clearly outperforming the other.")
    res = evaluations[side]
    conf = confirmation(res, ev, cfg)
    stale = ev["underlying"]["state"] in (STALE, MISSING)
    # A stale/missing underlying is the CONDITION here, not a separate contradiction, so it is excluded
    # from the count on the option-only path; every other contradiction still counts.
    other_con = [c for c in res["contradicting"] if c[0] != "UNDERLYING"]
    if stale and cfg.stale_underlying_needs_strong:
        needs = f"option-only evidence ({cfg.stale_min_support} supporting, no contradiction)"
        ok = (not res["blocking"] and len(res["supporting"]) >= cfg.stale_min_support and not other_con
              and ev[f"liquidity_{side.lower()}"]["state"] == "GOOD"
              and ev[f"{side.lower()}_momentum"]["detail"].get("persistent"))
        if ok:
            conf = "MODERATE"          # never STRONG: the underlying cannot confirm it
    else:
        needs = cfg.min_confirmation
        ok = ORDER[conf] >= ORDER[needs] and not res["blocking"]
    decision = (BUY_CE if side == "CE" else BUY_PE) if ok else WAIT
    if ok and stale:
        reason = (f"BUY {side} on option evidence alone -- the underlying reference is not live. "
                  + "; ".join(t for _, t in res["supporting"][:3]) + ".")
    elif ok:
        reason = (f"BUY {side}. " + "; ".join(t for _, t in res["supporting"][:3]) + "."
                  + (" Against: " + "; ".join(t for _, t in res["contradicting"]) + "." if res["contradicting"] else ""))
    elif res["blocking"]:
        reason = f"WAIT. {res['blocking'][0][1]}." + (
            f" ({len(res['blocking'])} blocking conditions.)" if len(res["blocking"]) > 1 else "")
    elif stale:
        reason = ("WAIT. The underlying reference is not live, so a new entry would rest on option evidence alone, and "
                  f"the {side} case is not clear enough for that ({len(res['supporting'])} supporting, {len(other_con)} against).")
    else:
        reason = (f"WAIT. {len(res['supporting'])} supporting and {len(res['contradicting'])} contradicting categories for {side} "
                  f"- confirmation {conf}, below the {needs} required to act.")
    return dict(decision=decision, confirmation=conf, side=side, supporting=res["supporting"], contradicting=res["contradicting"],
                blocking=res["blocking"], evaluations=evaluations, reason=reason, required_confirmation=needs)
