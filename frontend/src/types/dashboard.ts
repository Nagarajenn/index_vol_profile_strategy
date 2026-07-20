// Mirrors backend/app/schemas/*.py exactly -- keep in sync by hand for V1
// (no shared codegen yet; if the Pydantic DTOs change, update here too).

export interface CandleDTO {
  timestamp: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface OptionChainSummaryDTO {
  pcr: number | null;
  atm_strike: number | null;
  atm_iv_call: number | null;
  atm_iv_put: number | null;
}

export interface LevelsSummaryDTO {
  close: number;
  vwap_now: number | null;
  today_poc: number | null;
  today_vah: number | null;
  today_val: number | null;
  support_low: number | null;
  support_high: number | null;
  resistance_low: number | null;
  resistance_high: number | null;
  trend_label: string | null;
  trend_score: number | null;
  institutional_bias_label: string | null;
  confidence_score: number | null;
  action_text: string | null;
  interpretation: string | null;
}

export type DashboardStatus = "live" | "stale" | "no_data";

export interface DashboardResponseDTO {
  symbol: string;
  status: DashboardStatus;
  as_of: string | null;
  staleness_seconds: number | null;
  is_market_hours: boolean;
  levels: LevelsSummaryDTO | null;
  candles: CandleDTO[];
  option_chain: OptionChainSummaryDTO | null;
}

export interface SymbolInfoDTO {
  symbol: string;
  exchange: string;
}
