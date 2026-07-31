import sys
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from market_transition.live_advisor import (
    build_live_advisory,
    build_live_query,
    compute_estimated_move,
    compute_transition_risk_level,
    determine_transition_stage,
    estimate_transition_timing,
    is_advisor_active,
)
from market_transition.models import DailyTransitionRecord, PreWindowFeatures, TransitionOutcome
from market_transition.statistics import run_correlation_study
from tests.fixtures.synthetic_candles import make_candles


# ---------------------------------------------------------------------------
# Stage / activity window
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "t,expected",
    [
        (time(13, 59), "Not Yet Active"),
        (time(14, 0), "Pre-Transition Monitoring"),
        (time(14, 59), "Pre-Transition Monitoring"),
        (time(15, 0), "Transition Window"),
        (time(15, 1), "Transition Window"),
        (time(15, 2), "Post-Transition Follow-Through"),
        (time(15, 20), "Post-Transition Follow-Through"),
        (time(15, 21), "Session Complete"),
    ],
)
def test_determine_transition_stage(t, expected):
    assert determine_transition_stage(t) == expected


@pytest.mark.parametrize(
    "t,expected",
    [(time(13, 59), False), (time(14, 0), True), (time(15, 1), True), (time(15, 2), False)],
)
def test_is_advisor_active(t, expected):
    assert is_advisor_active(t) == expected


# ---------------------------------------------------------------------------
# build_live_query
# ---------------------------------------------------------------------------
def _partial_session(tz_date: str, up_to: str) -> pd.DataFrame:
    rows = []
    price = 100.0
    for t in pd.date_range(f"2026-01-01 09:15", f"2026-01-01 {up_to}", freq="1min"):
        price += 0.02
        rows.append({"time": t.strftime("%H:%M"), "o": price, "h": price + 0.3, "l": price - 0.3, "c": price, "v": 80})
    return make_candles(rows, tz_date=tz_date)


def test_build_live_query_none_before_1400():
    today = _partial_session("2026-07-10", "13:59")
    record = build_live_query("NIFTY", date(2026, 7, 10), today, None, {}, 1.0, None, now_time=time(13, 30))
    assert record is None


def test_build_live_query_returns_partial_features_mid_window():
    today = _partial_session("2026-07-10", "14:20")
    record = build_live_query("NIFTY", date(2026, 7, 10), today, None, {}, 1.0, None, now_time=time(14, 20))
    assert record is not None
    assert record.features.vwap_distance_1459 is not None


def test_build_live_query_clamps_cutoff_at_1459():
    # Even if "now" is inside the transition window, features must still
    # describe only the completed 14:00-14:59 pre-window, not extend into it.
    today = _partial_session("2026-07-10", "15:00")
    record = build_live_query("NIFTY", date(2026, 7, 10), today, None, {}, 1.0, None, now_time=time(15, 0))
    assert record is not None


# ---------------------------------------------------------------------------
# estimate_transition_timing
# ---------------------------------------------------------------------------
def _record_with_move(session_date: date, close_1459: float, post_move: float) -> DailyTransitionRecord:
    features = PreWindowFeatures(
        poc_migration_1400_1459=None, vwap_distance_1459=None, vwap_distance_1459_pct=None,
        volume_slope_1400_1459=None, realized_range_1400_1459=None, profile_shape_1459=None,
        rotation_label_1459=None, market_regime_1459=None, is_inside_initial_balance_1459=None,
        day_of_week=0, expiry_type=None, prior_day_profile_shape=None, prior_day_close_vs_poc=None,
    )
    outcome = TransitionOutcome(
        close_1459=close_1459, close_1501=close_1459 + 1, market_close=close_1459 + 1 + post_move,
        transition_move=1, transition_direction="up", post_transition_move=post_move,
        outcome="reversal" if post_move < 0 else "continuation", outcome_magnitude=abs(post_move),
    )
    return DailyTransitionRecord(symbol="TEST", session_date=session_date, features=features, outcome=outcome)


