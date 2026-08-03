"""Live Market Transition Advisor: consumes today's in-progress 2:00-3:01pm
session and compares it against the stored historical Market Transition
Intelligence database (mti_daily_transitions / mti_factor_correlations,
produced by scripts/run_market_transition_research.py) to produce a
real-time advisory before the 3pm event occurs.

Never a trading signal -- output is capped to a small, explicit vocabulary
(Observe / Low / Medium / High / Very High transition risk, plus a
confidence label) and the module never issues buy/sell language. Entirely
independent of the trading decision engine: this reads the historical MTI
database, it never writes to it or to any table the strategy engine reads
(confidence_score, trend_classifier, decision_card, institutional_bias).

Reuses scoring.py's k-NN historical-analog engine wholesale (find_analogs,
score_day) rather than re-implementing similarity/probability logic --
the only genuinely new work here is: (1) computing today's features from a
partial, still-forming session via feature_extraction.compute_pre_window_features,
(2) the transition-stage/timing/risk-level/estimated-move outputs specific
to a live advisory, and (3) trader-language (not statistical-jargon)
explanations.
"""

import statistics as pystats
from datetime import date, datetime, time

import pandas as pd

from market_transition.feature_extraction import PRE_WINDOW_END, PRE_WINDOW_START, TRANSITION_END, TRANSITION_START, compute_pre_window_features
from market_transition.models import (
    ContributingFactor,
    DailyTransitionRecord,
    ExpiryType,
    FactorCorrelationResult,
    LiveAdvisory,
    MostSimilarDay,
    PreWindowFeatures,
    TransitionOutcome,
    TransitionRiskLevel,
    TransitionStage,
    TransitionTimingEstimate,
)
from market_transition.scoring import DEFAULT_K, MIN_ANALOGS, find_analogs, score_day

# How long after the transition window the advisor keeps reporting
# follow-through (has the predicted reversal/continuation actually
# happened) before considering the session's transition read "complete" --
# through the rest of the trading session (15:40 close, per NSE's F&O
# session extension effective 2026-08-03 -- was 15:30 before that), not
# just a short window after 15:01, so the read stays visible rather than
# reverting to "not enough data" the instant the clock crosses 3:01pm.
FOLLOW_THROUGH_END = time(15, 40)

# Onset detection for "Expected Timing of Transition": a candle counts as
# the transition's onset once price has moved at least this fraction of the
# analog's eventual post-transition move, in the matching direction.
ONSET_FRACTION = 0.4
MIN_ONSET_MOVE_POINTS = 1.0  # ignore near-flat analogs entirely


def determine_transition_stage(now_time: time) -> TransitionStage:
    if now_time < PRE_WINDOW_START:
        return "Not Yet Active"
    if now_time <= PRE_WINDOW_END:
        return "Pre-Transition Monitoring"
    if now_time <= TRANSITION_END:
        return "Transition Window"
    if now_time <= FOLLOW_THROUGH_END:
        return "Post-Transition Follow-Through"
    return "Session Complete"


def is_advisor_active(now_time: time) -> bool:
    """Produces a read from 2:00pm through the rest of the session (15:30
    close) -- outside that it's dormant (still shows the stage, just no
    score). The score itself is computed once, from the frozen 14:00-14:59
    pre-window (see build_live_query's clamping), so it doesn't keep
    changing after 3:01pm -- it's retained as the pre-transition read for
    the trader to judge against what actually happened, not re-forecast."""
    return PRE_WINDOW_START <= now_time <= FOLLOW_THROUGH_END


def build_live_query(
    symbol: str,
    session_date: date,
    today_candles: pd.DataFrame,
    prior_day_candles: pd.DataFrame | None,
    historical_by_date: dict[date, pd.DataFrame],
    bin_size: float,
    expiry_type: ExpiryType | None,
    now_time: time,
) -> DailyTransitionRecord | None:
    """Builds a query record from today's partial session, using whatever
    of the 14:00-14:59 pre-window has elapsed as of `now_time` (clamped so
    it never looks past 14:59 -- the pre-window features always describe
    "before the 3pm event", never into or past it). Returns None before
    14:00, since there's no pre-window data to describe yet.
    """
    if now_time < PRE_WINDOW_START:
        return None
    cutoff = min(now_time, PRE_WINDOW_END)

    features = compute_pre_window_features(
        today_candles, prior_day_candles, historical_by_date, bin_size, expiry_type, session_date, cutoff
    )
    if features is None:
        return None

    # score_day() never reads query.outcome (only history days' outcomes),
    # so this placeholder is inert -- required only to satisfy the shared
    # DailyTransitionRecord shape.
    placeholder_outcome = TransitionOutcome(
        close_1459=0, close_1501=0, market_close=0, transition_move=0,
        transition_direction="flat", post_transition_move=0, outcome="neutral", outcome_magnitude=0,
    )
    return DailyTransitionRecord(symbol=symbol, session_date=session_date, features=features, outcome=placeholder_outcome)


