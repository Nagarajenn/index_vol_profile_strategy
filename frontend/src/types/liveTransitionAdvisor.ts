// Mirrors backend/app/schemas/market_transition.py's Live Advisor DTOs exactly.

export type TransitionStage =
  | "Not Yet Active"
  | "Pre-Transition Monitoring"
  | "Transition Window"
  | "Post-Transition Follow-Through"
  | "Session Complete";

export type TransitionRiskLevel = "Observe" | "Low" | "Medium" | "High" | "Very High";
export type ConfidenceLabel = "Strong" | "Moderate" | "Weak" | "Not significant" | "Insufficient data";

export interface MostSimilarDayDTO {
  session_date: string;
  distance: number;
  similarity: number;
  outcome: "continuation" | "reversal" | "neutral";
  transition_direction: "up" | "down" | "flat";
}

export interface TransitionTimingEstimateDTO {
  earliest: string | null;
  latest: string | null;
  n_analogs_with_onset: number;
  note: string;
}

export interface ContributingFactorDTO {
  factor_name: string;
  today_value: string;
  note: string;
  contribution: number;
}

export interface LiveAdvisoryDTO {
  symbol: string;
  session_date: string;
  as_of: string;
  stage: TransitionStage;
  is_active: boolean;
  historical_similarity_score: number;
  most_similar_days: MostSimilarDayDTO[];
  expected_direction: "up" | "down" | "flat";
  probability_continuation: number;
  probability_reversal: number;
  expected_volatility: number;
  expected_timing: TransitionTimingEstimateDTO | null;
  estimated_move: number;
  risk_level: TransitionRiskLevel;
  statistical_confidence: ConfidenceLabel;
  top_contributing_factors: ContributingFactorDTO[];
  institutional_bias_label: string | null;
  news_risk_score: number | null;
  news_sentiment: "Bullish" | "Bearish" | "Neutral" | null;
  explanation: string;
}
