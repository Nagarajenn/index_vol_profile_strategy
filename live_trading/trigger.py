"""Turn 12C's existing decisions into an entry candidate.

This module does NOT decide direction. 12C decides; this only asks "has that decision
qualified for one of the day's two scarce trade slots?" -- confirmation strength, episode
length, and the time window. No 12C threshold is read, changed or re-derived here.
"""

from dataclasses import dataclass

from option_risk_12b.option_state import leg
from scalp_decision_12c.config import BUY_CE, BUY_PE


@dataclass
class Candidate:
    minute: str
    decision: str
    confirmation: str | None
    reason: str
    episode_minutes: int
    side: str                      # CE / PE
    strike: float | None
    expiry: str | None
    ask: float | None
    bid: float | None
    spread_pct: float | None
    evidence: dict | None = None


def episode_minutes(history: list[tuple[str, str]], minute: str, decision: str) -> int:
    """Consecutive minutes, ending at `minute`, on which 12C said the same thing.

    `history` is [(minute, decision), ...] in ascending order. A BUY that appears for one
    minute and vanishes counts as 1 and can never satisfy the >= 2 rule."""
    run = 0
    for m, d in reversed([h for h in history if h[0] <= minute]):
        if d != decision:
            break
        run += 1
    return run


def candidate(out: dict, history: list[tuple[str, str]], series: dict, minute: str) -> Candidate | None:
    """Build an entry candidate from one 12C decision result. None when it is not a BUY."""
    if out.get("status") != "OK":
        return None
    entry = out.get("entry") or {}
    decision = entry.get("decision")
    if decision not in (BUY_CE, BUY_PE):
        return None
    side = "CE" if decision == BUY_CE else "PE"
    strike = (out.get("option_state") or {}).get("atm_strike")
    snap = series.get(minute) or {}
    q = leg(series, minute, side, strike) if strike is not None else None
    return Candidate(
        minute=minute, decision=decision, confirmation=entry.get("confirmation"),
        reason=entry.get("reason", ""), episode_minutes=episode_minutes(history, minute, decision),
        side=side, strike=strike,
        expiry=str(snap.get("expiry")) if snap.get("expiry") else None,
        ask=(q or {}).get("ask"), bid=(q or {}).get("bid"),
        spread_pct=(q or {}).get("spread_pct"), evidence=out.get("evidence"),
    )
