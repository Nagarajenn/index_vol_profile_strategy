"""Position risk state for the simulated position: NORMAL / ELEVATED / HIGH / STOP_BREACH / UNKNOWN.

This is a risk brake for observability, not an entry rule and not a new strategy. It combines
two things that are already computed elsewhere:

* how much of the entry-to-stop buffer is left (from the BID), and
* how many INDEPENDENT 12C evidence families currently argue against the position
  (reused unchanged from scalp_decision_12c.brake -- premium, relative strength, participation,
  positioning, liquidity, underlying).

A single adverse observation never reaches HIGH: that needs either several independent families
or a position that is materially close to its stop.
"""

from scalp_decision_12c import brake as BRAKE
from scalp_decision_12c.config import DEFAULT as DECISION_CFG

NORMAL, ELEVATED, HIGH, STOP_BREACH, UNKNOWN = "NORMAL", "ELEVATED", "HIGH", "STOP_BREACH", "UNKNOWN"


def assess(position_side: str, strike, evidence: dict | None, m: dict, data_status: str, cfg,
           decision_cfg=DECISION_CFG) -> dict:
    """m: the mark() result for this minute. Returns the state with its explicit reasons."""
    reasons, families = [], []
    if evidence is not None:
        b = BRAKE.assess(evidence, dict(option_type=position_side, strike=strike), decision_cfg)
        families = b["families_against"]
        reasons += [f"[{x['family']}] {x['text']}" for x in b["against"]]
    buffer_left = m.get("stop_buffer_left")

    if data_status == "MISSING" or m.get("pnl_status") != "OK":
        return dict(risk_state=UNKNOWN, reasons=["No executable bid for the held contract, so the position "
                                                 "cannot be marked or compared with its stop."],
                    families_against=families, stop_buffer_left=buffer_left, advisory_only=True)
    if m.get("stop_breached"):
        return dict(risk_state=STOP_BREACH,
                    reasons=[f"Bid {m['pnl_per_unit'] + 0:.2f} below entry is at or through the advisory stop "
                             f"({m['stop_loss_price']:.2f})."] + reasons,
                    families_against=families, stop_buffer_left=buffer_left, advisory_only=True)

    if buffer_left is not None and buffer_left <= cfg.buffer_high:
        reasons.insert(0, f"Only {buffer_left * 100:.0f}% of the entry-to-stop buffer is left.")
        state = HIGH
    elif len(families) >= cfg.families_high:
        state = HIGH
    elif (buffer_left is not None and buffer_left <= cfg.buffer_elevated) or len(families) >= cfg.families_elevated:
        if buffer_left is not None and buffer_left <= cfg.buffer_elevated:
            reasons.insert(0, f"{buffer_left * 100:.0f}% of the entry-to-stop buffer is left.")
        state = ELEVATED
    else:
        state = NORMAL
    if data_status == "STALE":
        reasons.append("Option data is stale, so this reading is less reliable than usual.")
        state = ELEVATED if state == NORMAL else state
    if not reasons:
        reasons = ["Price is holding above the advisory stop and no independent evidence family argues "
                   "against the position."]
    return dict(risk_state=state, reasons=reasons, families_against=families, stop_buffer_left=buffer_left,
                advisory_only=True)
