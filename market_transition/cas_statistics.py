"""Factor-correlation study for CAS Intelligence. Reuses
market_transition.statistics's exact statistical primitives
(correlate_continuous_factor/correlate_categorical_factor, point-biserial/
Pearson for continuous factors, chi-square/Kruskal-Wallis for categorical)
completely unmodified -- this module adds no new statistics, only new
factors and a new (still-additive) place to persist the results.

Two factor sources, tested against the SAME CAS-adjusted outcome
(DailyTransitionRecord.outcome, from extract_cas_transition_record):
  - The original engine's 13 factors, verbatim -- but `records` here comes
    from the CAS-windowed extraction, so e.g. "Developing POC migration"
    now reflects the 14:31-14:59 window, not the original 14:00-14:59 one.
  - New CAS-specific factors (pre-window points move/volume, post-window
    pre-auction volume and volume ratio, PCR and institutional bias at
    14:59) -- these live on CasDailyTransition, not PreWindowFeatures, so
    they're looked up by session_date via a small adapter rather than
    read directly off the record the way the original factors are.

Deliberately excludes post-window points move as a candidate factor: its
SIGN is literally what continuation/reversal is computed from (see
cas_transition.py), so correlating it against the outcome would be
circular, not predictive -- it would trivially "explain" the outcome by
restating it.
"""

from datetime import date
from typing import Callable

from market_transition.cas_transition import CasDailyTransition
from market_transition.models import DailyTransitionRecord, FactorCorrelationResult
from market_transition.statistics import (
    CATEGORICAL_FACTORS,
    CONTINUOUS_FACTORS,
    correlate_categorical_factor,
    correlate_continuous_factor,
)

CAS_CONTINUOUS_FACTOR_FIELDS: list[tuple[str, str]] = [
    ("Pre-window points move (2:31-2:59pm)", "pre_window_points_move"),
    ("Pre-window volume (2:31-2:59pm)", "pre_window_volume"),
    ("Post-window volume, pre-auction only (3:00-3:14pm)", "post_window_pre_auction_volume"),
    ("Volume ratio (post pre-auction / pre)", "volume_ratio"),
    ("PCR at 2:59pm", "pcr_1459"),
    ("Institutional bias score at 2:59pm", "institutional_bias_score_1459"),
]

CAS_CATEGORICAL_FACTOR_FIELDS: list[tuple[str, str]] = [
    ("Institutional bias label at 2:59pm", "institutional_bias_label_1459"),
]


def _cas_numeric_extractor(cas_by_date: dict[date, CasDailyTransition], field: str) -> Callable[[DailyTransitionRecord], float | None]:
    def extractor(r: DailyTransitionRecord) -> float | None:
        cas = cas_by_date.get(r.session_date)
        return getattr(cas, field) if cas is not None else None

    return extractor


def _cas_categorical_extractor(cas_by_date: dict[date, CasDailyTransition], field: str) -> Callable[[DailyTransitionRecord], str | None]:
    def extractor(r: DailyTransitionRecord) -> str | None:
        cas = cas_by_date.get(r.session_date)
        if cas is None:
            return None
        value = getattr(cas, field)
        return str(value) if value is not None else None

    return extractor


def run_cas_correlation_study(
    records: list[DailyTransitionRecord], cas_rows: list[CasDailyTransition]
) -> list[FactorCorrelationResult]:
    """`records` must come from market_transition.research.extract_all_records
    with extract_fn=cas_transition.extract_cas_transition_record; `cas_rows`
    from the matching build_cas_daily_transition() calls for the same days."""
    cas_by_date = {c.session_date: c for c in cas_rows}
    results: list[FactorCorrelationResult] = []

    for name, extractor in CONTINUOUS_FACTORS:
        results.extend(correlate_continuous_factor(name, extractor, records))
    for name, extractor in CATEGORICAL_FACTORS:
        results.extend(correlate_categorical_factor(name, extractor, records))

    for name, field in CAS_CONTINUOUS_FACTOR_FIELDS:
        results.extend(correlate_continuous_factor(name, _cas_numeric_extractor(cas_by_date, field), records))
    for name, field in CAS_CATEGORICAL_FACTOR_FIELDS:
        results.extend(correlate_categorical_factor(name, _cas_categorical_extractor(cas_by_date, field), records))

    return results
