// Mirrors backend/app/schemas/session_amd.py exactly.

export type SweepDirection = "swept_high" | "swept_low";
export type DistributionDirection = "up" | "down";
export type DistributionStatus = "Confirmed" | "Developing" | "Failed";
export type CurrentPhase =
  | "Accumulating"
  | "Range Established -- Awaiting Move"
  | "Testing Range"
  | "Distribution"
  | "Breakout (not manipulation)"
  | "No Clear Setup";

export interface AccumulationRangeDTO {
  high: number;
  low: number;
  range: number;
  start_time: string;
  end_time: string;
  is_complete: boolean;
}

export interface ManipulationSweepDTO {
  direction: SweepDirection;
  extreme_price: number;
  breakout_time: string;
  reversal_time: string;
  candles_to_reverse: number;
  expected_distribution_direction: DistributionDirection;
}

export interface DistributionPhaseDTO {
  direction: DistributionDirection;
  started_at: string;
  net_move_points: number;
  net_move_pct: number;
  dominant_side_confirms: boolean | null;
  status: DistributionStatus;
}

export interface SessionAmdDTO {
  symbol: string;
  as_of: string | null;
  accumulation: AccumulationRangeDTO | null;
  sweeps: ManipulationSweepDTO[];
  latest_sweep: ManipulationSweepDTO | null;
  distribution: DistributionPhaseDTO | null;
  current_phase: CurrentPhase;
  narrative: string;
}
