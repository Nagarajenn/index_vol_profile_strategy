import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from app.models import ClassifiedEvent, NewsItem
from app.services.market_intelligence_service import MarketIntelligenceService


def _event(sentiment: str, severity: int, confidence: float, source: str = "Test") -> ClassifiedEvent:
    news_item = NewsItem(
        source=source, title="Headline", link="http://x", guid="g", published_at=datetime.now(timezone.utc)
    )
    event = ClassifiedEvent(
        news_item_id=1,
        is_relevant=True,
        category="RBI / Monetary Policy",
        severity=severity,
        confidence=confidence,
        sentiment=sentiment,
        expected_duration="Intraday",
        volatility_impact="Medium",
        reversal_probability=0.3,
        affected_sectors=["Banking"],
        affected_indices=["NIFTY"],
        expected_direction_nifty="Down",
        expected_direction_sensex="Down",
        expected_direction_banknifty="Down",
        recommended_action="Wait for confirmation.",
        risk_level="Medium",
        rationale="Test rationale.",
        model="claude-haiku-4-5",
        classified_at=datetime.now(timezone.utc),
    )
    event.news_item = news_item
    return event


class _FakeRepo:
    def __init__(self, rows: list[ClassifiedEvent]) -> None:
        self._rows = rows

    async def list_recent(self, limit: int, relevant_only: bool = True) -> list[ClassifiedEvent]:
        return self._rows[:limit]


@pytest.mark.asyncio
async def test_get_latest_empty_returns_neutral_zero_risk():
    service = MarketIntelligenceService(_FakeRepo([]))
    result = await service.get_latest()
    assert result.overall_sentiment == "Neutral"
    assert result.news_risk_score == 0
    assert result.last_updated is None
    assert result.events == []


@pytest.mark.asyncio
async def test_get_latest_maps_events_and_picks_dominant_sentiment():
    rows = [_event("Bearish", severity=5, confidence=0.9), _event("Bullish", severity=1, confidence=0.2)]
    service = MarketIntelligenceService(_FakeRepo(rows))
    result = await service.get_latest()

    assert result.overall_sentiment == "Bearish"
    assert len(result.events) == 2
    assert result.events[0].source == "Test"
    assert result.last_updated is not None


@pytest.mark.asyncio
async def test_news_risk_score_scales_with_severity_and_confidence():
    high_risk = [_event("Bearish", severity=5, confidence=1.0)]
    low_risk = [_event("Neutral", severity=1, confidence=0.2)]

    high_result = await MarketIntelligenceService(_FakeRepo(high_risk)).get_latest()
    low_result = await MarketIntelligenceService(_FakeRepo(low_risk)).get_latest()

    assert high_result.news_risk_score == 100
    assert low_result.news_risk_score < high_result.news_risk_score
