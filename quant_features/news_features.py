"""News/event features from Market Intelligence's already-classified events.
Gated strictly on ClassifiedEvent.classified_at, never NewsItem.published_at
-- classification can lag collection/publication by hours on a busy day, so
joining on the article's own timestamp would leak information the system
didn't actually have available at T. `events` is caller-supplied (this
module never queries the DB, matching every other pure module in this
package) and only needs to cover a window at least `window_minutes` wide
ending at `as_of` -- this function re-applies the exact cutoff/window itself
rather than trusting the caller's query bounds, as a second, independent
leakage guard.
"""

from collections import Counter
from datetime import datetime, timedelta

from market_intelligence.models import ClassifiedEvent

from .models import NewsFeatureSet

NEWS_WINDOW_MINUTES = 30

_DIRECTION_ATTR_BY_SYMBOL = {
    "NIFTY": "expected_direction_nifty",
    "SENSEX": "expected_direction_sensex",
}


def _direction_for_symbol(event: ClassifiedEvent, symbol: str) -> str | None:
    attr = _DIRECTION_ATTR_BY_SYMBOL.get(symbol)
    if attr is None:
        return None
    return getattr(event, attr).value


def compute_news_feature_set(
    symbol: str,
    events: list[ClassifiedEvent],
    as_of: datetime,
    window_minutes: int = NEWS_WINDOW_MINUTES,
    relevant_only: bool = True,
) -> NewsFeatureSet:
    """Field names carry the default `_30m` window suffix regardless of the
    `window_minutes` actually passed, matching this codebase's convention
    of naming a field after its default parameter (e.g.
    `poc_migration_1400_1459`)."""
    window_start = as_of - timedelta(minutes=window_minutes)
    in_window = [
        e
        for e in events
        if e.classified_at <= as_of and e.classified_at >= window_start and (not relevant_only or e.is_relevant)
    ]
    if not in_window:
        return NewsFeatureSet(
            event_count_30m=0,
            max_severity_30m=None,
            dominant_sentiment_30m=None,
            most_recent_event_direction=None,
            most_recent_event_risk_level=None,
        )

    max_severity = max(e.severity for e in in_window)
    sentiment_counts = Counter(e.sentiment.value for e in in_window)
    dominant_sentiment = sentiment_counts.most_common(1)[0][0]
    most_recent = max(in_window, key=lambda e: e.classified_at)

    return NewsFeatureSet(
        event_count_30m=len(in_window),
        max_severity_30m=max_severity,
        dominant_sentiment_30m=dominant_sentiment,
        most_recent_event_direction=_direction_for_symbol(most_recent, symbol),
        most_recent_event_risk_level=most_recent.risk_level.value,
    )