def _target_sign(move: float) -> int:
    return 1 if move > 0 else -1 if move < 0 else 0


def estimate_transition_timing(
    analogs: list[tuple[DailyTransitionRecord, float]], analog_candles: dict[date, pd.DataFrame]
) -> TransitionTimingEstimate:
    """For each analog day, finds the first candle (within that day's
    supplied padded window, e.g. ~14:50-15:10) where price has moved at
    least ONSET_FRACTION of the analog's eventual post-transition move in
    the matching direction -- an approximation of when the transition
    actually started, distinct from the fixed 15:00-15:01 window used to
    MEASURE it. Analogs with a near-flat outcome or no window supplied are
    skipped; the estimate needs at least 3 to be reported.
    """
    onset_times: list[time] = []
    for record, _ in analogs:
        candles = analog_candles.get(record.session_date)
        if candles is None or candles.empty:
            continue
        move = record.outcome.post_transition_move
        if abs(move) < MIN_ONSET_MOVE_POINTS:
            continue
        target_sign = _target_sign(move)
        threshold = abs(move) * ONSET_FRACTION
        anchor = record.outcome.close_1459
        for row in candles.itertuples(index=False):
            delta = row.close - anchor
            if _target_sign(delta) == target_sign and abs(delta) >= threshold:
                onset_times.append(row.timestamp.time())
                break

    if len(onset_times) < 3:
        return TransitionTimingEstimate(
            earliest=None, latest=None, n_analogs_with_onset=len(onset_times),
            note="Not enough analog data to estimate timing precisely -- expect the move around the 3:00 PM window.",
        )

    earliest, latest = min(onset_times), max(onset_times)
    return TransitionTimingEstimate(
        earliest=earliest, latest=latest, n_analogs_with_onset=len(onset_times),
        note=f"Based on {len(onset_times)} of {len(analogs)} analogs with a detectable onset.",
    )


def compute_estimated_move(analog_days: list[DailyTransitionRecord]) -> float:
    """Signed mean of post_transition_move across the analogs -- a net
    directional point estimate, distinct from expected_volatility (the
    unsigned average magnitude)."""
    if not analog_days:
        return 0.0
    return round(pystats.mean(d.outcome.post_transition_move for d in analog_days), 2)


def compute_transition_risk_level(
    probability_reversal: float, historical_similarity_score: float, statistical_confidence: str, n_analogs: int, stage: TransitionStage
) -> TransitionRiskLevel:
    """Heuristic composite, not a statistically derived measure (same
    "reasonable, documented heuristic" spirit as Profile Shape/Opening Type
    elsewhere in this codebase): how decisively the analogs lean toward
    reversal-or-continuation, weighted by how tightly today actually
    matches them. Deliberately never reads as "Observe" only for lack of
    data -- also downgrades to it outside the active window, since a risk
    read before/after the transition window isn't meaningful.
    """
    if stage not in ("Pre-Transition Monitoring", "Transition Window", "Post-Transition Follow-Through"):
        return "Observe"
    if statistical_confidence == "Insufficient data" or n_analogs < MIN_ANALOGS:
        return "Observe"

    decisiveness = abs(probability_reversal - 0.5) * 2  # 0..1
    composite = 0.6 * decisiveness + 0.4 * historical_similarity_score
    if composite >= 0.75:
        return "Very High"
    if composite >= 0.55:
        return "High"
    if composite >= 0.35:
        return "Medium"
    return "Low"


def _format_time(t: time) -> str:
    # "%-I" (no leading zero) is Unix-only and errors on Windows -- strip
    # the leading zero manually instead, portable everywhere.
    return t.strftime("%I:%M %p").lstrip("0")


def _factor_phrase(f: ContributingFactor) -> str:
    lean = "favoring reversal" if f.contribution > 0 else "favoring continuation"
    return f"{f.factor_name.lower()} at {f.today_value} ({lean})"


