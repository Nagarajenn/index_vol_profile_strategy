import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from market_intelligence import pipeline as mi_pipeline
from market_intelligence.classifiers.claude_classifier import (
    ClaudeEventClassifier,
    _parse_response_json,
)
from market_intelligence.collectors.rss_collector import RSSCollector
from market_intelligence.models import Direction, Duration, EventCategory, ImpactLevel, NewsItem, Sentiment


# ---------------------------------------------------------------------------
# RSS collector
# ---------------------------------------------------------------------------
def _fake_parsed_feed(status=200, entries=None):
    return SimpleNamespace(status=status, entries=entries or [])


def test_rss_collector_parses_entries(monkeypatch):
    entry = {
        "title": "  RBI holds repo rate steady  ",
        "link": "https://example.com/a",
        "summary": "The RBI kept rates unchanged.",
        "id": "guid-1",
        "published_parsed": (2026, 7, 27, 9, 0, 0, 0, 0, 0),
    }
    monkeypatch.setattr(
        "market_intelligence.collectors.rss_collector.feedparser.parse",
        lambda url: _fake_parsed_feed(entries=[entry]),
    )
    items = RSSCollector(feeds={"Test Source": "http://example.com/feed"}).collect()

    assert len(items) == 1
    assert items[0].source == "Test Source"
    assert items[0].title == "RBI holds repo rate steady"
    assert items[0].guid == "guid-1"
    assert items[0].published_at.tzinfo is not None


def test_rss_collector_skips_failed_feed(monkeypatch):
    def fake_parse(url):
        if "bad" in url:
            return _fake_parsed_feed(status=403, entries=[])
        return _fake_parsed_feed(entries=[{"title": "ok", "link": "http://x", "id": "g1"}])

    monkeypatch.setattr("market_intelligence.collectors.rss_collector.feedparser.parse", fake_parse)
    items = RSSCollector(feeds={"Bad": "http://bad.example.com", "Good": "http://good.example.com"}).collect()

    assert len(items) == 1
    assert items[0].source == "Good"


def test_rss_collector_skips_entries_missing_title_or_link(monkeypatch):
    entries = [{"title": "", "link": "http://x"}, {"title": "ok", "link": ""}]
    monkeypatch.setattr(
        "market_intelligence.collectors.rss_collector.feedparser.parse",
        lambda url: _fake_parsed_feed(entries=entries),
    )
    items = RSSCollector(feeds={"S": "http://s"}).collect()
    assert items == []


# ---------------------------------------------------------------------------
# Claude classifier -- response parsing (no live API call)
# ---------------------------------------------------------------------------
def _sample_news_item() -> NewsItem:
    return NewsItem(
        source="Test",
        title="RBI raises repo rate by 50bps",
        link="http://example.com",
        published_at=datetime(2026, 7, 27, 9, 0, tzinfo=timezone.utc),
        summary="Surprise hike",
        guid="g1",
    )


def _sample_classification_dict() -> dict:
    return {
        "is_relevant": True,
        "category": "RBI / Monetary Policy",
        "severity": 4,
        "confidence": 0.85,
        "sentiment": "Bearish",
        "expected_duration": "Multi-day",
        "volatility_impact": "High",
        "reversal_probability": 0.4,
        "affected_sectors": ["Banking", "Financials"],
        "affected_indices": ["NIFTY", "BANKNIFTY"],
        "expected_direction_nifty": "Down",
        "expected_direction_sensex": "Down",
        "expected_direction_banknifty": "Down",
        "recommended_action": "Favor caution on bullish technical setups until the market digests the hike.",
        "risk_level": "High",
        "rationale": "Surprise rate hikes typically pressure rate-sensitive banking stocks intraday.",
    }


def test_parse_response_json_maps_all_fields():
    item = _sample_news_item()
    event = _parse_response_json(_sample_classification_dict(), item, model="claude-haiku-4-5")

    assert event.news_item is item
    assert event.is_relevant is True
    assert event.category == EventCategory.RBI_MONETARY_POLICY
    assert event.severity == 4
    assert event.sentiment == Sentiment.BEARISH
    assert event.expected_duration == Duration.MULTI_DAY
    assert event.volatility_impact == ImpactLevel.HIGH
    assert event.expected_direction_nifty == Direction.DOWN
    assert event.affected_sectors == ["Banking", "Financials"]
    assert event.model == "claude-haiku-4-5"
    assert event.classified_at.tzinfo is not None


