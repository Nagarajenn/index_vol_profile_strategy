"""The live 12D block for the decision panel.

Maps a 12C decision result into the feature keys `entry_quality` expects, so the panel can show
DIRECTION / ENTRY TIMING / MOMENTUM / MOVE STATE / SIGNAL AGE beside the decision. Read-only
over 12C's output -- it recomputes nothing 12C already decided and changes no rule.

The point of this block on screen is the case the milestone opened on: 12C can say BUY CE while
the CE premium is already decelerating into an extended move. The entry engine expresses both as
"BUY CE"; this block says which one it is.
"""

from signal_learning_12d.config import DEFAULT, INSUFFICIENT
from signal_learning_12d.entry_quality import assess


def _features(result: dict) -> dict:
    """12C evidence -> the flat feature keys entry_quality reads. No recomputation."""
    ev = result.get("evidence") or {}
    out = {}
    for side in ("ce", "pe"):
        d = (ev.get(f"{side}_momentum") or {}).get("detail") or {}
        out[f"{side}_chg_1m"] = d.get("chg_1m")
        out[f"{side}_chg_3m"] = d.get("chg_3m")
        out[f"{side}_chg_5m"] = d.get("chg_5m")
        out[f"{side}_acceleration"] = d.get("acceleration")
        out[f"{side}_momentum_label"] = (ev.get(f"{side}_momentum") or {}).get("state")
    out["straddle_chg_3m"] = ((ev.get("straddle") or {}).get("detail") or {}).get("chg_3m")
    out["directional_state"] = (ev.get("underlying") or {}).get("state")
    return out


def block(result: dict, cfg=DEFAULT) -> dict | None:
    """The 12D view of the current minute, or None when there is no decision to describe."""
    entry = result.get("entry") or {}
    decision = entry.get("decision") or result.get("decision")
    if not decision:
        return None
    feats = _features(result)
    # With no position and no BUY there is no side to assess; the CE leg is used purely as the
    # reference for describing the market's own move, and is labelled as such.
    side = "CE" if decision == "BUY_CE" else "PE" if decision == "BUY_PE" else None
    q = assess(feats, side or "CE", cfg)
    und = (result.get("evidence") or {}).get("underlying") or {}
    direction = (und.get("state") or "").replace("UNDERLYING_", "") or "UNKNOWN"
    return dict(
        version=result.get("version"), config_hash=cfg.config_hash(),
        applies_to=side, is_signal=side is not None,
        direction=direction,
        entry_timing=q["entry_timing"] if side else INSUFFICIENT,
        entry_timing_note=q["entry_timing_note"] if side else "No BUY signal this minute -- nothing to time.",
        entry_timing_provisional=True,
        momentum_state=q["momentum_state"], momentum_note=q["momentum_note"],
        exhaustion_state=q["exhaustion_state"], exhaustion_note=q["exhaustion_note"],
        signal_age_minutes=entry.get("held_minutes"),
        measurements=q["momentum_measurements"],
        caveat=("Entry-timing and exhaustion labels are PROVISIONAL measurement boundaries, not "
                "validated quality judgements. They describe where in a move the signal landed."),
    )
