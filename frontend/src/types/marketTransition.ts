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

// CAS Intelligence -- additive, parallel re-analysis of the 3pm transition
// under NSE's post-2026-08-03 Closing Auction Session framework. Does not
// replace the fields above.
export interface CasDailyResultDTO {
  session_date: string;
  close_1431: number | null;
  close_1459: number | null;
  close_1539: number | null;
  pre_direction: "up" | "down" | "flat" | null;
  post_direction: "up" | "down" | "flat" | null;
  conclusion: "continuation" | "reversal" | "neutral";
  outcome_magnitude: number | null;
  pre_window_volume: number | null;
  post_window_pre_auction_volume: number | null;
  volume_ratio: number | null;
  pre_window_points_move: number | null;
  post_window_points_move: number | null;
  pcr_1459: number | null;
  institutional_bias_label_1459: string | null;
  institutional_bias_score_1459: number | null;
  expiry_type: string | null;
  day_of_week: number | null;
  old_methodology_outcome: "continuation" | "reversal" | "neutral" | null;
  old_methodology_outcome_magnitude: number | null;
  data_quality_flag: string | null;
  computed_at: string;
}

export interface CasIntelligenceResponseDTO {
  symbol: string;
  total_days_analyzed: number;
  agreement_count: number;
  agreement_pct: number | null;
  daily_results: CasDailyResultDTO[];
  correlations: MtiFactorCorrelationDTO[];
}
