// 12C-scalp-decision-v1 -- mirrors backend/app/schemas/scalp_decision.py. ADVISORY ONLY.
export interface EvidenceCategory {
  category: string;
  state: string;
  detail: Record<string, unknown>;
  note: string;
}

export interface BrakeItem {
  family: string;
  text: string;
}

export interface RiskBrake {
  position: string;
  option_type: string;
  risk_level: string;
  risk_action: string;
  against: BrakeItem[];
  supporting: BrakeItem[];
  families_against: string[];
  families_supporting: string[];
  n_against: number;
  n_supporting: number;
  thesis_broken: boolean;
  summary: string;
  reason: string;
  advisory_only: boolean;
}

export interface EntryDecision {
  decision: string;
  confirmation: string;
  side: string | null;
  supporting: [string, string][];
  contradicting: [string, string][];
  blocking: [string, string][];
  reason: string;
  held_minutes?: number;
  required_confirmation?: string;
}

export interface ClosingRow {
  minute: string;
  present: boolean;
  ce_premium?: number | null;
  pe_premium?: number | null;
  ce_1m?: number | null;
  pe_1m?: number | null;
  relative?: string;
  ce_volume?: number | null;
  pe_volume?: number | null;
  ce_oi?: number | null;
  pe_oi?: number | null;
  underlying_state?: string;
  options?: string;
}

export interface SimulatedPosition {
  contract: string;
  symbol: string;
  side: string;
  strike: number | null;
  expiry: string | null;
  status: string;
  signal_minute: string;
  entry_minute: string;
  entry_price: number | null;          // ASK paid
  entry_price_type: string;
  entry_price_status: string;
  entry_bid_at_signal?: number | null;
  entry_ltp_at_signal?: number | null;
  quantity: number | null;
  quantity_status: string;
  quantity_source?: string;
  current: { minute: string | null; ltp: number | null; bid: number | null; ask: number | null; spread_pct: number | null; data_status: string };
  since_signal: { entry_ask: number | null; current_bid: number | null; price_change: number | null; pnl: number | null; pnl_pct: number | null; pnl_status: string };
  pnl: number | null;
  pnl_per_unit: number | null;
  pnl_pct: number | null;
  pnl_status: string;
  entry_value: number | null;
  current_value: number | null;
  stop_loss_price: number | null;
  stop_loss_pct: number;
  distance_to_stop: number | null;
  distance_to_stop_pct: number | null;
  stop_buffer_left: number | null;
  stop_breached: boolean | null;
  stop_breach_minute: string | null;
  excursions: { status: string; mfe?: number | null; mae?: number | null; mfe_per_unit?: number | null; mae_per_unit?: number | null; mfe_pct?: number | null; mae_pct?: number | null };
  hold_minutes: number;
  hold_text: string;
  risk: { risk_state: string; reasons: string[]; families_against: string[]; stop_buffer_left: number | null };
  exit_minute: string | null;
  exit_bid: number | null;
  exit_reason: string | null;
  realised_pnl: number | null;
  realised_pnl_pct: number | null;
  notice: string;
}

export interface PositionSimulation {
  version: string;
  config_hash: string;
  symbol: string;
  as_of: string | null;
  open_position: SimulatedPosition | null;
  closed_positions: SimulatedPosition[];
  counts: { opened: number; closed: number; unavailable: number };
  advisory_only: boolean;
}

export interface ScalpDecisionDTO {
  version: string;
  config_hash: string;
  symbol: string;
  session_date: string;
  minute: string | null;
  status: string;
  position_state: string | null;
  is_live_session: boolean;
  position_source: string | null;
  advisory_only: boolean;
  notice: string | null;
  decision: string | null;
  confirmation: string | null;
  reason: string | null;
  entry: EntryDecision | null;
  risk_brake: RiskBrake | null;
  evidence: Record<string, EvidenceCategory> | null;
  summary: {
    direction: string;
    underlying_state: string;
    options: string;
    decision: string;
    confirmation: string;
    reason: string;
    risk_level: string | null;
    risk_action: string | null;
    risk_summary: string | null;
    held_minutes?: number | null;
    evidence_row: Record<string, string>;
    data_quality: string[];
  } | null;
  option_state: Record<string, unknown> | null;
  closing_state: ClosingRow[];
  levels: Record<string, unknown> | null;
  trace: Record<string, unknown> | null;
  position_simulation: PositionSimulation | null;
  signal_learning: SignalLearningBlock | null;
}

// 12D-signal-learning-v1. Where in the move the signal landed. Observation only: these labels
// change no 12C rule, and the boundaries behind them are provisional, not validated.
export interface SignalLearningBlock {
  applies_to: string | null;
  is_signal: boolean;
  direction: string;
  entry_timing: string;
  entry_timing_note: string;
  entry_timing_provisional: boolean;
  momentum_state: string;
  momentum_note: string;
  exhaustion_state: string;
  exhaustion_note: string;
  signal_age_minutes: number | null;
  caveat: string;
}

// Closed hypothetical positions. SIMULATION ONLY -- not orders, not paper-account trades.
export interface SimPositionRow {
  symbol: string;
  session_date: string;
  signal_minute: string;
  entry_minute: string;
  entry_confirmation: string | null;
  side: string;
  strike: number | null;
  contract: string | null;
  entry_price: number | null;
  entry_ltp: number | null;
  quantity: number | null;
  entry_value: number | null;
  stop_loss_price: number | null;
  stop_breach_minute: string | null;
  exit_minute: string | null;
  exit_bid: number | null;
  exit_reason: string | null;
  closing_decision: string | null;
  closing_confirmation: string | null;
  closing_reason: string | null;
  risk_state_at_exit: string | null;
  realised_pnl: number | null;
  realised_pnl_pct: number | null;
  mfe: number | null;
  mae: number | null;
  hold_minutes: number | null;
}

export interface SimPositionHistoryDTO {
  symbol: string;
  session_date: string | null;
  source: string;                 // STORED | LIVE_REPLAY
  positions: SimPositionRow[];
  summary: {
    positions: number;
    priced: number;
    wins: number;
    losses: number;
    gross: number | null;
    best: number | null;
    worst: number | null;
    closed_by: Record<string, number>;
  };
  advisory_only: boolean;
}