def _news_phrase(news_risk_score: int | None) -> str | None:
    if news_risk_score is None:
        return None
    word = "low" if news_risk_score < 40 else "moderate" if news_risk_score < 70 else "elevated"
    return f"News risk remains {word} ({news_risk_score}/100)."


def _build_explanation(
    n_analogs: int,
    reversal_count: int,
    probability_reversal: float,
    top_factors: list[ContributingFactor],
    timing: TransitionTimingEstimate | None,
    risk_level: TransitionRiskLevel,
    news_risk_score: int | None,
    stage: TransitionStage,
) -> str:
    if n_analogs < MIN_ANALOGS:
        return "Not enough historically similar sessions yet to produce a reliable live read."

    factor_phrases = "; ".join(_factor_phrase(f) for f in top_factors[:2])
    timing_phrase = (
        f"between {_format_time(timing.earliest)} and {_format_time(timing.latest)}"
        if timing and timing.earliest and timing.latest
        else "around the 3:00 PM window"
    )

    parts = []
    if factor_phrases:
        parts.append(f"Today's market currently resembles {n_analogs} previous sessions where {factor_phrases}.")
    else:
        parts.append(f"Today's market currently resembles {n_analogs} previous similar sessions.")

    if reversal_count > 0:
        parts.append(f"In {reversal_count} of those sessions the market reversed {timing_phrase}.")
    else:
        parts.append("None of those sessions saw a reversal -- the move typically continued.")

    parts.append(f"Current reversal probability is estimated at {probability_reversal:.0%}.")

    news_phrase = _news_phrase(news_risk_score)
    if news_phrase:
        parts.append(news_phrase)

    if stage == "Post-Transition Follow-Through":
        parts.append("This reflects the pre-transition read (frozen at 2:59 PM) -- compare it against how price actually moved.")
    elif risk_level in ("High", "Very High"):
        parts.append("Consider tightening stops before the transition window.")
    elif risk_level == "Medium":
        parts.append("Stay alert as the transition window approaches.")
    elif risk_level == "Low":
        parts.append("No strong transition signal detected yet.")

    return " ".join(parts)


def build_live_advisory(
    query: DailyTransitionRecord,
    history: list[DailyTransitionRecord],
    correlations: list[FactorCorrelationResult],
    now: datetime,
    analog_candles: dict[date, pd.DataFrame] | None = None,
    institutional_bias_label: str | None = None,
    news_risk_score: int | None = None,
    news_sentiment: str | None = None,
    k: int = DEFAULT_K,
) -> LiveAdvisory:
    # `now` must already be IST-localized -- .time() extracts whatever
    # wall-clock values the datetime carries, aware or not.
    now_time = now.time()
    stage = determine_transition_stage(now_time)

    base_score = score_day(query, history, correlations, k)
    analogs = find_analogs(query, history, correlations, k)
    analog_days = [d for d, _ in analogs]

    timing = estimate_transition_timing(analogs, analog_candles or {}) if analogs else None
    estimated_move = compute_estimated_move(analog_days)
    risk_level = compute_transition_risk_level(
        base_score.probability_reversal, base_score.historical_similarity_score, base_score.statistical_confidence, len(analogs), stage
    )

    reversal_count = sum(1 for d in analog_days if d.outcome.outcome == "reversal")
    explanation = _build_explanation(
        len(analogs), reversal_count, base_score.probability_reversal, base_score.top_contributing_factors,
        timing, risk_level, news_risk_score, stage,
    )

    most_similar = [
        MostSimilarDay(
            session_date=d.session_date, distance=round(dist, 3), similarity=round(1 / (1 + dist), 3),
            outcome=d.outcome.outcome, transition_direction=d.outcome.transition_direction,
        )
        for d, dist in analogs
    ]

    return LiveAdvisory(
        symbol=query.symbol,
        session_date=query.session_date,
        as_of=now,
        stage=stage,
        historical_similarity_score=base_score.historical_similarity_score,
        most_similar_days=most_similar,
        expected_direction=base_score.expected_direction,
        probability_continuation=base_score.probability_continuation,
        probability_reversal=base_score.probability_reversal,
        expected_volatility=base_score.expected_volatility,
        expected_timing=timing,
        estimated_move=estimated_move,
        risk_level=risk_level,
        statistical_confidence=base_score.statistical_confidence,
        top_contributing_factors=base_score.top_contributing_factors,
        institutional_bias_label=institutional_bias_label,
        news_risk_score=news_risk_score,
        news_sentiment=news_sentiment,
        explanation=explanation,
    )
