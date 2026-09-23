// 13-live-trading-v1. Mirrors backend_control/main.py's status payload.

export interface LiveOpenPosition {
  correlation_id: string;
  contract_label: string;
  security_id: string;
  option_type: string;
  strike: number;
  quantity: number;
  entry_price: number;
  entry_cost: number | null;
  entry_at: string;
}

export interface LiveSymbolState {
  symbol: string;
  scheduled_today: boolean;
  armed: boolean;
  halted: boolean;
  halt_reason: string | null;
  kill_switch: boolean;
  entries_used: number;
  realised_pnl: number;
  open_position: LiveOpenPosition | null;
}

export interface LiveCaps {
  max_entries: number;
  lots: number;
  halt_after_first_loss: boolean;
  max_entry_cost: number;
  capital: number;
  entry_window: [string, string];
  min_confirmation: string;
  min_episode_minutes: number;
  force_flat_at: string;
}

export interface LiveJournalRow {
  at: string;
  symbol: string | null;
  minute: string | null;
  event: string;
  detail: string | null;
}

export interface LiveControlStatus {
  session_date: string;
  weekday: string;
  scheduled: string[];
  version: string;
  config_hash: string;
  dry_run_default: boolean;
  caps: LiveCaps;
  symbols: LiveSymbolState[];
  journal: LiveJournalRow[];
}
