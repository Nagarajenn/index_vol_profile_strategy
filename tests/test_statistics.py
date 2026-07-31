import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from market_transition.models import DailyTransitionRecord, PreWindowFeatures, TransitionOutcome
from market_transition.statistics import correlate_categorical_factor, correlate_continuous_factor, run_correlation_study


def _record(
    poc_migration: float | None,
    outcome: str,
    profile_shape: str | None = "D",
    magnitude: float = 10.0,
    day_index: int = 0,
) -> DailyTransitionRecord:
    features = PreWindowFeatures(
        poc_migration_1400_1459=poc_migration,
        vwap_distance_1459=None,
        vwap_distance_1459_pct=None,
        volume_slope_1400_1459=None,
        realized_range_1400_1459=None,
        profile_shape_1459=profile_shape,
        rotation_label_1459=None,
        market_regime_1459=None,
        is_inside_initial_balance_1459=None,
        day_of_week=0,
        expiry_type=None,
        prior_day_profile_shape=None,
        prior_day_close_vs_poc=None,
    )
    out = TransitionOutcome(
        close_1459=100, close_1501=101, market_close=101 + magnitude,
        transition_move=1, transition_direction="up",
        post_transition_move=magnitude, outcome=outcome, outcome_magnitude=magnitude,
    )
    return DailyTransitionRecord(symbol="TEST", session_date=date(2026, 1, 1) + timedelta(days=day_index), features=features, outcome=out)


def test_continuous_factor_detects_strong_known_correlation():
    # Large positive POC migration -> reversal; near-zero -> continuation.
    # Deterministic, unambiguous signal so the test should find it "Strong".
    records = []
    for i in range(15):
        records.append(_record(poc_migration=50 + i, outcome="reversal", magnitude=20 + i, day_index=i))
    for i in range(15):
        records.append(_record(poc_migration=1 + i * 0.1, outcome="continuation", magnitude=5, day_index=15 + i))

    vs_reversal, vs_magnitude = correlate_continuous_factor(
        "POC migration", lambda r: r.features.poc_migration_1400_1459, records
    )
    assert vs_reversal.n == 30
    assert vs_reversal.statistic > 0.8
    assert vs_reversal.p_value < 0.01
    assert vs_reversal.confidence_label == "Strong"
    assert vs_magnitude.statistic > 0.5


def test_continuous_factor_insufficient_data_below_min_n():
    records = [_record(poc_migration=10, outcome="reversal", day_index=0), _record(poc_migration=1, outcome="continuation", day_index=1)]
    vs_reversal, _ = correlate_continuous_factor("POC migration", lambda r: r.features.poc_migration_1400_1459, records)
    assert vs_reversal.confidence_label == "Insufficient data"


def test_continuous_factor_excludes_none_values():
    records = [_record(poc_migration=None, outcome="reversal", day_index=0), _record(poc_migration=5, outcome="continuation", day_index=1)]
    vs_reversal, _ = correlate_continuous_factor("POC migration", lambda r: r.features.poc_migration_1400_1459, records)
    assert vs_reversal.n == 1  # only the non-None record counts


def test_continuous_factor_no_relationship_is_not_significant_with_enough_n():
    import random

    random.seed(42)
    records = []
    for i in range(30):
        outcome = "reversal" if i % 2 == 0 else "continuation"
        records.append(_record(poc_migration=random.uniform(-5, 5), outcome=outcome, magnitude=random.uniform(1, 3), day_index=i))
    vs_reversal, _ = correlate_continuous_factor("POC migration", lambda r: r.features.poc_migration_1400_1459, records)
    assert vs_reversal.n == 30
    assert vs_reversal.confidence_label in ("Not significant", "Weak")


def test_categorical_factor_detects_known_pattern():
    records = []
    for i in range(20):
        records.append(_record(poc_migration=1, outcome="reversal", profile_shape="B", day_index=i))
    for i in range(20):
        records.append(_record(poc_migration=1, outcome="continuation", profile_shape="D", day_index=20 + i))

    vs_reversal, _ = correlate_categorical_factor("Profile shape", lambda r: r.features.profile_shape_1459, records)
    assert vs_reversal.n == 40
    assert vs_reversal.category_breakdown["B"]["reversal_rate"] == 1.0
    assert vs_reversal.category_breakdown["D"]["reversal_rate"] == 0.0
    assert vs_reversal.p_value < 0.01
    assert vs_reversal.confidence_label == "Strong"


def test_categorical_factor_insufficient_data_with_one_category():
    records = [_record(poc_migration=1, outcome="reversal", profile_shape="D", day_index=i) for i in range(10)]
    vs_reversal, _ = correlate_categorical_factor("Profile shape", lambda r: r.features.profile_shape_1459, records)
    assert vs_reversal.confidence_label == "Insufficient data"


def test_run_correlation_study_returns_two_results_per_factor():
    records = [_record(poc_migration=float(i), outcome="reversal" if i % 2 == 0 else "continuation", day_index=i) for i in range(25)]
    results = run_correlation_study(records)
    from market_transition.statistics import CATEGORICAL_FACTORS, CONTINUOUS_FACTORS

    assert len(results) == 2 * (len(CONTINUOUS_FACTORS) + len(CATEGORICAL_FACTORS))
    targets = {r.target for r in results}
    assert targets == {"reversal", "magnitude"}
