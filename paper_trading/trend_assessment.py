"""Paper-agent market-state interpretation layer.

This does NOT replace analytics/trend_classifier.py -- that remains the
authoritative trend component and is consumed here as ONE input among
ten. What this module adds is (a) a 7-level assessment the paper agent
can act on, and (b) explicit supporting/conflicting/risk factor lists, so
every decision can explain itself against real numbers.

Each input contributes a bounded vote in [-1, +1]; the assessment is the
sum mapped through fixed thresholds. Deliberately not a fitted model:
Milestones 11A-11C established there is no validated edge to fit to, so
an interpretable vote is the honest construct.
"""

from paper_trading.models import PaperMarketState, TrendAssessment, TrendVerdict

# Sum-of-votes thresholds. Symmetric by construction -- the agent must
# not be structurally more willing to go long than short.
STRONG_THRESHOLD = 3.0
DIRECTIONAL_THRESHOLD = 1.5
WEAK_THRESHOLD = 0.5

_BULLISH_TRENDS = ("Bullish", "Strong Bullish")
_BEARISH_TRENDS = ("Bearish", "Strong Bearish")


def _classify(score: float) -> TrendAssessment:
    if score >= STRONG_THRESHOLD:
        return "STRONG_UP"
    if score >= DIRECTIONAL_THRESHOLD:
        return "UP"
    if score >= WEAK_THRESHOLD:
        return "WEAK_UP"
    if score <= -STRONG_THRESHOLD:
        return "STRONG_DOWN"
    if score <= -DIRECTIONAL_THRESHOLD:
        return "DOWN"
    if score <= -WEAK_THRESHOLD:
        return "WEAK_DOWN"
    return "NEUTRAL"


def assess_trend(state: PaperMarketState, max_conflicting: int = 2) -> TrendVerdict:
    """Ten evidence inputs, each optional. A missing input contributes no
    vote and is recorded as a risk factor rather than silently treated as
    neutral agreement."""
    votes: list[float] = []
    supporting: list[str] = []
    conflicting: list[str] = []
    risks: list[str] = []

    # (vote, message) pairs. Which list a message ends up in is decided in
    # _finalize once the NET direction is known -- a bullish input under a
    # bearish verdict is evidence AGAINST that verdict, and labelling it
    # "supporting" would misrepresent the agent's own reasoning.
    evidence: list[tuple[float, str]] = []

    def record(vote: float, bullish_msg: str, bearish_msg: str) -> None:
        votes.append(vote)
        if vote > 0 and bullish_msg:
            evidence.append((vote, bullish_msg))
        elif vote < 0 and bearish_msg:
            evidence.append((vote, bearish_msg))

    # 1. existing Decision Card trend classifier (authoritative component)
    if state.trend_label:
        if state.trend_label in _BULLISH_TRENDS:
            record(1.0, f"Trend classifier reads {state.trend_label}", "")
        elif state.trend_label in _BEARISH_TRENDS:
            record(-1.0, "", f"Trend classifier reads {state.trend_label}")
        else:
            risks.append(f"Trend classifier is {state.trend_label} -- no directional lead")
    else:
        risks.append("Trend classifier unavailable")

    # 2. price vs VWAP
    if state.distance_from_vwap is not None and state.atr_14:
        normalized = state.distance_from_vwap / state.atr_14
        if normalized > 0.1:
            record(min(normalized, 1.0), f"Price {state.distance_from_vwap:+.0f} above VWAP", "")
        elif normalized < -0.1:
            record(max(normalized, -1.0), "", f"Price {state.distance_from_vwap:+.0f} below VWAP")
    else:
        risks.append("VWAP distance unavailable")

    # 3. VWAP slope
    if state.vwap_slope is not None:
        if state.vwap_slope > 0:
            record(0.5, "VWAP sloping up", "")
        elif state.vwap_slope < 0:
            record(-0.5, "", "VWAP sloping down")

    # 4. POC migration
    if state.poc_migration is not None:
        if state.poc_migration > 0:
            record(0.5, f"POC migrating up ({state.poc_migration:+.0f})", "")
        elif state.poc_migration < 0:
            record(-0.5, "", f"POC migrating down ({state.poc_migration:+.0f})")

    # 5. short-term momentum
    if state.momentum_5min is not None and state.atr_14:
        normalized = state.momentum_5min / state.atr_14
        if abs(normalized) > 0.05:
            record(max(-1.0, min(1.0, normalized * 2)),
                   f"5-min momentum {state.momentum_5min:+.0f}",
                   f"5-min momentum {state.momentum_5min:+.0f}")

    # 6. volume dominance proxy (Chaikin-style, disclosed as a proxy)
    if state.dominance_ratio is not None:
        if state.dominance_ratio >= 0.55:
            record(0.5, f"Buy dominance {state.dominance_ratio:.0%}", "")
        elif state.dominance_ratio <= 0.45:
            record(-0.5, "", f"Sell dominance {1 - state.dominance_ratio:.0%}")

    # 7. volume conviction -- scales nothing on its own, but thin volume
    #    behind a directional read is a genuine risk, not a vote.
    if state.rvol_pct is not None:
        if state.rvol_pct < 60:
            risks.append(f"Relative volume only {state.rvol_pct:.0f}% -- weak conviction behind any move")
        elif state.rvol_pct > 150:
            supporting.append(f"Relative volume {state.rvol_pct:.0f}% -- participation confirms the move")
    else:
        risks.append("Relative volume unavailable")

    # 8. support/resistance proximity -- an overhead wall contradicts a
    #    long thesis even when every momentum input agrees.
    if state.spot is not None and state.atr_14:
        if state.resistance_low is not None:
            gap = state.resistance_low - state.spot
            if 0 <= gap < 0.5 * state.atr_14:
                conflicting.append(f"Resistance {gap:.0f} pts overhead (inside 0.5x ATR)")
        if state.support_high is not None:
            gap = state.spot - state.support_high
            if 0 <= gap < 0.5 * state.atr_14:
                conflicting.append(f"Support {gap:.0f} pts below (inside 0.5x ATR)")

    # 9. option-chain pressure via PCR level
    if state.pcr is not None:
        if state.pcr >= 1.2:
            record(0.5, f"PCR {state.pcr:.2f} -- put writing supports a floor", "")
        elif state.pcr <= 0.8:
            record(-0.5, "", f"PCR {state.pcr:.2f} -- call writing caps upside")

    # 10. transition forecast (existing CAS engine, read-only)
    if state.probability_up is not None and state.probability_down is not None:
        edge = state.probability_up - state.probability_down
        if abs(edge) > 0.05:
            record(max(-1.0, min(1.0, edge * 2)),
                   f"Transition forecast P(UP) {state.probability_up:.0%} vs P(DOWN) {state.probability_down:.0%}",
                   f"Transition forecast P(DOWN) {state.probability_down:.0%} vs P(UP) {state.probability_up:.0%}")
    else:
        risks.append("No transition forecast available for this session")

    if state.n_analogs is not None and state.n_analogs < 10:
        risks.append(f"Only {state.n_analogs} historical analogs behind the transition forecast")

    return _finalize(state, votes, evidence, supporting, conflicting, risks, max_conflicting)


