"""Orchestrates News Collector -> dedupe -> Event Classifier -> persistence.
Deliberately thin: all the real logic lives in the collector/classifier
implementations (both swappable via their Protocol interfaces) and in
db/writer.py's upsert semantics -- this module just wires them together.
"""

import logging

from db import reader as db_reader
from db import writer as db_writer
from market_intelligence.classifiers.base import EventClassifier
from market_intelligence.collectors.base import NewsCollector
from market_intelligence.models import ClassifiedEvent

logger = logging.getLogger(__name__)


def collect_and_classify(
    collector: NewsCollector, classifier: EventClassifier, max_new_classifications: int | None = 30
) -> list[ClassifiedEvent]:
    """One pass: fetch news, persist every item seen (cheap upsert, so a
    partial run still makes progress for next time), classify only items
    not already classified in a prior run, up to `max_new_classifications`
    (a safety valve on API calls per run -- remaining items are picked up
    on the next run since their news_item row already exists unclassified).
    """
    items = collector.collect()
    logger.info("Collected %d news items", len(items))

    results: list[ClassifiedEvent] = []
    classified_this_run = 0
    for item in items:
        news_id = db_writer.insert_news_item(item)
        if db_reader.has_classified_event(news_id):
            continue
        if max_new_classifications is not None and classified_this_run >= max_new_classifications:
            continue

        classified = classifier.classify(item)
        classified_this_run += 1
        if classified is not None:
            db_writer.insert_classified_event(news_id, classified)
            results.append(classified)

    logger.info("Classified %d new items (%d relevant)", classified_this_run, sum(1 for r in results if r.is_relevant))
    return results
