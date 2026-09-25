// 13A-live-scalping-engine-v1. DECISION SUPPORT ONLY — no order path exists behind this.

export interface LiveScalpingPanelData {
  market: string;
  underlying: number | null;
  regime: string | null;
  regime_note: string | null;
  direction_note: string | null;
  underlying_confirmed: boolean | null;
  und_1m: number | null;
  und_3m: number | null;
  und_5m: number | null;
  option_confirmed: boolean | null;
  option_categories: string[];
  option_note: string | null;
  entry_timing: string | null;
  entry_timing_note: string | null;
  iv_state: string | null;
  iv_change_pct: number | null;
  spread: number | null;
  spread_pct: number | null;
  spread_ok: boolean | null;
  economics_ratio: number | null;
  economics_note: string | null;
  economics_ok: boolean | null;
  contract: string | null;
  strike: number | null;
  bid: number | null;
  ask: number | null;
  ltp: number | null;
  delta: number | null;
  iv: number | null;
  theta: number | null;
  quantity: number | null;
  entry_value: number | null;
}

export interface LiveRisk {
  state: string;
  lock_reasons: string[];
  allocated_capital: number;
  max_daily_loss: number;
  daily_realised_pnl: number;
  daily_unrealised_pnl: number;
  daily_total_pnl: number;
  remaining_daily_risk: number;
  consecutive_losses: number;
  max_consecutive_losses: number;
  trades_today: number;
  max_trades_per_day: number;
  open_position_value: number;
  max_position_value: number;
  note: string;
}

export interface LivePositionCard {
  contract?: string;
  strike?: number;
  entry_ask?: number;
  current_bid?: number;
  current_ask?: number;
  current_ltp?: number;
  quantity?: number;
  entry_value?: number;
  current_value?: number;
  pnl?: number;
  pnl_pct?: number;
  stop_loss?: number;
  distance_to_stop?: number;
  distance_to_stop_pct?: number;
  mfe?: number;
  mae?: number;
  hold_minutes?: number;
  quality?: string;
  exit_reason?: string | null;
  realised_pnl?: number | null;
  signal_minute?: string;
  exit_minute?: string | null;
  side?: string;
}

export interface DailyReview {
  total_decisions: number; buy_ce: number; buy_pe: number; wait: number;
  trades: number; wins: number; losses: number; realised_pnl: number;
  max_drawdown: number; max_consecutive_losses: number;
  rejected_range: number; rejected_reversing: number; rejected_extended: number;
  rejected_underlying: number; rejected_option: number; rejected_spread: number;
  rejected_economics: number; rejected_quality: number; rejected_risk_lock: number;
  rejected_no_base_signal: number; rejected_position_open: number;
}

// 13B-price-action-v1. A confirmation layer: it can veto a 13A BUY, never create one.
export interface PriceActionBlock {
  confirmation: string;
  reason: string;
  structure: string;
  structure_note: string;
  higher_high: boolean | null;
  higher_low: boolean | null;
  lower_high: boolean | null;
  lower_low: boolean | null;
  break_state: string;
  break_level: number | null;
  break_note: string;
  follow_through: boolean;
  setup: string;
  setup_note: string;
  vwap_state: string;
  vwap_distance_pct: number | null;
  vwap_note: string;
  value_state: string;
  value_note: string;
  volume_state: string;
  volume_ratio: number | null;
  volume_note: string;
  volume_confirms: boolean | null;
  agreeing_factors: number;
  contradicting_factors: string[];
  final_decision?: string;
  price_action_block?: boolean;
  final_price_action_state?: string;
  block_reason?: string | null;
  is_candidate?: boolean;
}

export interface LiveScalpingDTO {
  version: string;
  config_hash: string;
  mode: string;
  symbol: string;
  session_date: string;
  is_live_session: boolean;
  minute: string | null;
  decision: string;
  quality: string;
  primary_rejection_reason: string | null;
  reason_note: string | null;
  panel: LiveScalpingPanelData;
  risk: LiveRisk;
  open_position: LivePositionCard | null;
  closed_positions: LivePositionCard[];
  price_action: PriceActionBlock | null;
  daily_review: DailyReview | null;
  notice: string;
}