def test_estimate_transition_timing_finds_onset_across_analogs():
    day1 = _record_with_move(date(2026, 1, 1), close_1459=100.0, post_move=-20.0)
    day2 = _record_with_move(date(2026, 1, 2), close_1459=100.0, post_move=-20.0)
    day3 = _record_with_move(date(2026, 1, 3), close_1459=100.0, post_move=-20.0)
    analogs = [(day1, 0.1), (day2, 0.2), (day3, 0.3)]

    def _candles_moving_down_from(session_date, start_time_str):
        rows = []
        price = 100.0
        for i, t in enumerate(pd.date_range(f"2026-01-01 14:50", "2026-01-01 15:10", freq="1min")):
            price -= 1.0
            rows.append({"time": t.strftime("%H:%M"), "o": price, "h": price + 0.2, "l": price - 0.2, "c": price, "v": 10})
        return make_candles(rows, tz_date=session_date.isoformat())

    analog_candles = {d.session_date: _candles_moving_down_from(d.session_date, "14:50") for d, _ in analogs}

    result = estimate_transition_timing(analogs, analog_candles)

    assert result.n_analogs_with_onset == 3
    assert result.earliest is not None
    assert result.latest is not None
    assert result.earliest <= result.latest


def test_estimate_transition_timing_insufficient_data_fallback():
    day1 = _record_with_move(date(2026, 1, 1), close_1459=100.0, post_move=-20.0)
    result = estimate_transition_timing([(day1, 0.1)], {})
    assert result.earliest is None
    assert result.n_analogs_with_onset == 0
    assert "Not enough" in result.note


def test_estimate_transition_timing_skips_near_flat_analogs():
    flat_day = _record_with_move(date(2026, 1, 1), close_1459=100.0, post_move=0.1)
    result = estimate_transition_timing([(flat_day, 0.1)], {date(2026, 1, 1): make_candles([])})
    assert result.n_analogs_with_onset == 0


# ---------------------------------------------------------------------------
# compute_estimated_move
# ---------------------------------------------------------------------------
def test_compute_estimated_move_signed_mean():
    days = [
        _record_with_move(date(2026, 1, 1), 100.0, post_move=10.0),
        _record_with_move(date(2026, 1, 2), 100.0, post_move=-4.0),
    ]
    assert compute_estimated_move(days) == 3.0


def test_compute_estimated_move_empty():
    assert compute_estimated_move([]) == 0.0


# ---------------------------------------------------------------------------
# compute_transition_risk_level
# ---------------------------------------------------------------------------
def test_risk_level_observe_outside_active_window():
    assert compute_transition_risk_level(0.9, 0.9, "Strong", 10, "Not Yet Active") == "Observe"
    assert compute_transition_risk_level(0.9, 0.9, "Strong", 10, "Session Complete") == "Observe"


def test_risk_level_observe_with_insufficient_data():
    assert compute_transition_risk_level(0.9, 0.9, "Insufficient data", 10, "Pre-Transition Monitoring") == "Observe"


def test_risk_level_very_high_when_decisive_and_similar():
    level = compute_transition_risk_level(0.95, 0.9, "Moderate", 10, "Transition Window")
    assert level == "Very High"


def test_risk_level_low_when_near_5050():
    level = compute_transition_risk_level(0.51, 0.3, "Weak", 10, "Pre-Transition Monitoring")
    assert level == "Low"


