from dataclasses import dataclass
from datetime import date

import pytest

from market_transition.cas_cohorts import (
    COHORT_NAMES,
    MIN_N_FOR_COHORT_CONFIDENCE,
    classify_cohort,
    run_cohort_analysis,
)


# --- classify_cohort: every transition_type/magnitude_tier combination ---


@pytest.mark.parametrize(
    "transition_type,magnitude_tier,expected",
    [
        ("POST_WINDOW_INITIATION_UP", "LARGE", "FLAT_LARGE_UP"),
        ("POST_WINDOW_INITIATION_UP", "EXTREME", "FLAT_LARGE_UP"),
        ("POST_WINDOW_INITIATION_DOWN", "LARGE", "FLAT_LARGE_DOWN"),
        ("POST_WINDOW_INITIATION_DOWN", "EXTREME", "FLAT_LARGE_DOWN"),
        ("REVERSAL_DOWN", "NORMAL", "UP_REVERSAL_DOWN"),
        ("REVERSAL_UP", "NORMAL", "DOWN_REVERSAL_UP"),
        ("CONTINUATION_UP", "NORMAL", "UP_CONTINUATION"),
        ("CONTINUATION_DOWN", "NORMAL", "DOWN_CONTINUATION"),
        ("NO_MATERIAL_TRANSITION", None, "FLAT_NO_MATERIAL_MOVE"),
        ("NO_MATERIAL_TRANSITION", "NORMAL", "FLAT_NO_MATERIAL_MOVE"),
        # Real move but not a LARGE one -- fits none of the 7 named cohorts.
        ("POST_WINDOW_INITIATION_UP", "NORMAL", None),
        ("POST_WINDOW_INITIATION_UP", "MODERATE", None),
        ("POST_WINDOW_INITIATION_DOWN", "MODERATE", None),
        ("POST_WINDOW_INITIATION_UP", None, None),
    ],
)
def test_classify_cohort(transition_type, magnitude_tier, expected):
    assert classify_cohort(transition_type, magnitude_tier) == expected


def test_all_seven_cohort_names_are_reachable():
    reachable = set()
    for tt in [
        "CONTINUATION_UP", "CONTINUATION_DOWN", "REVERSAL_UP", "REVERSAL_DOWN",
        "POST_WINDOW_INITIATION_UP", "POST_WINDOW_INITIATION_DOWN", "NO_MATERIAL_TRANSITION",
    ]:
        for mt in ["NORMAL", "MODERATE", "LARGE", "EXTREME", None]:
            c = classify_cohort(tt, mt)
            if c is not None:
                reachable.add(c)
    assert reachable == set(COHORT_NAMES)


# --- run_cohort_analysis ---


@dataclass
class _FakeCasRow:
    session_date: date
    transition_type: str
    magnitude_tier: str | None
    institutional_bias_score_1459: int | None


@dataclass
class _FakeWindow:
    volume: float | None = 1000.0
    volume_acceleration_ratio: float | None = 1.0
    rvol_pct: float | None = 100.0
    price_distance_from_vwap_pct: float | None = 0.0
    poc_change_during_window: float | None = 0.0
    pcr: float | None = 0.9
    pcr_change: float | None = 0.0
    call_oi_change: float | None = 0.0
    put_oi_change: float | None = 0.0
    iv_change: float | None = 0.0
    option_pressure_score: float | None = 0.0
    institutional_bias_label: str | None = "Neutral"
    market_regime: str | None = "Range-Bound"


def _rows_and_windows(n_up=4, n_down=4, up_volume=1000.0, down_volume=200.0):
    rows, windows = [], {}
    for i in range(n_up):
        d = date(2026, 8, i + 1)
        rows.append(_FakeCasRow(d, "CONTINUATION_UP", "NORMAL", 1))
        windows[d] = _FakeWindow(volume=up_volume + i)
    for i in range(n_down):
        d = date(2026, 8, i + 10)
        rows.append(_FakeCasRow(d, "CONTINUATION_DOWN", "NORMAL", -1))
        windows[d] = _FakeWindow(volume=down_volume + i)
    return rows, windows


def test_run_cohort_analysis_returns_every_cohort_feature_combination():
    rows, windows = _rows_and_windows()
    feature_stats, categorical_stats = run_cohort_analysis(rows, windows)
    # 12 continuous features x 7 cohorts, 2 categorical features x 7 cohorts
    assert len(feature_stats) == 12 * 7
    assert len(categorical_stats) == 2 * 7


