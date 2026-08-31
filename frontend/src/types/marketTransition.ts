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
  // Independent-dimension reclassification (Phase 7A) -- additive, see
  // market_transition/cas_transition.py. `conclusion` above is untouched.
  transition_type:
    | "CONTINUATION_UP"
    | "CONTINUATION_DOWN"
    | "REVERSAL_UP"
    | "REVERSAL_DOWN"
    | "POST_WINDOW_INITIATION_UP"
    | "POST_WINDOW_INITIATION_DOWN"
    | "NO_MATERIAL_TRANSITION";
  magnitude_pct_return: number | null;
  magnitude_atr_normalized: number | null;
  magnitude_tier: "NORMAL" | "MODERATE" | "LARGE" | "EXTREME" | null;
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

// Phase 7B: dual-resolution pre/post-3pm transition detail, lazy-loaded
// per day. pre_transition_windows = FORECAST INFORMATION (14:30-14:59);
// post_transition_minutes = ACTUAL OUTCOME (15:00-15:15). Never merged --
// keep these visually distinct wherever rendered.
type DominantSide = "buy" | "sell" | "balanced";

export interface PreTransitionWindowDTO {
  window_index: number;
  window_label: string;
  open: number | null;
  close: number | null;
  high: number | null;
  low: number | null;
  net_point_change: number | null;
  pct_change: number | null;
  volume: number;
  rvol_pct: number | null;
  volume_acceleration_ratio: number | null;
  buy_volume_estimate: number | null;
  sell_volume_estimate: number | null;
  dominance_ratio: number;
  dominant_side: DominantSide;
  vwap_at_window_end: number | null;
  price_distance_from_vwap: number | null;
  price_distance_from_vwap_pct: number | null;
  vwap_slope: number | null;
  poc_at_window_end: number | null;
  poc_change_during_window: number | null;
  poc_slope: number | null;
  vah: number | null;
  val: number | null;
  pcr: number | null;
  pcr_change: number | null;
  call_oi_change: number | null;
  put_oi_change: number | null;
  iv_change: number | null;
  option_pressure_score: number | null;
  market_regime: string | null;
  institutional_bias_label: string | null;
  institutional_bias_score: number | null;
  news_risk_score: number | null;
  data_quality_flag: string | null;
}

export interface PostTransitionMinuteDTO {
  minute_offset: number;
  minute_time: string;
  close: number;
  price_change: number;
  volume: number;
  rvol_pct: number | null;
  dominance_ratio: number;
  dominant_side: DominantSide;
  poc_change: number | null;
  vwap_change: number | null;
  pcr_change: number | null;
  call_oi_change: number | null;
  put_oi_change: number | null;
  iv_change: number | null;
  option_pressure_score: number | null;
  range_expansion: number;
  transition_shock_score: number;
  is_closing_snapshot: boolean;
  data_quality_flag: string | null;
}

export interface TransitionForecastDTO {
  checkpoint_time: string;
  probability_no_material_transition: number;
  probability_large_up: number;
  probability_large_down: number;
  probability_reversal: number;
  probability_continuation: number;
  n_analogs: number;
  confidence_label: ConfidenceLabel;
  top_contributing_factors: ContributingFactorDTO[];
  historical_similarity_score: number;
}

export interface CasWindowedDetailResponseDTO {
  symbol: string;
  session_date: string;
  pre_transition_windows: PreTransitionWindowDTO[];
  post_transition_minutes: PostTransitionMinuteDTO[];
  forecasts: TransitionForecastDTO[];
}

// Phase 7C: historical cohorts + pre-3pm warning-indicator statistics --
// cohort-vs-rest comparison, complementary to the factor-correlation study
// above (CasIntelligenceResponseDTO.correlations), not a replacement.
export type CohortName =
  | "FLAT_LARGE_UP"
  | "FLAT_LARGE_DOWN"
  | "UP_REVERSAL_DOWN"
  | "DOWN_REVERSAL_UP"
  | "UP_CONTINUATION"
  | "DOWN_CONTINUATION"
  | "FLAT_NO_MATERIAL_MOVE";

export interface CohortFeatureStatDTO {
  feature_name: string;
  n: number;
  median: number | null;
  mean: number | null;
  percentile_within_full_sample: number | null;
  effect_size: number | null;
  statistic: number | null;
  p_value: number | null;
  confidence_label: ConfidenceLabel;
  direction_note: string | null;
}

export interface CohortCategoricalDTO {
  feature_name: string;
  n: number;
  category_counts: Record<string, number>;
  full_sample_category_counts: Record<string, number>;
}

export interface CohortResultDTO {
  cohort: CohortName;
  n_days: number;
  features: CohortFeatureStatDTO[];
  categorical: CohortCategoricalDTO[];
}

export interface CasCohortAnalysisResponseDTO {
  symbol: string;
  cohorts: CohortResultDTO[];
}
