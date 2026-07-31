"""Discovers correlations between pre-3pm features and the 3pm-transition
outcome, across every extracted historical day -- the "discover rather than
assume" core of the engine.

Every factor is tested against two targets:
  - "reversal": does the factor associate with the transition reversing
    (vs. continuing)? Neutral-outcome days are excluded from this target --
    they're "no significant move" days, not evidence either way.
  - "magnitude": does the factor associate with how large the post-3pm
    move is (a "breakout" framing)? All days with a valid outcome are used.

Continuous factors use point-biserial correlation (vs. reversal) and
Pearson correlation (vs. magnitude). Categorical factors use a chi-square
test on the reversal-rate-per-category contingency table, and Kruskal-Wallis
on magnitude across categories.

`confidence_label` requires BOTH statistical significance AND a minimum
sample size -- a low p-value from 8 days is not "Strong" evidence, it's
noise. This is deliberately conservative: the whole point of this engine is
to let the user validate whether a pattern is genuine or anecdotal.
"""

from collections import defaultdict
from typing import Callable

from scipy import stats

from market_transition.models import ConfidenceLabel, DailyTransitionRecord, FactorCorrelationResult

MIN_N_FOR_CONFIDENCE = 20


def _confidence_label(n: int, p_value: float | None) -> ConfidenceLabel:
    if p_value is None or n < MIN_N_FOR_CONFIDENCE:
        return "Insufficient data"
    if p_value < 0.01:
        return "Strong"
    if p_value < 0.05:
        return "Moderate"
    if p_value < 0.10:
        return "Weak"
    return "Not significant"


def _is_reversal_records(records: list[DailyTransitionRecord]) -> list[tuple[DailyTransitionRecord, int]]:
    """(record, is_reversal) pairs, excluding neutral-outcome days."""
    out = []
    for r in records:
        if r.outcome.outcome == "reversal":
            out.append((r, 1))
        elif r.outcome.outcome == "continuation":
            out.append((r, 0))
    return out


def correlate_continuous_factor(
    factor_name: str,
    extractor: Callable[[DailyTransitionRecord], float | None],
    records: list[DailyTransitionRecord],
) -> tuple[FactorCorrelationResult, FactorCorrelationResult]:
    """Returns (vs_reversal, vs_magnitude) results for one continuous factor."""
    reversal_pairs = [(extractor(r), is_rev) for r, is_rev in _is_reversal_records(records) if extractor(r) is not None]
    n_rev = len(reversal_pairs)
    if n_rev >= 3 and len({y for _, y in reversal_pairs}) == 2:
        xs = [p[0] for p in reversal_pairs]
        ys = [p[1] for p in reversal_pairs]
        stat, p = stats.pointbiserialr(ys, xs)
        note = f"{'Higher' if stat > 0 else 'Lower'} values associate with reversal (r={stat:.2f}, n={n_rev})."
    else:
        stat, p = None, None
        note = "Not enough directional days with this factor available."
    vs_reversal = FactorCorrelationResult(
        factor_name=factor_name, factor_type="continuous", target="reversal", n=n_rev,
        statistic=stat, p_value=p, confidence_label=_confidence_label(n_rev, p), direction_note=note,
    )

    magnitude_pairs = [(extractor(r), r.outcome.outcome_magnitude) for r in records if extractor(r) is not None]
    n_mag = len(magnitude_pairs)
    if n_mag >= 3:
        xs = [p[0] for p in magnitude_pairs]
        ys = [p[1] for p in magnitude_pairs]
        stat_m, p_m = stats.pearsonr(xs, ys)
        note_m = f"{'Higher' if stat_m > 0 else 'Lower'} values associate with larger post-3pm moves (r={stat_m:.2f}, n={n_mag})."
    else:
        stat_m, p_m = None, None
        note_m = "Not enough days with this factor available."
    vs_magnitude = FactorCorrelationResult(
        factor_name=factor_name, factor_type="continuous", target="magnitude", n=n_mag,
        statistic=stat_m, p_value=p_m, confidence_label=_confidence_label(n_mag, p_m), direction_note=note_m,
    )
    return vs_reversal, vs_magnitude


