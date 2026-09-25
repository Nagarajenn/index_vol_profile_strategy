"""PRICE_ACTION_CONFIRMATION and its integration with 13A.

This is the only module that knows which side 13A proposed. Everything upstream describes price
without reference to the candidate, so the confirmation is a genuine second opinion rather than
a restatement of the first.

Integration contract (spec 9), and the reason for it: 13B may only ever REMOVE a trade.
  CONFIRMED    -> the 13A BUY stands
  PARTIAL      -> WAIT   (configurable)
  CONTRADICTED -> WAIT
  NO_SETUP     -> WAIT
  UNKNOWN      -> the 13A decision is preserved and marked PRICE_ACTION_UNKNOWN
It can never turn a 13A WAIT into a BUY.
"""

from price_action_13b import bars as B
from price_action_13b import context as CX
from price_action_13b import structure as ST
from price_action_13b.config import (ABOVE_VWAP, BELOW_VWAP, BREAKDOWN, BREAKOUT_CONTINUATION,
                                     BREAKOUT_UP, CLEAN_BREAK, CLEAN_BREAK_FT, CONFIRMED,
                                     CONTRADICTED, DEFAULT, EXHAUSTED_BREAK, EXTENDED_MOVE,
                                     FAILED_BREAK, INSUFFICIENT, NO_BREAK, NO_SETUP, PARTIAL,
                                     RANGE_ROTATION, REVERSAL, TRENDING_DOWN, TRENDING_UP, UNKNOWN)


def evaluate(cmap: dict, minute: str, side: str, levels: dict | None, cfg=DEFAULT) -> dict:
    """The complete price-action read for one 13A candidate minute."""
    window = B.completed_bars(cmap, minute, cfg.structure_window + cfg.atr_period + 5)
    if len(window) < 2 * cfg.swing_k + 3:
        return _unknown("Not enough completed 1-minute bars before this signal.", window, minute)

    struct = ST.structure(window, cfg)
    brk = ST.break_quality(window, "up" if side == "CE" else "down", struct, cfg)
    setup = ST.setup_type(struct, brk, cfg)
    vwap = CX.vwap_context(window, (levels or {}).get("vwap_now"), cfg)
    value = CX.value_context(window, levels, cfg)
    vol = CX.volume_context(window, cfg)
    vol_ok = CX.volume_confirms(vol, side, window)

    want_up = side == "CE"
    # --- the four independent price-action questions ------------------------------------------
    structure_agrees = (struct["state"] in ((TRENDING_UP, BREAKOUT_UP) if want_up
                                            else (TRENDING_DOWN, BREAKDOWN)))
    broke = brk["state"] in (CLEAN_BREAK, CLEAN_BREAK_FT)
    followed = brk["state"] == CLEAN_BREAK_FT
    vwap_agrees = (vwap["state"] == ABOVE_VWAP) if want_up else (vwap["state"] == BELOW_VWAP)
    value_agrees = value["state"] in (("ACCEPTANCE_ABOVE_VAH",) if want_up
                                      else ("ACCEPTANCE_BELOW_VAL",))

    agree = sum(1 for x in (structure_agrees, broke, vwap_agrees, bool(vol_ok)) if x)
    contradicting = []
    if brk["state"] == FAILED_BREAK:
        contradicting.append("the break failed and price is back inside")
    if brk["state"] == EXHAUSTED_BREAK:
        contradicting.append("the move is already extended beyond the level")
    if struct["state"] in ((TRENDING_DOWN, BREAKDOWN) if want_up else (TRENDING_UP, BREAKOUT_UP)):
        contradicting.append(f"structure reads {struct['state'].replace('_', ' ').lower()}")
    if vol_ok is False and vol["state"] != UNKNOWN:
        contradicting.append("volume is not confirming the move's direction")

    # --- the verdict -------------------------------------------------------------------------------
    if struct["state"] == INSUFFICIENT or brk["state"] == INSUFFICIENT:
        return _unknown("Structure or break quality could not be established.", window, minute,
                        struct, brk, setup, vwap, value, vol)
    if contradicting and not broke:
        state = CONTRADICTED
    elif setup["state"] in (RANGE_ROTATION,) or brk["state"] == NO_BREAK:
        state = NO_SETUP
    elif broke and followed and structure_agrees and agree >= 3:
        state = CONFIRMED
    elif broke and (structure_agrees or followed):
        state = PARTIAL
    elif setup["state"] in (REVERSAL, EXTENDED_MOVE):
        state = CONTRADICTED
    else:
        state = PARTIAL if broke else NO_SETUP

    reason = _reason(state, side, struct, brk, setup, vwap, value, vol, contradicting)
    return dict(
        confirmation=state, reason=reason, side=side, minute=minute,
        structure=struct["state"], structure_note=struct["note"],
        higher_high=struct.get("higher_high"), higher_low=struct.get("higher_low"),
        lower_high=struct.get("lower_high"), lower_low=struct.get("lower_low"),
        break_state=brk["state"], break_level=brk.get("level"), break_minute=brk.get("break_minute"),
        break_note=brk["note"], follow_through=followed,
        setup=setup["state"], setup_note=setup["note"],
        vwap_state=vwap["state"], vwap_distance_pct=vwap.get("distance_pct"), vwap_note=vwap["note"],
        value_state=value["state"], value_note=value["note"],
        volume_state=vol["state"], volume_ratio=vol.get("ratio"), volume_note=vol["note"],
        volume_confirms=vol_ok, agreeing_factors=agree, contradicting_factors=contradicting,
        structure_agrees=structure_agrees, vwap_agrees=vwap_agrees, value_agrees=value_agrees,
        bars_used=len(window), last_completed_bar=window[-1]["minute"] if window else None,
    )


