// Mirrors backend/app/schemas/market_intelligence.py exactly.

export type EventCategory =
  | "RBI / Monetary Policy"
  | "Government Policy"
  | "Budget / Taxation"
  | "SEBI / Regulatory"
  | "Federal Reserve"
  | "US Economic Data"
  | "Inflation / CPI / GDP"
  | "Employment Data"
  | "FII / DII Flow"
  | "Geopolitical Conflict"
  | "Oil / Energy"
  | "Currency"
  | "Global Technology"
  | "Large Corporate Earnings"
  | "Major Layoffs"
  | "AI / Semiconductor Industry"
  | "Banking Crisis"
  | "Natural Disaster"
  | "Pandemic"
  | "Election"
  | "Political Instability"
  | "Trade War"
  | "Tariff Announcement"
  | "Other";

export type Sentiment = "Bullish" | "Bearish" | "Neutral";
export type Duration = "Minutes" | "Intraday" | "Multi-day" | "Long-term";
export type ImpactLevel = "Low" | "Medium" | "High" | "Extreme";
export type Direction = "Up" | "Down" | "Flat" | "Uncertain";

export interface MarketIntelligenceEventDTO {
  source: string;
  title: string;
  link: string;
  published_at: string | null;
  is_relevant: boolean;
  category: EventCategory;
  severity: number;
  confidence: number;
  sentiment: Sentiment;
  expected_duration: Duration;
  volatility_impact: ImpactLevel;
  reversal_probability: number;
  affected_sectors: string[];
  affected_indices: string[];
  expected_direction_nifty: Direction;
  expected_direction_sensex: Direction;
  expected_direction_banknifty: Direction;
  recommended_action: string;
  risk_level: ImpactLevel;
  rationale: string;
  classified_at: string;
}

export interface MarketIntelligenceSummaryDTO {
  overall_sentiment: Sentiment;
  news_risk_score: number;
  last_updated: string | null;
  events: MarketIntelligenceEventDTO[];
}
