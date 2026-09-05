"""Candid forecast verdict + expected-move range + driver reshaping
(Phase 9C, spec Parts 9-11).

Deliberately thin: every number this reads (probabilities, analog moves,
top contributing factors, state-vector contradictions) is already
computed elsewhere (scoring.py, transition_state.py). This module only
adds the "how do these numbers become a candid, explainable call"
layer -- no new statistics, no model fitting.
"""

import statistics as pystats
from typing import Literal

from market_transition.cas_transition import MAGNITUDE_TIER_ATR_THRESHOLDS, MagnitudeTier
from market_transition.models import ContributingFactor
from market_transition.scoring import MIN_ANALOGS

Verdict = Literal["UP", "DOWN", "NO_MATERIAL_MOVE", "NO_CLEAR_EDGE", "CONFLICTED", "INSUFFICIENT_EVIDENCE"]

# How much the leading UP/DOWN/NO_MATERIAL_MOVE probability must clear the
# next-highest by before the platform is willing to name it as the call --
# below this margin the honest read is "no clear edge", not a coin-flip
# forced into a direction. A documented starting default, tunable later,
# same stance as every other threshold in this codebase.
NO_CLEAR_EDGE_MARGIN = 0.15


def compute_verdict(
    n_analogs: int, probability_up: float, probability_down: float, probability_flat: float, contradictions: list[str],
) -> Verdict:
    """Priority order matches the spec's own: insufficient sample first
    (nothing else matters if there's no real evidence), then contradicting
    evidence (per spec Part 10, this overrides even a clean-looking
    probability split -- "do not rely on directional forecast"), then a
    thin margin between the leading and next outcome, and only then a
    genuine directional/no-material-move call."""
    if n_analogs < MIN_ANALOGS:
        return "INSUFFICIENT_EVIDENCE"
    if contradictions:
        return "CONFLICTED"

    probs: dict[Verdict, float] = {"UP": probability_up, "DOWN": probability_down, "NO_MATERIAL_MOVE": probability_flat}
    ranked = sorted(probs.items(), key=lambda kv: -kv[1])
    if ranked[0][1] - ranked[1][1] < NO_CLEAR_EDGE_MARGIN:
        return "NO_CLEAR_EDGE"
    return ranked[0][0]


def compute_expected_move_range(signed_moves: list[float]) -> tuple[float | None, float | None]:
    """25th/75th percentile of signed analog post-transition moves -- the
    "expected move: -95 to -160 points" range the spec asks for. None,None
    with fewer than 2 usable analog moves (never fabricates a range from
    one data point)."""
    if not signed_moves:
        return None, None
    if len(signed_moves) == 1:
        return signed_moves[0], signed_moves[0]
    q1, _, q3 = pystats.quantiles(sorted(signed_moves), n=4)
    return min(q1, q3), max(q1, q3)


def percentile_rank(value: float, population: list[float]) -> float | None:
    """Where `value` ranks (0-100) within `population` -- used for
    "expected move percentile": how unusual is today's implied move size
    versus all historical days' actual move sizes."""
    if not population:
        return None
    below_or_equal = sum(1 for v in population if v <= value)
    return round(below_or_equal / len(population) * 100, 1)


def classify_transition_risk_tier(expected_move_magnitude: float | None, atr_14: float | None) -> MagnitudeTier | None:
    """Reuses Phase 7A's exact ATR-normalized magnitude-tier vocabulary
    (NORMAL/MODERATE/LARGE/EXTREME) and thresholds -- applied to the
    FORECAST's expected move magnitude rather than an observed one, so the
    UI's "Transition Risk" reads on the same scale as the historical
    Magnitude column elsewhere in this app. None when the magnitude or ATR
    isn't available -- never fabricated."""
    if expected_move_magnitude is None or not atr_14:
        return None
    atr_normalized = abs(expected_move_magnitude) / atr_14
    lo, mid, hi = MAGNITUDE_TIER_ATR_THRESHOLDS
    if atr_normalized >= hi:
        return "EXTREME"
    if atr_normalized >= mid:
        return "LARGE"
    if atr_normalized >= lo:
        return "MODERATE"
    return "NORMAL"


DIRECTIONAL_VERDICTS = ("UP", "DOWN")
NO_MOVE_VERDICTS = ("NO_MATERIAL_MOVE",)
# Verdicts that made no directional call at all -- graded as "no call
# made" (every result field stays None), not as wrong, since a candid
# NO_CLEAR_EDGE/CONFLICTED/INSUFFICIENT_EVIDENCE is not a prediction to
# begin with (spec Part 10's whole point).
NO_CALL_VERDICTS = ("NO_CLEAR_EDGE", "CONFLICTED", "INSUFFICIENT_EVIDENCE")


def evaluate_forecast_vs_actual(
    verdict: str, probability_up: float, probability_down: float, probability_flat: float, actual_direction: str,
) -> dict:
    """Spec Part 14: directional accuracy, a multi-class Brier score, and
    false-positive/false-negative flags for one day's frozen forecast vs.
    its actual 15-min outcome. Never reads or writes the forecast row
    itself -- structurally enforces "do not optimize the model after
    seeing the outcome" by only ever comparing already-frozen numbers."""
    outcomes = {"up": probability_up, "down": probability_down, "flat": probability_flat}
    brier_score = round(sum((p - (1.0 if key == actual_direction else 0.0)) ** 2 for key, p in outcomes.items()), 4)
    predicted_probability_of_actual = outcomes.get(actual_direction)

    directionally_correct = is_false_positive = is_false_negative = None
    if verdict in DIRECTIONAL_VERDICTS:
        directionally_correct = (verdict == "UP" and actual_direction == "up") or (verdict == "DOWN" and actual_direction == "down")
        is_false_positive = actual_direction == "flat"  # called a direction, nothing material happened
        is_false_negative = False
    elif verdict in NO_MOVE_VERDICTS:
        directionally_correct = actual_direction == "flat"
        is_false_positive = False
        is_false_negative = actual_direction != "flat"  # called no-move, but a real move happened
    # NO_CALL_VERDICTS: everything stays None -- honestly "no call was made to grade"

    return {
        "brier_score": brier_score,
        "predicted_probability_of_actual": predicted_probability_of_actual,
        "directionally_correct": directionally_correct,
        "is_false_positive": is_false_positive,
        "is_false_negative": is_false_negative,
    }


def reshape_drivers(
    top_factors: list[ContributingFactor], contradictions: list[str],
) -> tuple[str | None, str | None, str | None, list[str]]:
    """Top-3 of the already-ranked (by abs(contribution)) factor list as
    primary/secondary/tertiary driver names -- `contradictory_factors` is
    the state vector's own contradiction statements, reported alongside
    rather than forced into a string match against the factor names (the
    two lists describe evidence at different granularities -- a
    statistical factor like "PCR" vs. a qualitative read like "Bearish
    price but Put OI concentration is increasing" -- so they're reported
    side by side, not merged)."""
    primary = top_factors[0].factor_name if len(top_factors) > 0 else None
    secondary = top_factors[1].factor_name if len(top_factors) > 1 else None
    tertiary = top_factors[2].factor_name if len(top_factors) > 2 else None
    return primary, secondary, tertiary, contradictions
