from datetime import datetime, timedelta, timezone

import pytest

from market_intelligence.models import (
    ClassifiedEvent,
    Direction,
    Duration,
    EventCategory,
    ImpactLevel,
    NewsItem,
    Sentiment,
)
from quant_features.news_features import compute_news_feature_set

T = datetime(2026, 7, 20, 10, 30, tzinfo=timezone.utc)


def _event(
    minutes_before: float,
    severity: int = 2,
    sentiment: Sentiment = Sentiment.BULLISH,
    is_relevant: bool = True,
    risk_level: ImpactLevel = ImpactLevel.MEDIUM,
    direction_nifty: Direction = Direction.UP,
    direction_sensex: Direction = Direction.UP,
) -> ClassifiedEvent:
    classified_at = T - timedelta(minutes=minutes_before)
    return ClassifiedEvent(
        news_item=NewsItem(source="test", title="t", link="http://x", published_at=classified_at, guid="g"),
        is_relevant=is_relevant,
        category=EventCategory.OTHER,
        severity=severity,
        confidence=0.8,
        sentiment=sentiment,
        expected_duration=Duration.INTRADAY,
        volatility_impact=ImpactLevel.MEDIUM,
        reversal_probability=0.3,
        affected_sectors=[],
        affected_indices=["NIFTY"],
        expected_direction_nifty=direction_nifty,
        expected_direction_sensex=direction_sensex,
        expected_direction_banknifty=Direction.FLAT,
        recommended_action="none",
        risk_level=risk_level,
        rationale="r",
        classified_at=classified_at,
        model="test-model",
    )


def test_no_events_returns_zero_count_and_none_fields():
    result = compute_news_feature_set("NIFTY", [], T)
    assert result.event_count_30m == 0
    assert result.max_severity_30m is None
    assert result.dominant_sentiment_30m is None
    assert result.most_recent_event_direction is None
    assert result.most_recent_event_risk_level is None


def test_events_outside_window_excluded():
    events = [_event(minutes_before=45)]  # older than the default 30-min window
    result = compute_news_feature_set("NIFTY", events, T)
    assert result.event_count_30m == 0


def test_events_after_as_of_excluded_even_if_in_list():
    future_event = _event(minutes_before=-5)  # classified_at is AFTER T -- must never leak in
    result = compute_news_feature_set("NIFTY", [future_event], T)
    assert result.event_count_30m == 0


def test_event_count_and_max_severity():
    events = [_event(10, severity=2), _event(20, severity=5), _event(5, severity=3)]
    result = compute_news_feature_set("NIFTY", events, T)
    assert result.event_count_30m == 3
    assert result.max_severity_30m == 5


def test_dominant_sentiment():
    events = [
        _event(10, sentiment=Sentiment.BULLISH),
        _event(15, sentiment=Sentiment.BULLISH),
        _event(20, sentiment=Sentiment.BEARISH),
    ]
    result = compute_news_feature_set("NIFTY", events, T)
    assert result.dominant_sentiment_30m == "Bullish"


def test_most_recent_event_direction_and_risk_level_per_symbol():
    events = [
        _event(20, direction_nifty=Direction.UP, direction_sensex=Direction.DOWN, risk_level=ImpactLevel.HIGH),
        _event(5, direction_nifty=Direction.DOWN, direction_sensex=Direction.UP, risk_level=ImpactLevel.EXTREME),
    ]
    nifty_result = compute_news_feature_set("NIFTY", events, T)
    sensex_result = compute_news_feature_set("SENSEX", events, T)
    assert nifty_result.most_recent_event_direction == "Down"
    assert nifty_result.most_recent_event_risk_level == "Extreme"
    assert sensex_result.most_recent_event_direction == "Up"


def test_relevant_only_filters_out_irrelevant_events():
    events = [_event(10, is_relevant=False)]
    result = compute_news_feature_set("NIFTY", events, T, relevant_only=True)
    assert result.event_count_30m == 0
    result_incl = compute_news_feature_set("NIFTY", events, T, relevant_only=False)
    assert result_incl.event_count_30m == 1


def test_custom_window_minutes():
    events = [_event(45)]
    result = compute_news_feature_set("NIFTY", events, T, window_minutes=60)
    assert result.event_count_30m == 1
