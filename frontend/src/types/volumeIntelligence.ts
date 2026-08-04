// Mirrors backend/app/schemas/volume_intelligence.py exactly.

export type BaselineGroup = "yesterday" | "last_5_days" | "last_20_days" | "same_weekday" | "expiry_day" | "monthly_expiry_day";
export type RvolLabel = "Above Average" | "Average" | "Below Average";
export type DominantSide = "buy" | "sell" | "balanced";
export type AccelerationLabel = "Accelerating" | "Stable" | "Decelerating";
export type MomentumLabel = "Strong Buy Momentum" | "Buy Momentum" | "Neutral" | "Sell Momentum" | "Strong Sell Momentum";
export type InstitutionalLabel = "Minimal" | "Low" | "Moderate" | "High" | "Very High";
export type VolumeTrendLabel = "Strong Increasing" | "Increasing" | "Stable" | "Decreasing" | "Strong Decreasing";
export type VolumeCharacterLabel = "Accumulation" | "Distribution" | "Markup" | "Markdown" | "Climactic" | "Quiet-Consolidation";
export type ExhaustionDirection = "up" | "down";
export type ResemblanceLabel =
  | "accumulation-like sessions"
  | "distribution-like sessions"
  | "climactic/high-volume sessions"
  | "quiet/low-volume sessions"
  | "mixed/typical sessions";
export type ForecastConfidence = "Low" | "Medium" | "High";

export interface RvolBaselineResultDTO {
  group: BaselineGroup;
  interval_rvol_pct: number | null;
  cumulative_rvol_pct: number | null;
  label: RvolLabel | null;
  sample_days: number;
}

export interface RvolReadingDTO {
  by_baseline: Partial<Record<BaselineGroup, RvolBaselineResultDTO>>;
  primary: RvolBaselineResultDTO | null;
}

export interface VolumeAccelerationDTO {
  recent_avg_volume: number;
  prior_avg_volume: number;
  ratio: number | null;
  pct_change: number | null;
  label: AccelerationLabel;
}

export interface VolumeSpikeDTO {
  is_spike: boolean;
  multiple: number | null;
  baseline_source: "historical_20d" | "intraday_rolling" | null;
  baseline_volume: number | null;
}

export interface VolumeDryUpDTO {
  is_dryup: boolean;
  fraction: number | null;
  baseline_source: "historical_20d" | "intraday_rolling" | null;
  baseline_volume: number | null;
}

export interface BuySellDominanceDTO {
  window_minutes: number;
  buy_volume: number;
  sell_volume: number;
  dominance_ratio: number;
  dominant_side: DominantSide;
  consecutive_dominant_minutes: number;
}

export interface CumulativePressureDTO {
  cum_buy_volume: number;
  cum_sell_volume: number;
  net_pressure: number;
  pressure_ratio: number;
}

export interface VolumeMomentumDTO {
  ema_signed_volume: number;
  normalized_score: number;
  streak_minutes: number;
  label: MomentumLabel;
}

export interface InstitutionalParticipationDTO {
  score: number;
  label: InstitutionalLabel;
  rvol_component: number;
  blockiness_component: number;
  dominance_component: number;
}

export interface AbsorptionSignalDTO {
  detected: boolean;
  range_ratio: number | null;
  volume_multiple: number | null;
  side_hint: "buy_absorption" | "sell_absorption" | "undetermined";
}

export interface ExhaustionSignalDTO {
  detected: boolean;
  direction: ExhaustionDirection | null;
  move_over_window: number | null;
  volume_multiple: number | null;
  wick_ratio: number | null;
}

export interface VolumeTrendDTO {
  window_minutes: number;
  pct_change: number | null;
  label: VolumeTrendLabel;
}

export interface VolumeCharacterDTO {
  label: VolumeCharacterLabel;
  rationale: string;
}

export interface SimilarDayDTO {
  session_date: string;
  distance: number;
  similarity: number;
  dominant_side: DominantSide;
  total_volume_ratio: number;
}

export interface HistoricalSimilarityDTO {
  top_days: SimilarDayDTO[];
  resemblance_label: ResemblanceLabel | null;
  n_days_compared: number;
}

export interface NextIntervalForecastDTO {
  horizon_minutes: number;
  probability_continuation: number;
  probability_reversal: number;
  confidence: ForecastConfidence;
  supporting_factors: string[];
  composite_score: number;
}

export interface VolumeNarrativeDTO {
  headline: string;
  observations: string[];
}

export interface VolumeIntelligenceDTO {
  symbol: string;
  as_of: string | null;
  rvol: RvolReadingDTO | null;
  acceleration: VolumeAccelerationDTO | null;
  dominance: BuySellDominanceDTO | null;
  cumulative_pressure: CumulativePressureDTO | null;
  momentum: VolumeMomentumDTO | null;
  institutional: InstitutionalParticipationDTO | null;
  spike: VolumeSpikeDTO | null;
  dryup: VolumeDryUpDTO | null;
  absorption: AbsorptionSignalDTO | null;
  exhaustion: ExhaustionSignalDTO | null;
  trend: VolumeTrendDTO | null;
  character: VolumeCharacterDTO | null;
  similarity: HistoricalSimilarityDTO | null;
  forecast: NextIntervalForecastDTO | null;
  narrative: VolumeNarrativeDTO | null;
}