def test_cleanly_separated_cohorts_get_opposite_sign_effect_sizes():
    rows, windows = _rows_and_windows(up_volume=1000.0, down_volume=200.0)
    feature_stats, _ = run_cohort_analysis(rows, windows)

    up_vol = next(s for s in feature_stats if s.cohort == "UP_CONTINUATION" and s.feature_name.startswith("Pre-window volume"))
    down_vol = next(s for s in feature_stats if s.cohort == "DOWN_CONTINUATION" and s.feature_name.startswith("Pre-window volume"))

    assert up_vol.n == 4
    assert up_vol.median == pytest.approx(1001.5)
    assert up_vol.effect_size == pytest.approx(1.0)  # entirely higher than the rest
    assert down_vol.effect_size == pytest.approx(-1.0)  # entirely lower than the rest
    # Percentile is computed against the FULL sample (cohort included), so
    # even a cohort with the highest values can't reach the 100th
    # percentile of its own set -- median 1001.5 among [200..203,1000..1003]
    # is <= 6 of the 8 full-sample values (itself included on both sides).
    assert up_vol.percentile_within_full_sample == 75.0


def test_below_min_n_is_insufficient_data_even_with_a_low_p_value():
    rows, windows = _rows_and_windows(n_up=4, n_down=4)  # 4 < MIN_N_FOR_COHORT_CONFIDENCE
    feature_stats, _ = run_cohort_analysis(rows, windows)
    up_vol = next(s for s in feature_stats if s.cohort == "UP_CONTINUATION" and s.feature_name.startswith("Pre-window volume"))
    assert up_vol.n < MIN_N_FOR_COHORT_CONFIDENCE
    assert up_vol.p_value is not None and up_vol.p_value < 0.05  # genuinely significant separation
    assert up_vol.confidence_label == "Insufficient data"  # but still marked insufficient on N alone


def test_meets_min_n_gets_a_real_confidence_label():
    rows, windows = _rows_and_windows(n_up=6, n_down=6, up_volume=1000.0, down_volume=200.0)
    feature_stats, _ = run_cohort_analysis(rows, windows)
    up_vol = next(s for s in feature_stats if s.cohort == "UP_CONTINUATION" and s.feature_name.startswith("Pre-window volume"))
    assert up_vol.n >= MIN_N_FOR_COHORT_CONFIDENCE
    assert up_vol.confidence_label in ("Strong", "Moderate", "Weak", "Not significant")


def test_empty_cohort_has_zero_n_and_no_crash():
    rows, windows = _rows_and_windows(n_up=4, n_down=0)
    feature_stats, _ = run_cohort_analysis(rows, windows)
    down_vol = next(s for s in feature_stats if s.cohort == "DOWN_CONTINUATION" and s.feature_name.startswith("Pre-window volume"))
    assert down_vol.n == 0
    assert down_vol.median is None
    assert down_vol.effect_size is None
    assert down_vol.confidence_label == "Insufficient data"
    # every other unreachable cohort (no days at all) also comes back cleanly
    reversal_up = next(s for s in feature_stats if s.cohort == "DOWN_REVERSAL_UP" and s.feature_name.startswith("Pre-window volume"))
    assert reversal_up.n == 0


def test_missing_window_data_is_excluded_not_treated_as_zero():
    rows, windows = _rows_and_windows(n_up=4, n_down=4)
    del windows[date(2026, 8, 1)]  # one UP_CONTINUATION day has no Phase 7B data yet
    feature_stats, _ = run_cohort_analysis(rows, windows)
    up_vol = next(s for s in feature_stats if s.cohort == "UP_CONTINUATION" and s.feature_name.startswith("Pre-window volume"))
    assert up_vol.n == 3  # not 4 -- the missing day is excluded, not counted as a zero-volume day


def test_categorical_breakdown_counts_within_cohort_and_full_sample():
    rows, windows = _rows_and_windows()
    _, categorical_stats = run_cohort_analysis(rows, windows)
    inst_bias = next(
        c for c in categorical_stats if c.cohort == "UP_CONTINUATION" and c.feature_name.startswith("Institutional bias label")
    )
    assert inst_bias.n == 4
    assert inst_bias.category_counts == {"Neutral": 4}
    assert inst_bias.full_sample_category_counts == {"Neutral": 8}


def test_day_not_fitting_any_cohort_is_excluded_from_all_cohorts():
    rows = [
        _FakeCasRow(date(2026, 8, 1), "POST_WINDOW_INITIATION_UP", "NORMAL", 0),  # real move, not large -- fits nothing
    ]
    windows = {date(2026, 8, 1): _FakeWindow()}
    feature_stats, _ = run_cohort_analysis(rows, windows)
    assert all(s.n == 0 for s in feature_stats)
