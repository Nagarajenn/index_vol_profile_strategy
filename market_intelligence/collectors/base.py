from typing import Protocol

from market_intelligence.models import NewsItem


class NewsCollector(Protocol):
    def collect(self) -> list[NewsItem]: ...
