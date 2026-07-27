"""Free, provider-independent news collection via public RSS feeds. Swapping
to a paid aggregator later means writing a new class satisfying the same
NewsCollector protocol -- nothing downstream (classifier, pipeline, DB,
dashboard) needs to change.

Feed URLs were individually verified live (2026-07-27) -- several
plausible-looking candidates (Business Standard, Reuters India) returned
403/DNS errors and were dropped in favor of ones confirmed actually working.
Requires `config` to have been imported first so the project's truststore
bootstrap (see config/__init__.py) is active -- without it, this machine's
antivirus TLS interception blocks these fetches with the same class of SSL
error seen elsewhere in this project.
"""

import logging
from calendar import timegm
from datetime import datetime, timezone

import feedparser

from market_intelligence.models import NewsItem

logger = logging.getLogger(__name__)

DEFAULT_FEEDS: dict[str, str] = {
    "Economic Times Markets": "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
    "Moneycontrol Markets": "https://www.moneycontrol.com/rss/marketreports.xml",
    "Moneycontrol Business": "https://www.moneycontrol.com/rss/business.xml",
    "LiveMint Markets": "https://www.livemint.com/rss/markets",
    "CNBC-TV18 Markets": "https://www.cnbctv18.com/commonfeeds/v1/cne/rss/market.xml",
}


def _parse_published(entry) -> datetime:
    struct = entry.get("published_parsed") or entry.get("updated_parsed")
    if struct:
        return datetime.fromtimestamp(timegm(struct), tz=timezone.utc)
    return datetime.now(timezone.utc)


class RSSCollector:
    def __init__(self, feeds: dict[str, str] | None = None) -> None:
        self.feeds = feeds if feeds is not None else DEFAULT_FEEDS

    def collect(self) -> list[NewsItem]:
        items: list[NewsItem] = []
        for source, url in self.feeds.items():
            try:
                parsed = feedparser.parse(url)
            except Exception as e:
                logger.warning("RSS fetch failed for %s (%s): %s", source, url, e)
                continue

            status = getattr(parsed, "status", None)
            if status is not None and status >= 400:
                logger.warning("RSS fetch for %s returned HTTP %s", source, status)
                continue

            for entry in parsed.entries:
                title = entry.get("title", "").strip()
                link = entry.get("link", "")
                if not title or not link:
                    continue
                items.append(
                    NewsItem(
                        source=source,
                        title=title,
                        link=link,
                        published_at=_parse_published(entry),
                        summary=entry.get("summary"),
                        guid=entry.get("id") or link,
                    )
                )
        return items
