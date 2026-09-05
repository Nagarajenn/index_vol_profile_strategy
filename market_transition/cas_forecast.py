"""Leakage-safe 3PM Transition Forecast (Phase 7B).

Generates a forecast at each of 7 checkpoints (14:30/35/40/45/50/55/59)
using ONLY information available at that instant, then -- separately, by
the caller comparing against the day's actual mti_cas_daily_transitions
row -- graded against what actually happened. This module itself never
reads anything past `checkpoint_time`.

Reuses market_transition/scoring.py's find_analogs/score_day (generic
weighted k-NN over DailyTransitionRecord) UNMODIFIED for the
reversal/continuation pair, and adds one new, small extension: a
magnitude-tier vote over the same analog list (weighted by the same
per-analog distance find_analogs already returns), reading each analog's
already-computed Phase 7A transition_type/magnitude_tier -- closing the
loop between the two phases rather than fitting a second model.
"""

from dataclasses import dataclass, field
from datetime import date, time

import pandas as pd

from market_transition.feature_extraction import compute_pre_window_features
from market_transition.models import (
    ContributingFactor,
    DailyTransitionRecord,
    ExpiryType,
    FactorCorrelationResult,
    TransitionOutcome,
)
from market_transition.scoring import MIN_ANALOGS, find_analogs, score_day
from market_transition.transition_state import build_market_state_vector
from market_transition.verdict import (
    classify_transition_risk_tier,
    compute_expected_move_range,
    compute_verdict,
    percentile_rank,
    reshape_drivers,
)

FORECAST_CHECKPOINTS: list[time] = [
    time(14, 30), time(14, 35), time(14, 40), time(14, 45), time(14, 50), time(14, 55), time(14, 59),
]


@dataclass
class TransitionForecast:
    checkpoint_time: str  # "14:30".."14:59"
    probability_no_material_transition: float
    probability_large_up: float
    probability_large_down: float
    probability_reversal: float
    probability_continuation: float
    n_analogs: int
    confidence_label: str
    top_contributing_factors: list[ContributingFactor]
    historical_similarity_score: float
    # Phase 9C (spec Parts 1, 9-11): the unified "is the market more likely
    # to move UP, DOWN, or stay within a normal range" read -- additive,
    # safe defaults so every existing caller/test that builds a
    # TransitionForecast directly keeps working unchanged.
    probability_up: float = 0.0
    probability_down: float = 0.0
    expected_move_low: float | None = None
    expected_move_high: float | None = None
    expected_move_pct: float | None = None
    expected_move_percentile: float | None = None
    transition_risk_tier: str | None = None  # NORMAL/MODERATE/LARGE/EXTREME -- Phase 7A's MagnitudeTier vocabulary
    verdict: str = "INSUFFICIENT_EVIDENCE"
    primary_driver: str | None = None
    secondary_driver: str | None = None
    tertiary_driver: str | None = None
    contradictory_factors: list[str] = field(default_factory=list)
    option_bias: str | None = None


def _magnitude_probabilities(
    analogs: list[tuple[DailyTransitionRecord, float]], cas_by_date: dict[date, dict]
) -> tuple[float, float, float]:
    """Weighted vote (weight = 1/(1+distance), same similarity-to-weight
    mapping scoring.py already uses) of each analog day's Phase 7A
    transition_type/magnitude_tier -> (p_no_material, p_large_up, p_large_down).
    "Large" means magnitude_tier is LARGE/EXTREME; direction comes from
    post_direction -- the two Phase 7A dimensions read together, not a new
    third model. Analog days with no matching CAS row (shouldn't happen in
    practice since analogs are drawn from the same CAS-windowed history,
    but handled defensively) are skipped, not treated as zero-weight votes
    for "no material"."""
    weights = {"no_material": 0.0, "large_up": 0.0, "large_down": 0.0}
    total = 0.0
    for record, dist in analogs:
        cas_row = cas_by_date.get(record.session_date)
        if cas_row is None:
            continue
        w = 1.0 / (1.0 + dist)
        total += w
        is_large = cas_row.get("magnitude_tier") in ("LARGE", "EXTREME")
        if is_large and cas_row.get("post_direction") == "up":
            weights["large_up"] += w
        elif is_large and cas_row.get("post_direction") == "down":
            weights["large_down"] += w
        else:
            weights["no_material"] += w
    if total == 0:
        return 1 / 3, 1 / 3, 1 / 3  # no usable analogs -- an honest even split, paired with confidence="Insufficient data" by the caller
    return weights["no_material"] / total, weights["large_up"] / total, weights["large_down"] / total


