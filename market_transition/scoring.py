"""Scores a single day using a k-nearest-neighbor "historical analog"
approach: find the K most similar historical days (by distance across the
factors the correlation study found significant), and report the empirical
outcome distribution among those analogs.

This is deliberately not a fitted model (logistic regression, etc.) --
with ~70-80 historical days total and often far fewer once split by
significant factors, a fitted model would overfit and be much harder to
explain. A transparent "here are the N most similar days and what actually
happened" approach matches the engine's own stated purpose: let the user
validate whether a pattern is genuine, not hide it behind a black box.

Explanations are template-generated (deterministic, composed only from the
numbers computed here) rather than LLM-generated, per an explicit product
decision: this tool's whole point is not overstating certainty, and a
template can never claim more than the stats support.
"""

import statistics as pystats
from dataclasses import dataclass
from datetime import datetime, timezone

from market_transition.models import (
    ContributingFactor,
    DailyTransitionRecord,
    DailyTransitionScore,
    FactorCorrelationResult,
)
from market_transition.statistics import CATEGORICAL_FACTORS, CONTINUOUS_FACTORS

DEFAULT_K = 10
MIN_ANALOGS = 3

_CONFIDENCE_WEIGHT = {"Strong": 1.0, "Moderate": 0.6, "Weak": 0.3, "Not significant": 0.0, "Insufficient data": 0.0}


@dataclass
class _WeightedFactor:
    name: str
    extractor: object
    kind: str  # "continuous" | "categorical"
    weight: float
    sign: int  # +1 if higher/matching value historically associates with reversal, else -1 (continuous only)


def _build_weighted_factors(correlations: list[FactorCorrelationResult]) -> list[_WeightedFactor]:
    by_name = {(c.factor_name, c.target): c for c in correlations}
    extractors = {name: fn for name, fn in CONTINUOUS_FACTORS}
    cat_extractors = {name: fn for name, fn in CATEGORICAL_FACTORS}

    out: list[_WeightedFactor] = []
    for name, fn in extractors.items():
        corr = by_name.get((name, "reversal"))
        weight = _CONFIDENCE_WEIGHT.get(corr.confidence_label, 0.0) if corr else 0.0
        if weight <= 0:
            continue
        sign = 1 if (corr.statistic or 0) >= 0 else -1
        out.append(_WeightedFactor(name=name, extractor=fn, kind="continuous", weight=weight, sign=sign))
    for name, fn in cat_extractors.items():
        corr = by_name.get((name, "reversal"))
        weight = _CONFIDENCE_WEIGHT.get(corr.confidence_label, 0.0) if corr else 0.0
        if weight <= 0:
            continue
        out.append(_WeightedFactor(name=name, extractor=fn, kind="categorical", weight=weight, sign=1))
    return out


def _historical_stdev(factor: _WeightedFactor, history: list[DailyTransitionRecord]) -> float | None:
    values = [factor.extractor(r) for r in history]
    values = [v for v in values if v is not None]
    if len(values) < 2:
        return None
    sd = pystats.pstdev(values)
    return sd if sd > 0 else None


def _distance(query: DailyTransitionRecord, day: DailyTransitionRecord, factors: list[_WeightedFactor], stdevs: dict[str, float | None]) -> float | None:
    total_weight = 0.0
    weighted_sum = 0.0
    for f in factors:
        qv = f.extractor(query)
        dv = f.extractor(day)
        if qv is None or dv is None:
            continue
        if f.kind == "continuous":
            sd = stdevs.get(f.name)
            if sd is None:
                continue
            component = abs(qv - dv) / sd
        else:
            component = 0.0 if qv == dv else 1.0
        weighted_sum += f.weight * component
        total_weight += f.weight
    if total_weight == 0:
        return None
    return weighted_sum / total_weight


def _find_analogs(
    query: DailyTransitionRecord, history: list[DailyTransitionRecord], factors: list[_WeightedFactor], k: int
) -> list[tuple[DailyTransitionRecord, float]]:
    stdevs = {f.name: _historical_stdev(f, history) for f in factors if f.kind == "continuous"}
    candidates = [d for d in history if d.session_date != query.session_date]
    scored = []
    for d in candidates:
        dist = _distance(query, d, factors, stdevs)
        if dist is not None:
            scored.append((d, dist))
    scored.sort(key=lambda t: t[1])
    return scored[:k]


def _confidence_from_factor_count(n_weighted_factors: int, n_analogs: int) -> str:
    if n_analogs < MIN_ANALOGS:
        return "Insufficient data"
    if n_weighted_factors >= 5:
        return "Strong"
    if n_weighted_factors >= 3:
        return "Moderate"
    if n_weighted_factors >= 1:
        return "Weak"
    return "Insufficient data"


