from datetime import date, timedelta

from market_transition.cas_transition import CasDailyTransition
from market_transition.cas_statistics import CAS_CONTINUOUS_FACTOR_FIELDS, run_cas_correlation_study
from market_transition.models import DailyTransitionRecord, PreWindowFeatures, TransitionOutcome


def _record(outcome: str, magnitude: float, day_index: int) -> DailyTransitionRecord:
    features = PreWindowFeatures(
        poc_migration_1400_1459=None, vwap_distance_1459=None, vwap_distance_1459_pct=None,
        volume_slope_1400_1459=None, realized_range_1400_1459=None, profile_shape_1459="D",
        rotation_label_1459=None, market_regime_1459=None, is_inside_initial_balance_1459=None,
        day_of_week=0, expiry_type=None, prior_day_profile_shape=None, prior_day_close_vs_poc=None,
    )
    out = TransitionOutcome(
        close_1459=100, close_1501=101, market_close=101 + magnitude,
        transition_move=1, transition_direction="up",
        post_transition_move=magnitude, outcome=outcome, outcome_magnitude=magnitude,
    )
    d = date(2026, 8, 3) + timedelta(days=day_index)
    return DailyTransitionRecord(symbol="TEST", session_date=d, features=features, outcome=out)


def _cas_row(day_index: int, volume_ratio: float, points_move: float = 10.0) -> CasDailyTransition:
    d = date(2026, 8, 3) + timedelta(days=day_index)
    return CasDailyTransition(
        symbol="TEST", session_date=d, close_1431=100, close_1459=100, close_1539=110,
        pre_direction="up", post_direction="up", conclusion="continuation", outcome_magnitude=10.0,
        pre_window_volume=1000.0, post_window_pre_auction_volume=1000.0 * volume_ratio, volume_ratio=volume_ratio,
        pre_window_points_move=points_move, post_window_points_move=15.0,
        pcr_1459=None, institutional_bias_label_1459=None, institutional_bias_score_1459=None,
        expiry_type=None, day_of_week=0, old_methodology_outcome=None, old_methodology_outcome_magnitude=None,
    )


def test_run_cas_correlation_study_includes_original_and_new_factors():
    records = [_record("reversal" if i % 2 == 0 else "continuation", 10 + i, i) for i in range(30)]
    cas_rows = [_cas_row(i, volume_ratio=1.0 + i * 0.05) for i in range(30)]

    results = run_cas_correlation_study(records, cas_rows)
    factor_names = {r.factor_name for r in results}

    # A known original-engine factor is present.
    assert "Developing POC migration (2-3pm)" in factor_names
    # New CAS-specific factors are present.
    assert "Volume ratio (post pre-auction / pre)" in factor_names
    assert "Pre-window points move (2:31-2:59pm)" in factor_names
    # The circular factor must never appear.
    assert not any("Post-window points move" in n for n in factor_names)


def test_run_cas_correlation_study_detects_a_known_volume_ratio_signal():
    # High volume ratio -> reversal; low -> continuation. Deterministic.
    records = []
    cas_rows = []
    for i in range(15):
        records.append(_record("reversal", 20 + i, i))
        cas_rows.append(_cas_row(i, volume_ratio=3.0 + i * 0.1))
    for i in range(15):
        records.append(_record("continuation", 5, 15 + i))
        cas_rows.append(_cas_row(15 + i, volume_ratio=0.5 + i * 0.01))

    results = run_cas_correlation_study(records, cas_rows)
    vs_reversal = next(r for r in results if r.factor_name == "Volume ratio (post pre-auction / pre)" and r.target == "reversal")
    assert vs_reversal.n == 30
    assert vs_reversal.statistic > 0.8
    assert vs_reversal.confidence_label == "Strong"


def test_cas_continuous_factor_fields_are_all_real_cas_daily_transition_fields():
    row = _cas_row(0, volume_ratio=1.0)
    for _, field in CAS_CONTINUOUS_FACTOR_FIELDS:
        assert hasattr(row, field)


def test_run_cas_correlation_study_handles_missing_cas_row_gracefully():
    # A record with no matching CasDailyTransition (e.g. a day that failed
    # option-context lookup) must not raise -- its CAS-specific factors are
    # simply excluded from that factor's sample.
    records = [_record("continuation", 10, i) for i in range(5)]
    cas_rows = [_cas_row(i, volume_ratio=1.0) for i in range(3)]  # missing days 3, 4
    results = run_cas_correlation_study(records, cas_rows)
    vol_ratio_result = next(r for r in results if r.factor_name == "Volume ratio (post pre-auction / pre)" and r.target == "magnitude")
    assert vol_ratio_result.n == 3
