"""Shared data shapes for the Market Intelligence Engine -- pure dataclasses/
enums, no DB or API dependency, mirrored into backend DTOs and frontend
TypeScript types the same way analytics/volume_profile_intelligence.py is.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class EventCategory(str, Enum):
    RBI_MONETARY_POLICY = "RBI / Monetary Policy"
    GOVERNMENT_POLICY = "Government Policy"
    BUDGET_TAXATION = "Budget / Taxation"
    SEBI_REGULATORY = "SEBI / Regulatory"
    FEDERAL_RESERVE = "Federal Reserve"
    US_ECONOMIC_DATA = "US Economic Data"
    INFLATION_CPI_GDP = "Inflation / CPI / GDP"
    EMPLOYMENT_DATA = "Employment Data"
    FII_DII_FLOW = "FII / DII Flow"
    GEOPOLITICAL_CONFLICT = "Geopolitical Conflict"
    OIL_ENERGY = "Oil / Energy"
    CURRENCY = "Currency"
    GLOBAL_TECHNOLOGY = "Global Technology"
    CORPORATE_EARNINGS = "Large Corporate Earnings"
    MAJOR_LAYOFFS = "Major Layoffs"
    AI_SEMICONDUCTOR = "AI / Semiconductor Industry"
    BANKING_CRISIS = "Banking Crisis"
    NATURAL_DISASTER = "Natural Disaster"
    PANDEMIC = "Pandemic"
    ELECTION = "Election"
    POLITICAL_INSTABILITY = "Political Instability"
    TRADE_WAR = "Trade War"
    TARIFF_ANNOUNCEMENT = "Tariff Announcement"
    OTHER = "Other"


class Sentiment(str, Enum):
    BULLISH = "Bullish"
    BEARISH = "Bearish"
    NEUTRAL = "Neutral"


class Duration(str, Enum):
    MINUTES = "Minutes"
    INTRADAY = "Intraday"
    MULTI_DAY = "Multi-day"
    LONG_TERM = "Long-term"


class ImpactLevel(str, Enum):
    LOW = "Low"
    MEDIUM = "Medium"
    HIGH = "High"
    EXTREME = "Extreme"


class Direction(str, Enum):
    UP = "Up"
    DOWN = "Down"
    FLAT = "Flat"
    UNCERTAIN = "Uncertain"


@dataclass
class NewsItem:
    source: str
    title: str
    link: str
    published_at: datetime
    summary: str | None = None
    guid: str | None = None  # dedupe key, falls back to link


@dataclass
class ClassifiedEvent:
    news_item: NewsItem
    is_relevant: bool
    category: EventCategory
    severity: int  # 1-5
    confidence: float  # 0-1
    sentiment: Sentiment
    expected_duration: Duration
    volatility_impact: ImpactLevel
    reversal_probability: float  # 0-1
    affected_sectors: list[str]
    affected_indices: list[str]
    expected_direction_nifty: Direction
    expected_direction_sensex: Direction
    expected_direction_banknifty: Direction
    recommended_action: str
    risk_level: ImpactLevel
    rationale: str
    classified_at: datetime
    model: str