def build_transition_forecast(
    checkpoint_time: time,
    symbol: str,
    session_date: date,
    today_candles: pd.DataFrame,
    prior_day_candles: pd.DataFrame | None,
    historical_by_date: dict[date, pd.DataFrame],
    history: list[DailyTransitionRecord],
    cas_history: list[dict],  # rows shaped like db.reader.load_cas_daily_transitions()'s return
    correlations: list[FactorCorrelationResult],
    bin_size: float,
    expiry_type: ExpiryType | None,
    k: int = 10,
    pre_window=None,  # market_transition.cas_windows.PreTransitionWindow ending at/near checkpoint_time, for the state-vector/contradiction read -- optional, Phase 9C
    option_bias: str | None = None,  # option_chain.snapshot_features.classify_option_positioning's read at/before checkpoint_time -- optional, Phase 9C
    atr_14: float | None = None,  # for transition_risk_tier -- same day-level ATR Phase 7A already computes elsewhere
) -> TransitionForecast | None:
    """Builds the leakage-safe query (compute_pre_window_features clamped to
    `checkpoint_time`) and scores it against `history`/`correlations` --
    both of which the caller must have already restricted to strictly-past
    days, same discipline as every other checkpoint in this package.
    Returns None only if there isn't even enough same-day data through
    `checkpoint_time` to build a query at all (e.g. session hasn't reached
    that time on a partial/interrupted day)."""
    features = compute_pre_window_features(
        today_candles, prior_day_candles, historical_by_date, bin_size, expiry_type, session_date,
        pre_window_end=checkpoint_time,
    )
    if features is None:
        return None

    # A placeholder outcome -- score_day/find_analogs never read the
    # query's own .outcome, only history days' outcomes (same convention
    # live_advisor.build_live_query already relies on).
    placeholder_outcome = TransitionOutcome(
        close_1459=0.0, close_1501=0.0, market_close=0.0,
        transition_move=0.0, transition_direction="flat", post_transition_move=0.0,
        outcome="neutral", outcome_magnitude=0.0,
    )
    query = DailyTransitionRecord(symbol=symbol, session_date=session_date, features=features, outcome=placeholder_outcome)

    cas_by_date = {r["session_date"]: r for r in cas_history}
    analogs = find_analogs(query, history, correlations, k=k)

    # The magnitude-tier vote can only ever use analogs that have a Phase 7A
    # transition_type/magnitude_tier -- i.e. CAS-era days. Searching the SAME
    # unrestricted `history` (~4 months, mostly pre-CAS) for this vote would
    # waste most of the k slots on days find_analogs correctly ranks as
    # similar but that _magnitude_probabilities can never use, silently
    # degenerating to an even split almost every time. A second, separate
    # find_analogs call restricted to days that actually have a cas_by_date
    # entry makes the (currently thin, ~20-day) post-CAS signal count for
    # something instead of getting crowded out.
    cas_era_history = [r for r in history if r.session_date in cas_by_date]
    magnitude_analogs = find_analogs(query, cas_era_history, correlations, k=k) if cas_era_history else []
    p_no_material, p_large_up, p_large_down = _magnitude_probabilities(magnitude_analogs, cas_by_date)

    score = score_day(query, history, correlations, k=k)
    confidence = score.statistical_confidence
    if len(analogs) < MIN_ANALOGS:
        confidence = "Insufficient data"

    # Phase 9C: unified UP/DOWN/NO-MATERIAL-MOVE verdict, expected-move
    # range, transition risk tier, and driver reshaping -- all additive
    # synthesis over what's already computed above, per market_transition/
    # verdict.py and transition_state.py.
    contradictions: list[str] = []
    if pre_window is not None:
        contradictions = build_market_state_vector(pre_window, option_bias=option_bias).contradictions

    signed_moves = [d.outcome.post_transition_move for d, _ in analogs if d.outcome.post_transition_move is not None]
    expected_move_low, expected_move_high = compute_expected_move_range(signed_moves)
    expected_move_mid = ((expected_move_low + expected_move_high) / 2) if (expected_move_low is not None and expected_move_high is not None) else None

    baseline_price = None
    same_day_before_cutoff = today_candles[today_candles["timestamp"].dt.time <= checkpoint_time]
    if not same_day_before_cutoff.empty:
        baseline_price = float(same_day_before_cutoff["close"].iloc[-1])
    expected_move_pct = (expected_move_mid / baseline_price * 100) if (expected_move_mid is not None and baseline_price) else None

    all_magnitudes = [abs(d.outcome.post_transition_move) for d in history if d.outcome.post_transition_move is not None]
    expected_move_percentile = percentile_rank(abs(expected_move_mid), all_magnitudes) if expected_move_mid is not None else None

    transition_risk_tier = classify_transition_risk_tier(expected_move_mid, atr_14)
    verdict = compute_verdict(len(analogs), score.probability_up, score.probability_down, score.probability_flat, contradictions)
    primary_driver, secondary_driver, tertiary_driver, contradictory_factors = reshape_drivers(score.top_contributing_factors, contradictions)

    return TransitionForecast(
        checkpoint_time=f"{checkpoint_time:%H:%M}",
        probability_no_material_transition=round(p_no_material, 3),
        probability_large_up=round(p_large_up, 3),
        probability_large_down=round(p_large_down, 3),
        probability_reversal=score.probability_reversal,
        probability_continuation=score.probability_continuation,
        n_analogs=len(analogs),
        confidence_label=confidence,
        top_contributing_factors=score.top_contributing_factors,
        historical_similarity_score=score.historical_similarity_score,
        probability_up=score.probability_up,
        probability_down=score.probability_down,
        expected_move_low=expected_move_low,
        expected_move_high=expected_move_high,
        expected_move_pct=round(expected_move_pct, 3) if expected_move_pct is not None else None,
        expected_move_percentile=expected_move_percentile,
        transition_risk_tier=transition_risk_tier,
        verdict=verdict,
        primary_driver=primary_driver,
        secondary_driver=secondary_driver,
        tertiary_driver=tertiary_driver,
        contradictory_factors=contradictory_factors,
        option_bias=option_bias,
    )
