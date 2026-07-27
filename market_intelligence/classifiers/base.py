from typing import Protocol

from market_intelligence.models import ClassifiedEvent, NewsItem


class EventClassifier(Protocol):
    def classify(self, item: NewsItem) -> ClassifiedEvent | None: ...