# ---------------------------------------------------------------------------
# build_live_advisory (integration)
# ---------------------------------------------------------------------------
def _known_history_reversal_on_high_migration() -> list[DailyTransitionRecord]:
    records = []
    for i in range(20):
        f = PreWindowFeatures(
            poc_migration_1400_1459=50 + i, vwap_distance_1459=None, vwap_distance_1459_pct=None,
            volume_slope_1400_1459=None, realized_range_1400_1459=None, profile_shape_1459="D",
            rotation_label_1459=None, market_regime_1459=None, is_inside_initial_balance_1459=None,
            day_of_week=i % 5, expiry_type=None, prior_day_profile_shape=None, prior_day_close_vs_poc=None,
        )
        o = TransitionOutcome(
            close_1459=100, close_1501=101, market_close=101 - (15 + i), transition_move=1,
            transition_direction="up", post_transition_move=-(15 + i), outcome="reversal", outcome_magnitude=15 + i,
        )
        records.append(DailyTransitionRecord(symbol="TEST", session_date=date(2026, 1, 1) + timedelta(days=i), features=f, outcome=o))
    for i in range(20):
        f = PreWindowFeatures(
            poc_migration_1400_1459=1 + i * 0.1, vwap_distance_1459=None, vwap_distance_1459_pct=None,
            volume_slope_1400_1459=None, realized_range_1400_1459=None, profile_shape_1459="D",
            rotation_label_1459=None, market_regime_1459=None, is_inside_initial_balance_1459=None,
            day_of_week=i % 5, expiry_type=None, prior_day_profile_shape=None, prior_day_close_vs_poc=None,
        )
        o = TransitionOutcome(
            close_1459=100, close_1501=101, market_close=109, transition_move=1,
            transition_direction="up", post_transition_move=8, outcome="continuation", outcome_magnitude=8,
        )
        records.append(DailyTransitionRecord(symbol="TEST", session_date=date(2026, 2, 1) + timedelta(days=i), features=f, outcome=o))
    return records


def test_build_live_advisory_end_to_end_leans_reversal():
    history = _known_history_reversal_on_high_migration()
    correlations = run_correlation_study(history)

    query_features = PreWindowFeatures(
        poc_migration_1400_1459=60, vwap_distance_1459=None, vwap_distance_1459_pct=None,
        volume_slope_1400_1459=None, realized_range_1400_1459=None, profile_shape_1459="D",
        rotation_label_1459=None, market_regime_1459=None, is_inside_initial_balance_1459=None,
        day_of_week=2, expiry_type=None, prior_day_profile_shape=None, prior_day_close_vs_poc=None,
    )
    placeholder_outcome = TransitionOutcome(
        close_1459=0, close_1501=0, market_close=0, transition_move=0,
        transition_direction="flat", post_transition_move=0, outcome="neutral", outcome_magnitude=0,
    )
    query = DailyTransitionRecord(symbol="TEST", session_date=date(2026, 3, 1), features=query_features, outcome=placeholder_outcome)

    advisory = build_live_advisory(
        query, history, correlations, now=datetime(2026, 3, 1, 14, 30, tzinfo=timezone.utc),
        institutional_bias_label="Mildly Bearish", news_risk_score=25, news_sentiment="Neutral",
    )

    assert advisory.stage == "Pre-Transition Monitoring"
    assert advisory.probability_reversal > advisory.probability_continuation
    assert advisory.risk_level in ("Low", "Medium", "High", "Very High")
    assert len(advisory.most_similar_days) > 0
    assert advisory.institutional_bias_label == "Mildly Bearish"
    assert advisory.news_risk_score == 25
    assert "reversal" in advisory.explanation.lower() or "%" in advisory.explanation


def test_build_live_advisory_observe_outside_window():
    history = _known_history_reversal_on_high_migration()
    correlations = run_correlation_study(history)
    query_features = history[0].features
    placeholder_outcome = TransitionOutcome(
        close_1459=0, close_1501=0, market_close=0, transition_move=0,
        transition_direction="flat", post_transition_move=0, outcome="neutral", outcome_magnitude=0,
    )
    query = DailyTransitionRecord(symbol="TEST", session_date=date(2026, 3, 1), features=query_features, outcome=placeholder_outcome)

    advisory = build_live_advisory(query, history, correlations, now=datetime(2026, 3, 1, 16, 0, tzinfo=timezone.utc))
    assert advisory.stage == "Session Complete"
    assert advisory.risk_level == "Observe"
