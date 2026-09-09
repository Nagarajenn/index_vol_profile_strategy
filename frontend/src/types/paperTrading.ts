// Mirrors backend/app/schemas/paper_trading.py (hand-synced, matching this
// project's existing convention -- there is no shared codegen).
// PAPER MODE: every value here describes a simulated experiment. No real
// order is ever placed and all P&L is PRE-COST.

export interface PaperStatusDTO {
  paper_mode: boolean;
  agent_state: string;
  kill_switch_active: boolean;
  session_date: string | null;
  last_heartbeat: string | null;
  strategy_version: string;
  configuration_version: string;
  configuration_hash: string;
  experiment_day: number | null;
  experiment_total_days: number;
  underlying_data_age_sec: number | null;
  option_data_age_sec: number | null;
  database_ok: boolean;
}

export interface PaperAccountDTO {
  session_date: string | null;
  starting_capital: number;
  current_capital: number;
  available_capital: number;
  capital_in_trade: number;
  realized_pnl: number;
  unrealized_pnl: number;
  daily_pnl: number;
  total_pnl: number;
  daily_drawdown: number;
  max_drawdown: number;
  max_drawdown_pct: number;
  trade_count: number;
  win_count: number;
  loss_count: number;
  win_rate: number | null;
  consecutive_wins: number;
  consecutive_losses: number;
  average_win: number | null;
  average_loss: number | null;
  largest_win: number | null;
  largest_loss: number | null;
  profit_factor: number | null;
  pnl_basis: string;
}

export interface PaperDecisionDTO {
  symbol: string;
  session_date: string;
  decision_timestamp: string;
  decision: "TRADE_CALL" | "TRADE_PUT" | "NO_TRADE";
  decision_reason: string;
  no_trade_reason: string | null;
  trend_assessment: string;
  confidence: number;
  strategy_version: string;
  configuration_hash: string;
  spot: number | null;
  trend_label: string | null;
  institutional_bias_label: string | null;
  vwap: number | null;
  poc: number | null;
  support_low: number | null;
  support_high: number | null;
  resistance_low: number | null;
  resistance_high: number | null;
  atr_14: number | null;
  rvol_pct: number | null;
  dominant_side: string | null;
  pcr: number | null;
  atm_iv_call: number | null;
  atm_iv_put: number | null;
  transition_verdict: string | null;
  probability_up: number | null;
  probability_down: number | null;
  probability_no_move: number | null;
  expected_move_low: number | null;
  expected_move_high: number | null;
  transition_risk_tier: string | null;
  n_analogs: number | null;
  option_type: string | null;
  strike: number | null;
  expiry: string | null;
  entry_bid: number | null;
  entry_ask: number | null;
  entry_spread_pct: number | null;
  option_delta: number | null;
  dynamic_stop: number | null;
  dynamic_target: number | null;
  underlying_invalidation: number | null;
  underlying_target: number | null;
  reward_risk: number | null;
  quantity: number | null;
  capital_allocated: number | null;
  supporting_factors: string[];
  conflicting_factors: string[];
  risk_factors: string[];
  explanation: string[];
  data_quality: string;
  missing_fields: string[];
}

export interface PaperPositionEventDTO {
  event_timestamp: string;
  minutes_in_trade: number;
  event_type: string;
  underlying_price: number | null;
  option_bid: number | null;
  option_ask: number | null;
  unrealized_pnl: number | null;
  momentum: string | null;
  current_stop: number | null;
  current_target: number | null;
  note: string | null;
}

export interface PaperPositionDTO {
  id: number;
  symbol: string;
  session_date: string;
  option_type: string;
  strike: number;
  expiry: string | null;
  quantity: number;
  entry_timestamp: string;
  entry_bid: number | null;
  entry_ask: number | null;
  entry_spread_pct: number | null;
  entry_price: number;
  capital_allocated: number;
  spot_at_entry: number | null;
  initial_stop: number;
  initial_target: number;
  current_stop: number;
  current_target: number;
  is_open: boolean;
  exit_timestamp: string | null;
  exit_bid: number | null;
  exit_price: number | null;
  exit_reason: string | null;
  gross_pnl: number | null;
  net_pnl: number | null;
  pnl_basis: string;
  return_pct: number | null;
  mfe_pct: number | null;
  mae_pct: number | null;
  underlying_move: number | null;
  direction_correct: boolean | null;
  data_quality: string;
  events: PaperPositionEventDTO[];
}

export interface DecisionOutcomeDTO {
  symbol: string;
  session_date: string;
  decision: string;
  forecast_direction: string | null;
  actual_direction: string | null;
  direction_correct: boolean | null;
  option_profitable: boolean | null;
  net_pnl: number | null;
  decision_quality: string;
}

export interface PaperTodayDTO {
  session_date: string;
  status: PaperStatusDTO;
  account: PaperAccountDTO;
  decisions: PaperDecisionDTO[];
  open_position: PaperPositionDTO | null;
  closed_today: PaperPositionDTO[];
  outcomes: DecisionOutcomeDTO[];
}
