"""AI Correlation/Classification via the Claude API (Haiku, for low
per-event cost -- an explicit user decision, see product_requirements id=1).
Uses structured outputs (output_config.format) so the response is
guaranteed-valid JSON matching the schema below, rather than free-form text
that needs fragile parsing.

Response parsing is a separate pure function (_parse_response_json) so it's
unit-testable without a live API call -- the classifier class itself is a
thin wrapper around the Anthropic SDK call.
"""

import json
import logging
from datetime import datetime, timezone

import anthropic

from market_intelligence.models import (
    ClassifiedEvent,
    Direction,
    Duration,
    EventCategory,
    ImpactLevel,
    NewsItem,
    Sentiment,
)

logger = logging.getLogger(__name__)

# Haiku 4.5: cheap, fast, supports structured outputs -- does not support
# output_config.effort (errors on Haiku 4.5), so that parameter is never set.
DEFAULT_MODEL = "claude-haiku-4-5"

_CATEGORIES = [c.value for c in EventCategory]
_SENTIMENTS = [s.value for s in Sentiment]
_DURATIONS = [d.value for d in Duration]
_IMPACT_LEVELS = [i.value for i in ImpactLevel]
_DIRECTIONS = [d.value for d in Direction]

_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "is_relevant": {
            "type": "boolean",
            "description": "True only for a genuine market-moving event; false for routine/non-market news.",
        },
        "category": {"type": "string", "enum": _CATEGORIES},
        "severity": {"type": "integer", "enum": [1, 2, 3, 4, 5]},
        "confidence": {"type": "number", "description": "0.0-1.0 confidence in this classification"},
        "sentiment": {"type": "string", "enum": _SENTIMENTS},
        "expected_duration": {"type": "string", "enum": _DURATIONS},
        "volatility_impact": {"type": "string", "enum": _IMPACT_LEVELS},
        "reversal_probability": {
            "type": "number",
            "description": "0.0-1.0 probability this event reverses/invalidates a prevailing technical trend",
        },
        "affected_sectors": {"type": "array", "items": {"type": "string"}},
        "affected_indices": {"type": "array", "items": {"type": "string"}},
        "expected_direction_nifty": {"type": "string", "enum": _DIRECTIONS},
        "expected_direction_sensex": {"type": "string", "enum": _DIRECTIONS},
        "expected_direction_banknifty": {"type": "string", "enum": _DIRECTIONS},
        "recommended_action": {"type": "string", "description": "One or two sentences, decision-support framing"},
        "risk_level": {"type": "string", "enum": _IMPACT_LEVELS},
        "rationale": {"type": "string", "description": "Brief inference explanation, not a summary of the headline"},
    },
    "required": [
        "is_relevant", "category", "severity", "confidence", "sentiment", "expected_duration",
        "volatility_impact", "reversal_probability", "affected_sectors", "affected_indices",
        "expected_direction_nifty", "expected_direction_sensex", "expected_direction_banknifty",
        "recommended_action", "risk_level", "rationale",
    ],
    "additionalProperties": False,
}

_SYSTEM_PROMPT = (
    "You are a market-intelligence analyst for an intraday Indian equity index "
    "options desk trading NIFTY, SENSEX, and BANKNIFTY. Given one news headline "
    "and summary, INFER its likely trading impact -- do not just summarize the "
    "news. Base severity, sentiment, and direction on genuine market-moving "
    "potential, not on how dramatic the headline sounds. Mark is_relevant=false "
    "for routine corporate PR, generic listicles, unrelated sports/entertainment, "
    "or stale recycled news with no fresh market implication."
)


def _build_user_content(item: NewsItem) -> str:
    return (
        f"Source: {item.source}\n"
        f"Headline: {item.title}\n"
        f"Summary: {item.summary or '(none)'}\n"
        f"Published: {item.published_at.isoformat()}"
    )


def _parse_response_json(data: dict, item: NewsItem, model: str) -> ClassifiedEvent:
    """Pure JSON-dict -> ClassifiedEvent mapping, kept separate from the API
    call so it's testable with a hand-built dict, no network required."""
    return ClassifiedEvent(
        news_item=item,
        is_relevant=data["is_relevant"],
        category=EventCategory(data["category"]),
        severity=data["severity"],
        confidence=data["confidence"],
        sentiment=Sentiment(data["sentiment"]),
        expected_duration=Duration(data["expected_duration"]),
        volatility_impact=ImpactLevel(data["volatility_impact"]),
        reversal_probability=data["reversal_probability"],
        affected_sectors=data["affected_sectors"],
        affected_indices=data["affected_indices"],
        expected_direction_nifty=Direction(data["expected_direction_nifty"]),
        expected_direction_sensex=Direction(data["expected_direction_sensex"]),
        expected_direction_banknifty=Direction(data["expected_direction_banknifty"]),
        recommended_action=data["recommended_action"],
        risk_level=ImpactLevel(data["risk_level"]),
        rationale=data["rationale"],
        classified_at=datetime.now(timezone.utc),
        model=model,
    )


class ClaudeEventClassifier:
    def __init__(self, client: anthropic.Anthropic | None = None, model: str = DEFAULT_MODEL) -> None:
        self._client = client or anthropic.Anthropic()
        self._model = model

    def classify(self, item: NewsItem) -> ClassifiedEvent | None:
        try:
            response = self._client.messages.create(
                model=self._model,
                max_tokens=1024,
                system=_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": _build_user_content(item)}],
                output_config={"format": {"type": "json_schema", "schema": _RESPONSE_SCHEMA}},
            )
        except anthropic.APIError as e:
            logger.warning("Classification failed for %r: %s", item.title[:60], e)
            return None

        text = next((b.text for b in response.content if b.type == "text"), None)
        if text is None:
            logger.warning("No text block in classification response for %r", item.title[:60])
            return None

        try:
            data = json.loads(text)
            return _parse_response_json(data, item, self._model)
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.warning("Malformed classification response for %r: %s", item.title[:60], e)
            return None
