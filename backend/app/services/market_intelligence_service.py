from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Literal

from app.models import ClassifiedEvent
from app.repositories.protocols import MarketIntelligenceRepositoryProtocol
from app.schemas.market_intelligence import MarketIntelligenceEventDTO, MarketIntelligenceSummaryDTO

DEFAULT_LIMIT = 5

# Only surface news from roughly the last two calendar days -- older items
# (e.g. classified late by a backlog catch-up run) would otherwise clutter
# the "current" read with stale context.
RECENCY_WINDOW = timedelta(days=2)


class MarketIntelligenceService:
    """Owns the "what does this mean" aggregation on top of the raw
    classified-event list: overall sentiment and a news risk score, both
    simple derived display aggregates -- computed here, not persisted, and
    entirely separate from analytics/confidence_score.py's trading
    confidence score (this never touches that table or that logic).
    """

    def __init__(self, repo: MarketIntelligenceRepositoryProtocol) -> None:
        self._repo = repo

    async def get_latest(self, limit: int = DEFAULT_LIMIT) -> MarketIntelligenceSummaryDTO:
        since = datetime.now(timezone.utc) - RECENCY_WINDOW
        rows = await self._repo.list_recent(limit, relevant_only=True, published_since=since)
        events = [self._to_dto(r) for r in rows]

        return MarketIntelligenceSummaryDTO(
            overall_sentiment=self._overall_sentiment(rows),
            news_risk_score=self._news_risk_score(rows),
            last_updated=max((r.classified_at for r in rows), default=None),
            events=events,
        )

    @staticmethod
    def _to_dto(row: ClassifiedEvent) -> MarketIntelligenceEventDTO:
        return MarketIntelligenceEventDTO(
            source=row.news_item.source,
            title=row.news_item.title,
            link=row.news_item.link,
            published_at=row.news_item.published_at,
            is_relevant=row.is_relevant,
            category=row.category,
            severity=row.severity,
            confidence=row.confidence,
            sentiment=row.sentiment,
            expected_duration=row.expected_duration,
            volatility_impact=row.volatility_impact,
            reversal_probability=row.reversal_probability,
            affected_sectors=row.affected_sectors,
            affected_indices=row.affected_indices,
            expected_direction_nifty=row.expected_direction_nifty,
            expected_direction_sensex=row.expected_direction_sensex,
            expected_direction_banknifty=row.expected_direction_banknifty,
            recommended_action=row.recommended_action,
            risk_level=row.risk_level,
            rationale=row.rationale,
            classified_at=row.classified_at,
        )

    @staticmethod
    def _overall_sentiment(rows: list[ClassifiedEvent]) -> Literal["Bullish", "Bearish", "Neutral"]:
        if not rows:
            return "Neutral"
        weight: dict[str, float] = defaultdict(float)
        for r in rows:
            weight[r.sentiment] += r.severity * r.confidence
        return max(weight, key=weight.get)  # type: ignore[arg-type]

    @staticmethod
    def _news_risk_score(rows: list[ClassifiedEvent]) -> int:
        """0-100: how much caution the recent news flow warrants, weighting
        severity by confidence so a low-confidence extreme reading doesn't
        dominate. Purely a display aggregate -- never written back to any
        trading table."""
        if not rows:
            return 0
        avg = sum(r.severity * r.confidence for r in rows) / len(rows)
        return round(min(avg / 5 * 100, 100))