def _unknown(note, window, minute, *rest) -> dict:
    out = dict(confirmation=UNKNOWN, reason=note, minute=minute,
               structure=INSUFFICIENT, break_state=INSUFFICIENT, setup="NO_CLEAR_SETUP",
               vwap_state=UNKNOWN, value_state=UNKNOWN, volume_state=UNKNOWN,
               bars_used=len(window), last_completed_bar=window[-1]["minute"] if window else None,
               agreeing_factors=0, contradicting_factors=[], follow_through=False,
               structure_note=note, break_note=note, setup_note=note, vwap_note=note,
               value_note=note, volume_note=note, volume_confirms=None,
               higher_high=None, higher_low=None, lower_high=None, lower_low=None,
               break_level=None, break_minute=None, vwap_distance_pct=None, volume_ratio=None,
               structure_agrees=False, vwap_agrees=False, value_agrees=False, side=None)
    return out


def _reason(state, side, struct, brk, setup, vwap, value, vol, contradicting) -> str:
    """A sentence a trader can check against the chart, in the spec's own arrow style."""
    chain = []
    if struct["note"] and "No confirmed" not in struct["note"]:
        chain.append(struct["note"])
    if brk["state"] in (CLEAN_BREAK, CLEAN_BREAK_FT):
        chain.append(f"{'LOW' if side == 'PE' else 'HIGH'} BREAK at {brk['level']:,.1f}")
        chain.append("FOLLOW-THROUGH" if brk["state"] == CLEAN_BREAK_FT else "NO FOLLOW-THROUGH YET")
    if vwap["state"] not in (UNKNOWN,):
        chain.append(vwap["state"].replace("_", " "))
    if value["state"] not in (UNKNOWN, "INSIDE_VALUE"):
        chain.append(value["state"].replace("_", " "))
    if vol["state"] != UNKNOWN:
        chain.append(vol["state"].replace("VOLUME_", "VOLUME "))
    head = " → ".join(chain) if chain else "No readable price-action chain."

    if state == CONFIRMED:
        return head
    if state == NO_SETUP:
        # name the actual cause -- a missing break and a range rotation are different problems
        cause = (brk["note"] if brk["state"] == "NO_BREAK" else setup["note"])
        return (f"{'Bearish' if side == 'PE' else 'Bullish'} candidate with no clean setup: "
                f"{cause} {head}")
    if state == CONTRADICTED:
        return f"Price action contradicts the candidate: {'; '.join(contradicting) or brk['note']}. {head}"
    return f"Partial: {head}"


# ---------------------------------------------------------------- integration with 13A
def apply(thirteen_a_decision: str, pa: dict, cfg=DEFAULT) -> dict:
    """Combine 13A's verdict with the price-action read. 13B may only remove trades."""
    if not cfg.enabled:
        return dict(final_decision=thirteen_a_decision, price_action_block=False,
                    final_price_action_state=pa.get("confirmation"),
                    block_reason=None, note="13B is disabled; the 13A decision passes through.")
    if thirteen_a_decision not in ("BUY_CE", "BUY_PE"):
        return dict(final_decision=thirteen_a_decision, price_action_block=False,
                    final_price_action_state=pa.get("confirmation"), block_reason=None,
                    note="13A did not produce a candidate, so there is nothing to confirm.")

    c = pa.get("confirmation")
    if c == CONFIRMED:
        return dict(final_decision=thirteen_a_decision, price_action_block=False,
                    final_price_action_state=c, block_reason=None,
                    note="Price action confirms the candidate.")
    if c == UNKNOWN and cfg.preserve_on_unknown:
        return dict(final_decision=thirteen_a_decision, price_action_block=False,
                    final_price_action_state=UNKNOWN, block_reason=None,
                    note="Price action could not be established; the 13A decision is preserved "
                         "and marked PRICE_ACTION_UNKNOWN.")
    blocking = {PARTIAL: cfg.block_on_partial, CONTRADICTED: cfg.block_on_contradicted,
                NO_SETUP: cfg.block_on_no_setup}.get(c, False)
    if blocking:
        return dict(final_decision="WAIT", price_action_block=True, final_price_action_state=c,
                    block_reason=f"PRICE_ACTION_{c}", note=pa.get("reason"))
    return dict(final_decision=thirteen_a_decision, price_action_block=False,
                final_price_action_state=c, block_reason=None, note=pa.get("reason"))