def correlate_categorical_factor(
    factor_name: str,
    extractor: Callable[[DailyTransitionRecord], str | None],
    records: list[DailyTransitionRecord],
) -> tuple[FactorCorrelationResult, FactorCorrelationResult]:
    """Returns (vs_reversal, vs_magnitude) results for one categorical factor."""
    by_category: dict[str, list[int]] = defaultdict(list)  # category -> [is_reversal, ...]
    for r, is_rev in _is_reversal_records(records):
        cat = extractor(r)
        if cat is not None:
            by_category[cat].append(is_rev)

    n_rev = sum(len(v) for v in by_category.values())
    breakdown = {
        cat: {"n": len(vals), "reversal_rate": round(sum(vals) / len(vals), 3)}
        for cat, vals in by_category.items()
        if vals
    }
    if len(by_category) >= 2 and n_rev >= 3:
        table = [[sum(vals), len(vals) - sum(vals)] for vals in by_category.values()]
        try:
            chi2, p, _, _ = stats.chi2_contingency(table)
        except ValueError:
            chi2, p = None, None
        top = max(breakdown.items(), key=lambda kv: kv[1]["reversal_rate"]) if breakdown else None
        note = f"Highest reversal rate: {top[0]} ({top[1]['reversal_rate']:.0%}, n={top[1]['n']})." if top else "No category breakdown available."
    else:
        chi2, p = None, None
        note = "Not enough categories/days with this factor available."
    vs_reversal = FactorCorrelationResult(
        factor_name=factor_name, factor_type="categorical", target="reversal", n=n_rev,
        statistic=chi2, p_value=p, confidence_label=_confidence_label(n_rev, p), direction_note=note,
        category_breakdown=breakdown or None,
    )

    magnitude_groups: dict[str, list[float]] = defaultdict(list)
    for r in records:
        cat = extractor(r)
        if cat is not None:
            magnitude_groups[cat].append(r.outcome.outcome_magnitude)
    n_mag = sum(len(v) for v in magnitude_groups.values())
    if len(magnitude_groups) >= 2 and all(len(v) >= 3 for v in magnitude_groups.values()):
        stat_m, p_m = stats.kruskal(*magnitude_groups.values())
        note_m = f"Move-size distribution differs across {len(magnitude_groups)} categories (H={stat_m:.2f})."
    else:
        stat_m, p_m = None, None
        note_m = "Not enough days per category to compare move size."
    vs_magnitude = FactorCorrelationResult(
        factor_name=factor_name, factor_type="categorical", target="magnitude", n=n_mag,
        statistic=stat_m, p_value=p_m, confidence_label=_confidence_label(n_mag, p_m), direction_note=note_m,
        category_breakdown={cat: {"n": len(v)} for cat, v in magnitude_groups.items()} or None,
    )
    return vs_reversal, vs_magnitude


# ---------------------------------------------------------------------------
# The battery of factors this engine investigates, per the spec's list of
# auto-investigated questions. Extractors return None to be excluded from
# that factor's sample (missing data, not a zero).
# ---------------------------------------------------------------------------
CONTINUOUS_FACTORS: list[tuple[str, Callable[[DailyTransitionRecord], float | None]]] = [
    ("Developing POC migration (2-3pm)", lambda r: r.features.poc_migration_1400_1459),
    ("VWAP distance at 2:59pm (%)", lambda r: r.features.vwap_distance_1459_pct),
    ("Volume slope (2-3pm, 2nd half vs 1st half)", lambda r: r.features.volume_slope_1400_1459),
    ("Realized range (2-3pm)", lambda r: r.features.realized_range_1400_1459),
]

CATEGORICAL_FACTORS: list[tuple[str, Callable[[DailyTransitionRecord], str | None]]] = [
    ("Profile shape at 2:59pm", lambda r: r.features.profile_shape_1459),
    ("Rotation label at 2:59pm", lambda r: r.features.rotation_label_1459),
    ("Market regime at 2:59pm", lambda r: r.features.market_regime_1459),
    ("Day of week", lambda r: str(r.features.day_of_week) if r.features.day_of_week is not None else None),
    (
        "Inside initial balance at 2:59pm",
        lambda r: (
            "Yes" if r.features.is_inside_initial_balance_1459 else "No"
            if r.features.is_inside_initial_balance_1459 is not None
            else None
        ),
    ),
    (
        "Is expiry day",
        lambda r: "Yes" if r.features.expiry_type is not None else "No",
    ),
    (
        "Expiry type (expiry days only)",
        lambda r: r.features.expiry_type,
    ),
    ("Prior day's profile shape", lambda r: r.features.prior_day_profile_shape),
    ("Prior day's close vs. its own POC", lambda r: r.features.prior_day_close_vs_poc),
]


def run_correlation_study(records: list[DailyTransitionRecord]) -> list[FactorCorrelationResult]:
    results: list[FactorCorrelationResult] = []
    for name, extractor in CONTINUOUS_FACTORS:
        vs_rev, vs_mag = correlate_continuous_factor(name, extractor, records)
        results.extend([vs_rev, vs_mag])
    for name, extractor in CATEGORICAL_FACTORS:
        vs_rev, vs_mag = correlate_categorical_factor(name, extractor, records)
        results.extend([vs_rev, vs_mag])
    return results
