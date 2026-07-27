"""One-shot Market Intelligence collection run: fetch news via RSS, classify
new items via Claude, persist both. Requires ANTHROPIC_API_KEY in .env.

Usage: venv\\Scripts\\python.exe scripts\\run_market_intelligence.py [--max-new N]
"""
import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from market_intelligence.classifiers.claude_classifier import ClaudeEventClassifier
from market_intelligence.collectors.rss_collector import RSSCollector
from market_intelligence.pipeline import collect_and_classify

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-new", type=int, default=30, help="Max new classifications this run (rate-limit safety valve)")
    args = parser.parse_args()

    results = collect_and_classify(RSSCollector(), ClaudeEventClassifier(), max_new_classifications=args.max_new)

    relevant = [r for r in results if r.is_relevant]
    print(f"Classified {len(results)} new items, {len(relevant)} marked relevant")
    for r in sorted(relevant, key=lambda r: -r.severity)[:10]:
        print(f"  [{r.severity}] {r.category.value} / {r.sentiment.value} -- {r.news_item.title[:80]}")


if __name__ == "__main__":
    main()
