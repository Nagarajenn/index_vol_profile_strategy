import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from market_transition.models import DailyTransitionRecord, PreWindowFeatures, TransitionOutcome
from market_transition.scoring import score_day
from market_transition.statistics import run_correlation_study


def _record(day_index: int, poc_migration: float, outcome: str, magnitude: float = 10.0, profile_shape: str = "D") -> DailyTransitionRecord:
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
        day_of_week=day_index % 5,
        expiry_type=None,
        prior_day_profile_shape=None,
        prior_day_close_vs_poc=None,
    )
    out = TransitionOutcome(
        close_1459=100, close_1501=101, market_close=101 + magnitude if outcome != "reversal" else 101 - magnitude,
        transition_move=1, transition_direction="up",
        post_transition_move=magnitude if outcome != "reversal" else -magnitude,
        outcome=outcome, outcome_magnitude=magnitude,
    )
    return DailyTransitionRecord(symbol="TEST", session_date=date(2026, 1, 1) + timedelta(days=day_index), features=features, outcome=out)


def _build_known_history() -> list[DailyTransitionRecord]:
    # High POC migration -> reversal; low -> continuation. Unambiguous
    # signal so the correlation study should flag it "Strong".
    records = []
    for i in range(20):
        records.append(_record(i, poc_migration=50 + i, outcome="reversal", magnitude=15 + i * 0.5))
    for i in range(20):
        records.append(_record(20 + i, poc_migration=1 + i * 0.1, outcome="continuation", magnitude=8))
    return records


def test_score_day_leans_reversal_for_high_poc_migration_query():
    history = _build_known_history()
    correlations = run_correlation_study(history)
    query = _record(999, poc_migration=60, outcome="continuation")  # outcome unused for scoring, only features

    result = score_day(query, history, correlations, k=10)

    assert result.probability_reversal > result.probability_continuation
    assert result.transition_risk_score > 50
    assert result.statistical_confidence != "Insufficient data"
    assert len(result.top_contributing_factors) > 0
    assert any("Developing POC migration" in c.factor_name for c in result.top_contributing_factors)


def test_score_day_leans_continuation_for_low_poc_migration_query():
    history = _build_known_history()
    correlations = run_correlation_study(history)
    query = _record(998, poc_migration=1.0, outcome="continuation")

    result = score_day(query, history, correlations, k=10)

    assert result.probability_continuation > result.probability_reversal
    assert result.transition_risk_score < 50


def test_score_day_insufficient_data_with_empty_history():
    query = _record(0, poc_migration=5, outcome="continuation")
    result = score_day(query, [], [], k=10)

    assert result.statistical_confidence == "Insufficient data"
    assert result.probability_continuation == 0.5
    assert result.probability_reversal == 0.5
    assert result.top_contributing_factors == []


def test_score_day_excludes_query_date_from_its_own_analogs():
    history = _build_known_history()
    correlations = run_correlation_study(history)
    query = history[0]  # a day that IS in history

    result = score_day(query, history, correlations, k=5)
    # Should not crash or trivially match itself; just verify it still
    # produces a real (non-fallback) result using other days.
    assert result.statistical_confidence != "Insufficient data"


def test_explanation_is_non_empty_and_deterministic():
    history = _build_known_history()
    correlations = run_correlation_study(history)
    query = _record(997, poc_migration=55, outcome="continuation")

    result1 = score_day(query, history, correlations, k=10)
    result2 = score_day(query, history, correlations, k=10)

    assert result1.explanation != ""
    assert result1.probability_reversal == result2.probability_reversal
    assert result1.transition_risk_score == result2.transition_risk_score
