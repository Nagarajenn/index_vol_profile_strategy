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
}
