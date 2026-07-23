// Mirrors backend/app/schemas/volume_profile_intelligence.py exactly.

export interface DevelopingPointDTO {
  timestamp: string;
  poc: number;
  vah: number;
  val: number;
}

export interface VolumeNodeDTO {
  price: number;
  volume: number;
  kind: "hvn" | "lvn";
}

export interface ValueMigrationDTO {
  poc_shift: number;
  poc_shift_pct: number;
  direction: "up" | "down" | "flat";
  vah_shift: number;
  val_shift: number;
  intraday_poc_drift: number;
}

export interface LevelTestDTO {
  level_name: string;
  price: number;
  outcome: "accepted" | "rejected" | "untested";
  touches: number;
}

export interface ProfileShapeDTO {
  shape: "P" | "b" | "D" | "B";
  description: string;
}

export interface InitialBalanceDTO {
  ib_high: number;
  ib_low: number;
  ib_range: number;
  end_time: string;
  is_complete: boolean;
}

export interface OpeningTypeDTO {
  type: "Open-Drive" | "Open-Test-Drive" | "Open-Rejection-Reverse" | "Open-Auction";
  description: string;
}

export interface RotationFactorDTO {
  value: number;
  periods: number;
  label: "Trending" | "Rotational";
}

export interface VolumePaceDTO {
  pace_pct: number;
  today_cumulative: number;
  average_cumulative: number;
  label: "Above Average" | "Average" | "Below Average";
}

export interface VolumeProfileIntelligenceDTO {
  symbol: string;
  as_of: string | null;
  developing: DevelopingPointDTO[];
  hvns: VolumeNodeDTO[];
  lvns: VolumeNodeDTO[];
  migration: ValueMigrationDTO | null;
  level_tests: LevelTestDTO[];
  profile_shape: ProfileShapeDTO | null;
  initial_balance: InitialBalanceDTO | null;
  opening_type: OpeningTypeDTO | null;
  rotation_factor: RotationFactorDTO | null;
  volume_pace: VolumePaceDTO | null;
}
