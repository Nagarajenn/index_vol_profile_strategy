"""Historical cohorts + pre-3pm warning-indicator statistics (Phase 7C).

Groups CAS-era days into 7 named cohorts derived from Phase 7A's own two
independent dimensions (transition_type x magnitude_tier), then for each
(cohort, feature) pair compares that cohort's pre-3pm (14:55-14:59) state
against the rest of the sample -- "which conditions preceded this kind of
outcome". This is a cohort-vs-rest comparison, not the correlation study
cas_statistics.py already runs (which is a single-model regression-style
test over ALL days at once) -- deliberately a different, complementary
question: not "does factor X correlate with the outcome" but "what did
days in cohort Y actually look like beforehand".

Pure functions, no DB access -- same discipline as every other module in
this package. Reuses Phase 7A's persisted transition_type/magnitude_tier
and Phase 7B's cas_pretransition_windows (the 14:55-14:59 window = the
final pre-3pm state) as-is; computes no new candle-level features.

"Do not claim predictive power from correlation alone" (the user's own
explicit principle): every result carries N and a confidence label: below
MIN_N_FOR_COHORT_CONFIDENCE the result is "Insufficient data", never
implied to be meaningful just because a p-value happens to be small.
"""

from dataclasses import dataclass
from datetime import date
from typing import Literal

from scipy import stats

CohortName = Literal[
    "FLAT_LARGE_UP",
    "FLAT_LARGE_DOWN",
    "UP_REVERSAL_DOWN",
    "DOWN_REVERSAL_UP",
    "UP_CONTINUATION",
    "DOWN_CONTINUATION",
    "FLAT_NO_MATERIAL_MOVE",
]

COHORT_NAMES: list[CohortName] = [
    "FLAT_LARGE_UP", "FLAT_LARGE_DOWN", "UP_REVERSAL_DOWN", "DOWN_REVERSAL_UP",
    "UP_CONTINUATION", "DOWN_CONTINUATION", "FLAT_NO_MATERIAL_MOVE",
]

# Separate from market_transition/statistics.py's MIN_N_FOR_CONFIDENCE=20 --
# a 7-way cohort split of the current ~19-day CAS-era sample will rarely
# reach 20 for any single cohort for a long time; reusing that threshold
# here would mark every single result "Insufficient data" forever, which
# isn't a useful signal, just a permanently-blank report. This is a
# documented starting default, tunable later, same stance as every other
# threshold in this codebase.
MIN_N_FOR_COHORT_CONFIDENCE = 5

_LARGE_TIERS = ("LARGE", "EXTREME")


def classify_cohort(transition_type: str, magnitude_tier: str | None) -> CohortName | None:
    """Maps Phase 7A's transition_type/magnitude_tier onto the 7 named
    cohorts from the spec. A day whose transition_type is
    POST_WINDOW_INITIATION_UP/DOWN but whose magnitude_tier is only
    NORMAL/MODERATE (a real move, just not a *large* one) fits none of the
    7 named cohorts and is deliberately excluded (returns None) rather than
    force-fit into the nearest one -- "exclude, don't fabricate"."""
    if transition_type == "POST_WINDOW_INITIATION_UP" and magnitude_tier in _LARGE_TIERS:
        return "FLAT_LARGE_UP"
    if transition_type == "POST_WINDOW_INITIATION_DOWN" and magnitude_tier in _LARGE_TIERS:
        return "FLAT_LARGE_DOWN"
    if transition_type == "REVERSAL_DOWN":
        return "UP_REVERSAL_DOWN"
    if transition_type == "REVERSAL_UP":
        return "DOWN_REVERSAL_UP"
    if transition_type == "CONTINUATION_UP":
        return "UP_CONTINUATION"
    if transition_type == "CONTINUATION_DOWN":
        return "DOWN_CONTINUATION"
    if transition_type == "NO_MATERIAL_TRANSITION":
        return "FLAT_NO_MATERIAL_MOVE"
    return None