def _finalize(state, votes, evidence, supporting, conflicting, risks, max_conflicting) -> TrendVerdict:
    """Sums the votes, detects internal contradiction, and derives a
    0-100 confidence. Confidence is NOT a probability and is never
    presented as one -- it is a bounded score reflecting how much
    agreeing evidence exists and how much of it is missing."""
    score = sum(votes)
    assessment = _classify(score)

    # Split the recorded evidence by whether it agrees with the NET read.
    net_sign = 1 if score > 0 else (-1 if score < 0 else 0)
    for vote, message in evidence:
        if net_sign == 0 or (vote > 0) == (net_sign > 0):
            supporting.append(message)
        else:
            conflicting.append(message)
    supporting = [m for m in supporting if m]

    # A directional read with meaningful opposing votes is conflicted:
    # compare the magnitude that agrees with the sign against the
    # magnitude that opposes it.
    positive = sum(v for v in votes if v > 0)
    negative = -sum(v for v in votes if v < 0)
    agreeing, opposing = (positive, negative) if score >= 0 else (negative, positive)
    if agreeing > 0 and opposing / agreeing >= 0.5:
        conflicting.append(
            f"Directional evidence is split ({agreeing:.1f} for vs {opposing:.1f} against)"
        )

    is_conflicted = len(conflicting) > max_conflicting or (
        assessment != "NEUTRAL" and agreeing > 0 and opposing / agreeing >= 0.75
    )

    # Confidence: strength of the net read, penalised for contradiction
    # and for missing inputs. Capped at 85 -- this agent is never allowed
    # to claim near-certainty on a sample this small.
    strength = min(abs(score) / STRONG_THRESHOLD, 1.0)
    penalty = 0.10 * len(conflicting) + 0.06 * len(risks)
    confidence = int(max(0.0, min(0.85, strength * 0.85 - penalty)) * 100)

    return TrendVerdict(
        assessment=assessment,
        score=round(score, 3),
        confidence=confidence,
        supporting_factors=supporting,
        conflicting_factors=conflicting,
        risk_factors=risks,
        is_conflicted=is_conflicted,
    )