def _top_contributing_factors(
    query: DailyTransitionRecord, history: list[DailyTransitionRecord], factors: list[_WeightedFactor], correlations: list[FactorCorrelationResult]
) -> list[ContributingFactor]:
    by_name = {(c.factor_name, c.target): c for c in correlations}
    contributions: list[ContributingFactor] = []
    for f in factors:
        today_val = f.extractor(query)
        if today_val is None:
            continue
        corr = by_name.get((f.name, "reversal"))
        if f.kind == "continuous":
            values = [f.extractor(r) for r in history if f.extractor(r) is not None]
            if len(values) < 2:
                continue
            mean = pystats.mean(values)
            sd = pystats.pstdev(values) or 1.0
            z = (today_val - mean) / sd
            contribution = f.weight * f.sign * z
            note = f"{today_val:.2f} vs. historical average {mean:.2f}"
        else:
            if corr is None or corr.category_breakdown is None:
                continue
            cat_stats = corr.category_breakdown.get(today_val)
            if cat_stats is None:
                continue
            overall_rate = pystats.mean(
                [v["reversal_rate"] for v in corr.category_breakdown.values() if "reversal_rate" in v]
            )
            contribution = f.weight * (cat_stats.get("reversal_rate", overall_rate) - overall_rate)
            note = f"{today_val} (historical reversal rate {cat_stats.get('reversal_rate', 0):.0%})"
        contributions.append(ContributingFactor(factor_name=f.name, today_value=str(today_val), note=note, contribution=contribution))

    contributions.sort(key=lambda c: -abs(c.contribution))
    return contributions[:5]


def _explanation(
    query: DailyTransitionRecord, score: float, p_reversal: float, p_continuation: float, n_analogs: int,
    similarity: float, top_factors: list[ContributingFactor], confidence: str,
) -> str:
    if n_analogs < MIN_ANALOGS or not top_factors:
        return (
            f"Not enough historically similar days or statistically significant factors yet to "
            f"produce a reliable read for {query.session_date.isoformat()} ({confidence.lower()})."
        )
    lean = "reversal" if p_reversal > p_continuation else "continuation"
    factor_summary = "; ".join(f"{c.factor_name}: {c.note}" for c in top_factors[:3])
    return (
        f"Among the {n_analogs} historically most similar days (similarity {similarity:.0%}), "
        f"{p_reversal:.0%} saw the 3pm move reverse and {p_continuation:.0%} saw it continue -- "
        f"today leans toward {lean}. Top contributing factors: {factor_summary}. "
        f"Statistical confidence: {confidence}."
    )


def score_day(
    query: DailyTransitionRecord,
    history: list[DailyTransitionRecord],
    correlations: list[FactorCorrelationResult],
    k: int = DEFAULT_K,
) -> DailyTransitionScore:
    factors = _build_weighted_factors(correlations)
    analogs = _find_analogs(query, history, factors, k)

    if len(analogs) < MIN_ANALOGS:
        return DailyTransitionScore(
            symbol=query.symbol,
            session_date=query.session_date,
            transition_risk_score=50.0,
            probability_continuation=0.5,
            probability_reversal=0.5,
            expected_volatility=0.0,
            expected_direction="flat",
            historical_similarity_score=0.0,
            top_contributing_factors=[],
            statistical_confidence="Insufficient data",
            explanation=_explanation(query, 50.0, 0.5, 0.5, len(analogs), 0.0, [], "Insufficient data"),
            computed_at=datetime.now(timezone.utc),
        )

    analog_days = [d for d, _ in analogs]
    avg_distance = pystats.mean(dist for _, dist in analogs)
    similarity = 1 / (1 + avg_distance)

    directional = [d for d in analog_days if d.outcome.outcome != "neutral"]
    if directional:
        reversal_count = sum(1 for d in directional if d.outcome.outcome == "reversal")
        p_reversal = reversal_count / len(directional)
    else:
        p_reversal = 0.5
    p_continuation = 1 - p_reversal

    expected_volatility = pystats.mean(d.outcome.outcome_magnitude for d in analog_days)

    # What direction did price actually move from 3:01pm to close among the
    # analogs -- the sign of post_transition_move itself, regardless of
    # which way the 3pm transition went or whether it was later labeled a
    # reversal/continuation (a "reversal" analog still has a real, directional
    # post-3pm move; excluding it here would silently discard that signal).
    up_count = sum(1 for d in analog_days if d.outcome.post_transition_move > 0)
    down_count = sum(1 for d in analog_days if d.outcome.post_transition_move < 0)
    other = len(analog_days) - up_count - down_count
    if up_count > down_count and up_count > other:
        expected_direction = "up"
    elif down_count > up_count and down_count > other:
        expected_direction = "down"
    else:
        expected_direction = "flat"

    risk_score = 50 + (p_reversal - 0.5) * 100 * min(similarity * 2, 1.0)
    risk_score = max(0.0, min(100.0, risk_score))

    top_factors = _top_contributing_factors(query, history, factors, correlations)
    confidence = _confidence_from_factor_count(len(factors), len(analogs))
    explanation = _explanation(query, risk_score, p_reversal, p_continuation, len(analogs), similarity, top_factors, confidence)

    return DailyTransitionScore(
        symbol=query.symbol,
        session_date=query.session_date,
        transition_risk_score=round(risk_score, 1),
        probability_continuation=round(p_continuation, 3),
        probability_reversal=round(p_reversal, 3),
        expected_volatility=round(expected_volatility, 2),
        expected_direction=expected_direction,
        historical_similarity_score=round(similarity, 3),
        top_contributing_factors=top_factors,
        statistical_confidence=confidence,
        explanation=explanation,
        computed_at=datetime.now(timezone.utc),
    )