class _FakeMessages:
    def __init__(self, response=None, exc=None):
        self._response = response
        self._exc = exc

    def create(self, **kwargs):
        if self._exc:
            raise self._exc
        return self._response


class _FakeClient:
    def __init__(self, response=None, exc=None):
        self.messages = _FakeMessages(response, exc)


def test_classifier_returns_event_on_valid_response():
    import json

    response = SimpleNamespace(content=[SimpleNamespace(type="text", text=json.dumps(_sample_classification_dict()))])
    classifier = ClaudeEventClassifier(client=_FakeClient(response=response))

    event = classifier.classify(_sample_news_item())
    assert event is not None
    assert event.category == EventCategory.RBI_MONETARY_POLICY


def test_classifier_returns_none_on_malformed_json():
    response = SimpleNamespace(content=[SimpleNamespace(type="text", text="not json")])
    classifier = ClaudeEventClassifier(client=_FakeClient(response=response))
    assert classifier.classify(_sample_news_item()) is None


def test_classifier_returns_none_when_no_text_block():
    response = SimpleNamespace(content=[SimpleNamespace(type="tool_use", text=None)])
    classifier = ClaudeEventClassifier(client=_FakeClient(response=response))
    assert classifier.classify(_sample_news_item()) is None


def test_classifier_returns_none_on_api_error():
    import anthropic

    exc = anthropic.APIError("boom", request=SimpleNamespace(), body=None)
    classifier = ClaudeEventClassifier(client=_FakeClient(exc=exc))
    assert classifier.classify(_sample_news_item()) is None


# ---------------------------------------------------------------------------
# Pipeline orchestrator -- dedupe/limit logic with fakes
# ---------------------------------------------------------------------------
class _FakeCollector:
    def __init__(self, items):
        self._items = items

    def collect(self):
        return self._items


class _FakeClassifier:
    def __init__(self):
        self.calls = 0

    def classify(self, item):
        self.calls += 1
        event = SimpleNamespace(is_relevant=True, news_item=item)
        return event


def test_pipeline_skips_already_classified_items(monkeypatch):
    items = [
        NewsItem(source="S", title="A", link="http://a", published_at=datetime.now(timezone.utc), guid="a"),
        NewsItem(source="S", title="B", link="http://b", published_at=datetime.now(timezone.utc), guid="b"),
    ]
    news_ids = {"a": 1, "b": 2}
    already_classified = {1}  # item "a" was classified in a prior run

    monkeypatch.setattr(mi_pipeline.db_writer, "insert_news_item", lambda item: news_ids[item.guid])
    monkeypatch.setattr(mi_pipeline.db_reader, "has_classified_event", lambda nid: nid in already_classified)
    inserted = []
    monkeypatch.setattr(mi_pipeline.db_writer, "insert_classified_event", lambda nid, event: inserted.append((nid, event)))

    classifier = _FakeClassifier()
    results = mi_pipeline.collect_and_classify(_FakeCollector(items), classifier)

    assert classifier.calls == 1  # only "b" was classified
    assert len(results) == 1
    assert len(inserted) == 1


def test_pipeline_respects_max_new_classifications(monkeypatch):
    items = [
        NewsItem(source="S", title=f"T{i}", link=f"http://{i}", published_at=datetime.now(timezone.utc), guid=str(i))
        for i in range(5)
    ]
    monkeypatch.setattr(mi_pipeline.db_writer, "insert_news_item", lambda item: int(item.guid))
    monkeypatch.setattr(mi_pipeline.db_reader, "has_classified_event", lambda nid: False)
    monkeypatch.setattr(mi_pipeline.db_writer, "insert_classified_event", lambda nid, event: None)

    classifier = _FakeClassifier()
    mi_pipeline.collect_and_classify(_FakeCollector(items), classifier, max_new_classifications=2)

    assert classifier.calls == 2


def test_pipeline_empty_collection_returns_empty(monkeypatch):
    monkeypatch.setattr(mi_pipeline.db_writer, "insert_news_item", lambda item: 1)
    monkeypatch.setattr(mi_pipeline.db_reader, "has_classified_event", lambda nid: False)
    results = mi_pipeline.collect_and_classify(_FakeCollector([]), _FakeClassifier())
    assert results == []