@dataclass
class CohortFeatureStat:
    cohort: CohortName
    feature_name: str
    n: int
    median: float | None
    mean: float | None
    percentile_within_full_sample: float | None
    effect_size: float | None
    statistic: float | None
    p_value: float | None
    confidence_label: str
    direction_note: str


@dataclass
class CohortCategoricalBreakdown:
    cohort: CohortName
    feature_name: str
    n: int
    category_counts: dict[str, int]
    full_sample_category_counts: dict[str, int]


def _confidence_label(n: int, p_value: float | None, min_n: int = MIN_N_FOR_COHORT_CONFIDENCE) -> str:
    if p_value is None or n < min_n:
        return "Insufficient data"
    if p_value < 0.01:
        return "Strong"
    if p_value < 0.05:
        return "Moderate"
    if p_value < 0.10:
        return "Weak"
    return "Not significant"


def _percentile_rank(value: float, full_sample: list[float]) -> float:
    """Percentage of full_sample values <= `value` -- an intuitive,
    unit-free read of where the cohort's median sits in the overall
    distribution."""
    if not full_sample:
        return 0.0
    return sum(1 for v in full_sample if v <= value) / len(full_sample) * 100


def _compare_feature(
    cohort: CohortName, feature_name: str, cohort_values: list[float], rest_values: list[float], all_values: list[float]
) -> CohortFeatureStat:
    n = len(cohort_values)
    if n == 0:
        return CohortFeatureStat(
            cohort=cohort, feature_name=feature_name, n=0, median=None, mean=None,
            percentile_within_full_sample=None, effect_size=None, statistic=None, p_value=None,
            confidence_label="Insufficient data", direction_note="No days in this cohort have a value for this feature.",
        )

    sorted_cohort = sorted(cohort_values)
    median = sorted_cohort[n // 2] if n % 2 else (sorted_cohort[n // 2 - 1] + sorted_cohort[n // 2]) / 2
    mean = sum(cohort_values) / n
    percentile = _percentile_rank(median, all_values)

    statistic: float | None = None
    p_value: float | None = None
    effect_size: float | None = None
    if n >= 2 and len(rest_values) >= 2:
        result = stats.mannwhitneyu(cohort_values, rest_values, alternative="two-sided")
        statistic, p_value = float(result.statistic), float(result.pvalue)
        # Rank-biserial correlation, the natural effect-size pairing for
        # Mann-Whitney U: +1 = cohort's values are entirely higher than the
        # rest, -1 = entirely lower, 0 = no separation. scipy's U statistic
        # (for x=cohort_values) is *maximal* (n*m) when cohort is entirely
        # higher, so it must be scaled up, not down, to land on +1 there.
        effect_size = (2 * statistic) / (n * len(rest_values)) - 1

    direction = "higher" if effect_size is not None and effect_size > 0 else "lower" if effect_size is not None and effect_size < 0 else "no clear difference from"
    note = (
        f"Cohort median {median:.3g} ({percentile:.0f}th percentile of all days) is {direction} than the rest of the sample."
        if effect_size is not None
        else f"Cohort median {median:.3g} ({percentile:.0f}th percentile) -- not enough data in the rest of the sample to compare."
    )

    return CohortFeatureStat(
        cohort=cohort, feature_name=feature_name, n=n, median=median, mean=mean,
        percentile_within_full_sample=percentile, effect_size=effect_size, statistic=statistic, p_value=p_value,
        confidence_label=_confidence_label(n, p_value), direction_note=note,
    )


def _compare_categorical(
    cohort: CohortName, feature_name: str, cohort_values: list[str], all_values: list[str]
) -> CohortCategoricalBreakdown:
    def _counts(values: list[str]) -> dict[str, int]:
        out: dict[str, int] = {}
        for v in values:
            out[v] = out.get(v, 0) + 1
        return out

    return CohortCategoricalBreakdown(
        cohort=cohort, feature_name=feature_name, n=len(cohort_values),
        category_counts=_counts(cohort_values), full_sample_category_counts=_counts(all_values),
    )


# (display name, extractor over (cas_row, final_window)) -- extractor
# returns None when the value isn't available for that day, filtered out
# before comparison rather than treated as 0.
_CONTINUOUS_FEATURES: list[tuple[str, "object"]] = [
    ("Pre-window volume (14:55-14:59)", lambda row, w: w.volume if w else None),
    ("Volume acceleration (14:55-14:59)", lambda row, w: w.volume_acceleration_ratio if w else None),
    ("RVOL % (14:55-14:59)", lambda row, w: w.rvol_pct if w else None),
    ("Price distance from VWAP % (14:59)", lambda row, w: w.price_distance_from_vwap_pct if w else None),
    ("Developing POC migration (14:55-14:59)", lambda row, w: w.poc_change_during_window if w else None),
    ("PCR (14:59)", lambda row, w: w.pcr if w else None),
    ("PCR change (14:55-14:59)", lambda row, w: w.pcr_change if w else None),
    ("Call OI change (14:55-14:59)", lambda row, w: w.call_oi_change if w else None),
    ("Put OI change (14:55-14:59)", lambda row, w: w.put_oi_change if w else None),
    ("IV change (14:55-14:59)", lambda row, w: w.iv_change if w else None),
    ("Option pressure (14:55-14:59)", lambda row, w: w.option_pressure_score if w else None),
    ("Institutional bias score (14:59)", lambda row, w: row.institutional_bias_score_1459),
]
_CATEGORICAL_FEATURES: list[tuple[str, "object"]] = [
    ("Institutional bias label (14:59)", lambda row, w: w.institutional_bias_label if w else None),
    ("Market regime (14:59)", lambda row, w: w.market_regime if w else None),
]


def run_cohort_analysis(
    cas_rows: list, final_windows_by_date: dict[date, object]
) -> tuple[list[CohortFeatureStat], list[CohortCategoricalBreakdown]]:
    """`cas_rows` is a list of CasDailyTransition-shaped objects (attribute
    access: transition_type, magnitude_tier, session_date,
    institutional_bias_score_1459). `final_windows_by_date` maps
    session_date -> the day's window_index=6 (14:55-14:59)
    PreTransitionWindow, or is missing/None for days without Phase 7B
    data yet (handled gracefully, not required)."""
    cohort_by_date: dict[date, CohortName] = {}
    for row in cas_rows:
        cohort = classify_cohort(row.transition_type, row.magnitude_tier)
        if cohort is not None:
            cohort_by_date[row.session_date] = cohort

    rows_by_date = {row.session_date: row for row in cas_rows}

    feature_stats: list[CohortFeatureStat] = []
    for feature_name, extractor in _CONTINUOUS_FEATURES:
        all_pairs = [(d, extractor(rows_by_date[d], final_windows_by_date.get(d))) for d in rows_by_date]
        all_values = [v for _, v in all_pairs if v is not None]
        for cohort in COHORT_NAMES:
            cohort_dates = {d for d, c in cohort_by_date.items() if c == cohort}
            cohort_values = [v for d, v in all_pairs if d in cohort_dates and v is not None]
            rest_values = [v for d, v in all_pairs if d not in cohort_dates and v is not None]
            feature_stats.append(_compare_feature(cohort, feature_name, cohort_values, rest_values, all_values))

    categorical_stats: list[CohortCategoricalBreakdown] = []
    for feature_name, extractor in _CATEGORICAL_FEATURES:
        all_pairs = [(d, extractor(rows_by_date[d], final_windows_by_date.get(d))) for d in rows_by_date]
        all_values = [v for _, v in all_pairs if v is not None]
        for cohort in COHORT_NAMES:
            cohort_dates = {d for d, c in cohort_by_date.items() if c == cohort}
            cohort_values = [v for d, v in all_pairs if d in cohort_dates and v is not None]
            categorical_stats.append(_compare_categorical(cohort, feature_name, cohort_values, all_values))

    return feature_stats, categorical_stats
