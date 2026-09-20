// 12B-option-risk-v1 -- mirrors backend/app/schemas/option_risk.py. ADVISORY / RESEARCH ONLY.
export interface LegState {
  type: string;
  strike: number | null;
  status: string;
  ltp?: number | null;
  bid?: number | null;
  ask?: number | null;
  mid?: number | null;
  spread_pct?: number | null;
  volume?: number | null;
  volume_change?: number | null;
  oi?: number | null;
  intraday_oi_change?: number | null;
  iv?: number | null;
  delta?: number | null;
  gamma?: number | null;
  theta?: number | null;
  vega?: number | null;
  greeks_status?: string;
  premium_change_pct?: number | null;
  premium_change_pts?: number | null;
  bid_qty?: number | null;
  ask_qty?: number | null;
}

export interface Trajectory {
  value: number | null;
  chg_1m: number | null;
  chg_3m: number | null;
  chg_5m: number | null;
  acceleration: number | null;
  label: string;
}

export interface UnderlyingState {
  minute: string;
  state: string;
  value: number | null;
  new_print: boolean;
  last_reliable_value: number | null;
  last_reliable_minute: string | null;
  age_minutes: number | null;
}

export interface PositionRisk {
  minute: string;
  position_label?: string;
  position_support: string;
  risk_state: string;
  risk_action: string;
  reasons: string[];
  own_mid: number | null;
  negative_families?: string[];
}

export interface OptionRiskMinute {
  minute: string;
  segment: string;
  snapshot_present: boolean;
  atm_strike: number | null;
  underlying: UnderlyingState;
  option_activity: { status: string; changed_legs: number | null; legs: number | null };
  closing_state: string;
  combination_state: string;
  market_state: string;
  ce: LegState;
  pe: LegState;
  trajectory: Record<string, Trajectory> | null;
  pressure: {
    label: string;
    CE_PRESSURE?: number | null;
    PE_PRESSURE?: number | null;
    OPTION_DIRECTIONAL_PRESSURE?: number | null;
    up_evidence?: string[];
    down_evidence?: string[];
  };
  implied: { implied_spot: number | null; gap_points: number | null; gap_percent: number | null; quality: string };
  position_risk: PositionRisk[];
  data_quality: string[];
}

export interface OptionRiskSummary {
  status: string;
  latest_minute?: string;
  underlying_state?: string;
  underlying_value?: number | null;
  last_reliable_underlying?: number | null;
  last_reliable_minute?: string | null;
  underlying_age_minutes?: number | null;
  closing_state?: string;
  options_state?: string;
  option_derived_state?: string;
  implied_spot?: number | null;
  implied_gap_points?: number | null;
  implied_gap_percent?: number | null;
  implied_quality?: string;
  confidence?: string;
  missing_option_minutes?: string[];
  stale_minutes?: number;
  options_active_while_stale?: number;
  new_print_minute?: string | null;
  new_print_value?: number | null;
  caveat: string;
}

export interface OptionRiskPosition {
  option_type: string;
  strike: number;
  entry_minute: string;
  exit_minute: string | null;
  entry_price?: number | null;
  is_open?: boolean;
  label: string;
}

export interface LtpPoint {
  minute: string;
  present: boolean;
  atm_strike?: number | null;
  ce_ltp?: number | null;
  pe_ltp?: number | null;
}

export interface OptionRiskClosingStateDTO {
  version: string;
  config_hash: string;
  symbol: string;
  session_date: string;
  as_of: string;
  is_live_session: boolean;
  advisory_only: boolean;
  caveat: string;
  positions: OptionRiskPosition[];
  minutes: OptionRiskMinute[];
  ltp_series: LtpPoint[];
  summary: OptionRiskSummary;
}
