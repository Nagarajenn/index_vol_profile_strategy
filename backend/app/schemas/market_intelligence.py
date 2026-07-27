"""DTOs mirroring market_intelligence/models.py's ClassifiedEvent/NewsItem
dataclasses. Served only by GET /api/v1/market-intelligence/latest --
informational, does not feed the strategy engine.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

EventCategoryLiteral = Literal[
    "RBI / Monetary Policy", "Government Policy", "Budget / Taxation", "SEBI / Regulatory",
    "Federal Reserve", "US Economic Data", "Inflation / CPI / GDP", "Employment Data",
    "FII / DII Flow", "Geopolitical Conflict", "Oil / Energy", "Currency",
    "Global Technology", "Large Corporate Earnings", "Major Layoffs",
    "AI / Semiconductor Industry", "Banking Crisis", "Natural Disaster", "Pandemic",
    "Election", "Political Instability", "Trade War", "Tariff Announcement", "Other",
]


class MarketIntelligenceEventDTO(BaseModel):
    source: str
    title: str
    link: str
    published_at: datetime | None
    is_relevant: bool
    category: EventCategoryLiteral
    severity: int
    confidence: float
    sentiment: Literal["Bullish", "Bearish", "Neutral"]
    expected_duration: Literal["Minutes", "Intraday", "Multi-day", "Long-term"]
    volatility_impact: Literal["Low", "Medium", "High", "Extreme"]
    reversal_probability: float
    affected_sectors: list[str]
    affected_indices: list[str]
    expected_direction_nifty: Literal["Up", "Down", "Flat", "Uncertain"]
    expected_direction_sensex: Literal["Up", "Down", "Flat", "Uncertain"]
    expected_direction_banknifty: Literal["Up", "Down", "Flat", "Uncertain"]
    recommended_action: str
    risk_level: Literal["Low", "Medium", "High", "Extreme"]
    rationale: str
    classified_at: datetime


class MarketIntelligenceSummaryDTO(BaseModel):
    """Aggregated read across recent events -- the dashboard's at-a-glance
    "Current Market Sentiment" / "News Risk Score" fields, computed here
    (not persisted) from the same event list the panel already lists.
    """

    overall_sentiment: Literal["Bullish", "Bearish", "Neutral"]
    news_risk_score: int  # 0-100, higher = more caution warranted
    last_updated: datetime | None
    events: list[MarketIntelligenceEventDTO]
