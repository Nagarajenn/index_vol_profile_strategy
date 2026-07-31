// Mirrors backend/app/schemas/market_transition.py exactly.

export type ConfidenceLabel = "Strong" | "Moderate" | "Weak" | "Not significant" | "Insufficient data";

export interface ContributingFactorDTO {
  factor_name: string;
  today_value: string;
  note: string;
  contribution: number;
}

export interface MtiFactorCorrelationDTO {
  factor_name: string;
  factor_type: "continuous" | "categorical";
  target: "reversal" | "magnitude";
  n_days: number;
  statistic: number | null;
  p_value: number | null;
  confidence_label: ConfidenceLabel;
  direction_note: string | null;
  category_breakdown: Record<string, { n: number; reversal_rate?: number }> | null;
}

export interface MtiDailyResultDTO {
  session_date: string;
  profile_shape_1459: string | null;
  market_regime_1459: string | null;
  expiry_type: string | null;
  transition_direction: "up" | "down" | "flat";
  transition_move: number;
  post_transition_move: number;
  outcome: "continuation" | "reversal" | "neutral";
  outcome_magnitude: number;
  transition_risk_score: number | null;
  probability_continuation: number | null;
  probability_reversal: number | null;
  expected_volatility: number | null;
  expected_direction: string | null;
  historical_similarity_score: number | null;
  top_contributing_factors: ContributingFactorDTO[];
  statistical_confidence: ConfidenceLabel | null;
  explanation: string | null;
  computed_at: string | null;
  predicted_outcome: "reversal" | "continuation" | null;
  forecast_correct: boolean | null;
}

export interface MtiResearchResponseDTO {
  symbol: string;
  total_days_analyzed: number;
  correlations: MtiFactorCorrelationDTO[];
  daily_results: MtiDailyResultDTO[];
  forecast_evaluable_days: number;
  forecast_hit_count: number;
  forecast_accuracy_pct: number | null;
}
