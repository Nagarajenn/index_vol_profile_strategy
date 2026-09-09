"""Milestone 11C: the opportunity score, NO-TRADE gates, candidate
selection, and comparison baselines. RESEARCH ONLY -- no order placement,
no live trading, nothing here calls any Dhan order API.

Every threshold/formula below is fixed BEFORE Validation or Test is
evaluated (fit only from Training-tier data where a fit is involved) and
applied identically across all three tiers -- see scripts/run_milestone11c.py.
"""

from dataclasses import dataclass
from typing import Literal

from market_transition.option_features_11c import CandidateOption

Direction = Literal["up", "down"]

# ---------------------------------------------------------------------
# Documented, fixed assumptions (never tuned against Validation/Test)
# ---------------------------------------------------------------------

MINUTES_PER_TRADING_DAY = 375  # 09:15-15:30 IST
HOLDING_MINUTES = 15  # 14:59 entry -> 15:14/15:15 exit horizon

# Theta is assumed to already be expressed on a standard per-trading-day
# basis (the conventional options-greek unit) -- scaled linearly to the
# ~15-minute holding window. If Dhan's own theta convention differs, this
# estimate is indicative only; flagged explicitly in the Limitations
# section of the Milestone 11C report, not silently corrected.
def estimate_theta_cost_15min(theta: float | None) -> float | None:
    if theta is None:
        return None
    return abs(theta) * (HOLDING_MINUTES / MINUTES_PER_TRADING_DAY)


# Data-quality / liquidity gate -- a starting, documented default (not
# fit/tuned on any tier). A wider spread than this makes the round-trip
# cost dominate any plausible 15-minute move for an ATM-ish option.
SPREAD_PCT_MAX = 5.0


def fit_expected_move_points(training_rows: list[dict], symbol: str, field: str = "actual_15m_point_move") -> float | None:
    """Median absolute realized 15-minute point move for `symbol`, from
    TRAINING rows only. This is a symbol-level, direction-agnostic
    constant -- NOT a per-day forecast (this milestone has no calibrated
    per-day expected-move model; see the 11C report's 'Expected Move'
    section for the explicit limitation this represents)."""
    values = [abs(r[field]) for r in training_rows if r.get("symbol") == symbol and r.get(field) is not None]
    if not values:
        return None
    values.sort()
    n = len(values)
    mid = n // 2
    return values[mid] if n % 2 else (values[mid - 1] + values[mid]) / 2


@dataclass
class ScoredCandidate:
    candidate: CandidateOption
    expected_benefit: float | None
    theta_cost: float | None
    spread_cost: float | None
    score: float | None
    eligible: bool
    rejection_reason: str | None


def compute_opportunity_score(candidate: CandidateOption, expected_move_points: float | None) -> ScoredCandidate:
    """expected_benefit = |delta| * expected_move_points (linear payoff
    approximation) minus spread cost and a 15-minute theta-decay estimate.
    Deterministic, documented, no look-ahead: uses only fields already
    present on `candidate` (all <=14:59) plus the Training-fit
    `expected_move_points` constant."""
    if candidate.data_quality == "MISSING_QUOTE" or candidate.ask is None or not candidate.ask:
        return ScoredCandidate(candidate, None, None, None, None, False, "MISSING_QUOTE")
    if candidate.spread_pct is not None and candidate.spread_pct > SPREAD_PCT_MAX:
        return ScoredCandidate(candidate, None, None, candidate.spread, None, False, "SPREAD_TOO_WIDE")
    if candidate.delta is None or expected_move_points is None:
        return ScoredCandidate(candidate, None, None, candidate.spread, None, False, "MISSING_SCORING_INPUT")

    theta_cost = estimate_theta_cost_15min(candidate.theta) or 0.0
    spread_cost = candidate.spread or 0.0
    expected_benefit = abs(candidate.delta) * expected_move_points
    score = expected_benefit - spread_cost - theta_cost
    return ScoredCandidate(candidate, expected_benefit, theta_cost, spread_cost, score, True, None)


@dataclass
class SelectionResult:
    selected: CandidateOption | None
    scored: ScoredCandidate | None
    reason: str  # "SELECTED" or a NO-TRADE reason
    ranked: list[ScoredCandidate]


def _direction_leg(direction_state: Direction) -> str:
    return "CE" if direction_state == "up" else "PE"


def select_candidate(
    candidates: list[CandidateOption], universe_rejection_reason: str | None,
    direction_state: Direction | None, expected_move_points: float | None,
) -> SelectionResult:
    """The full 11C decision procedure (Section 'OPTION CANDIDATE RANKING'):
    construct -> filter to the direction-matching leg -> score -> rank ->
    select top if score>0, else NO TRADE. Every gate is checked in a fixed
    order so the specific NO-TRADE reason is always traceable."""
    if universe_rejection_reason is not None:
        return SelectionResult(None, None, f"NO_TRADE_DATA_QUALITY_{universe_rejection_reason}", [])
    if direction_state is None:
        return SelectionResult(None, None, "NO_TRADE_NO_CLEAR_EDGE", [])
    if not candidates:
        return SelectionResult(None, None, "NO_TRADE_EMPTY_UNIVERSE", [])

    leg = _direction_leg(direction_state)
    same_leg = [c for c in candidates if c.option_type == leg]
    scored = [compute_opportunity_score(c, expected_move_points) for c in same_leg]
    eligible = [s for s in scored if s.eligible and s.score is not None]

    if not eligible:
        return SelectionResult(None, None, "NO_TRADE_NO_ELIGIBLE_CANDIDATE", scored)

    ranked = sorted(eligible, key=lambda s: (-s.score, s.candidate.strike))
    top = ranked[0]
    if top.score is None or top.score <= 0:
        return SelectionResult(None, top, "NO_TRADE_EXPECTED_BENEFIT_NONPOSITIVE", ranked)

    return SelectionResult(top.candidate, top, "SELECTED", ranked)


# ---------------------------------------------------------------------
# Comparison baselines -- ALWAYS pick a candidate (never NO TRADE), so
# the opportunity engine's NO-TRADE discipline can be compared against
# "always trade" alternatives, per the spec's explicit requirement.
# ---------------------------------------------------------------------

def select_atm_baseline(candidates: list[CandidateOption], direction_state: Direction | None) -> CandidateOption | None:
    if direction_state is None:
        return None
    leg = _direction_leg(direction_state)
    matches = [c for c in candidates if c.option_type == leg and c.atm_offset == 0 and c.ask]
    return matches[0] if matches else None


def _nearest_offset_baseline(candidates: list[CandidateOption], direction_state: Direction | None, want_otm: bool) -> CandidateOption | None:
    if direction_state is None:
        return None
    leg = _direction_leg(direction_state)
    # For CE: OTM = positive offset, ITM = negative offset. For PE: reversed.
    otm_sign = 1 if leg == "CE" else -1
    target_sign = otm_sign if want_otm else -otm_sign
    same_leg = [c for c in candidates if c.option_type == leg and c.ask]
    same_side = [c for c in same_leg if (c.atm_offset * target_sign) > 0]
    if not same_side:
        return None
    return min(same_side, key=lambda c: abs(c.atm_offset))


def select_nearest_otm_baseline(candidates: list[CandidateOption], direction_state: Direction | None) -> CandidateOption | None:
    return _nearest_offset_baseline(candidates, direction_state, want_otm=True)


def select_nearest_itm_baseline(candidates: list[CandidateOption], direction_state: Direction | None) -> CandidateOption | None:
    return _nearest_offset_baseline(candidates, direction_state, want_otm=False)
