"""Every Opportunity Matrix v1 research parameter, in one place (no hidden constants).

These are a-priori research definitions. None was selected by looking at
outcomes on any day; magnitudes that need a scale come from PRIOR-day
percentile distributions (see thresholds.py), never from fixed point values.
"""

import hashlib
import json
from dataclasses import asdict, dataclass, field

VERSION = "om1-v1"
DATASET_VERSION = "om1-dataset-v1"


@dataclass(frozen=True)
class OMConfig:
    # ---- windows (IST, [start, end)) ------------------------------------------------
    windows: dict = field(default_factory=lambda: {
        "PRE_STATE": ("14:30:00", "15:00:00"),
        "SETUP": ("14:55:00", "15:00:00"),
        "MODE_A_EARLY": ("15:00:00", "15:05:00"),
        "MODE_A_MIDDLE": ("15:05:00", "15:10:00"),
        "MODE_A_LATE": ("15:10:00", "15:15:00"),
        "OPTION_ONLY": ("15:15:00", "15:30:00"),
    })
    snapshot_times: tuple = ("14:30", "14:40", "14:45", "14:50", "14:55", "14:56", "14:57", "14:58", "14:59")
    hr_first_bar: str = "14:55:00"
    bar_seconds: int = 5
    symbols: tuple = ("NIFTY", "SENSEX")
    vp_bin_size: dict = field(default_factory=lambda: {"NIFTY": 5.0, "SENSEX": 25.0})

    # ---- chronology -----------------------------------------------------------------
    min_prior_hr_days: int = 2            # HR days used ONLY to seed thresholds (never called out-of-sample)
    prior_1min_days: int = 20             # prior trading days of 1-min candles for 1-min state thresholds
    target_hr_days: int = 22
    target_evaluable_symbol_days: int = 40
    split_fractions: tuple = (0.5, 0.25, 0.25)   # TRAIN / VALIDATION / UNSEEN over evaluable days, chronological

    # ---- 1-minute market state (percentile-based; fixed rule logic) --------------------
    atr_period_1min: int = 14
    vwap_slope_lookback_min: int = 10
    poc_migration_lookback_min: int = 30
    range_window_min: int = 15
    velocity_window_min: int = 5
    volume_accel_window_min: int = 5
    trend_min_conditions: int = 3         # of 4 directional conditions
    conflict_min_conditions: int = 2      # both sides >= this -> CONFLICTED
    dominance_up: float = 0.55            # Chaikin proxy share (definition boundary, symmetric)
    dominance_down: float = 0.45
    compression_pct: float = 25.0         # 15-min range <= prior p25 -> COMPRESSED
    expansion_vol_pct: float = 75.0       # compressed + volume acceleration >= prior p75 -> EXPANSION_SETUP
    reversal_velocity_pct: float = 75.0   # counter-trend 5-min move >= prior p75 -> REVERSAL_SETUP
    vwap_distance_pct: float = 50.0       # |dist/ATR| >= prior p50 counts as "away from VWAP"
    rvol_high: float = 1.2                # descriptive volume_state boundaries (label only, never a gate)
    rvol_low: float = 0.8

    # ---- setup state (14:55-14:59) ------------------------------------------------------
    setup_move_pct: float = 50.0          # |5-min return| >= prior p50 counts as pressure

    # ---- 5-second events ----------------------------------------------------------------
    detection_pct: float = 90.0           # |futures-mid 10 s| or |CE-PE 10 s| >= prior p90 -> trigger
    descriptor_pcts: tuple = (50.0, 75.0, 85.0, 90.0, 95.0)
    context_pct: float = 75.0             # prior 60 s move >= p75 -> reversal / continuation context
    cluster_gap_s: int = 60               # events < 60 s apart share an event_cluster_id
    lookback_bars: int = 12               # 60 s onset look-back for lead/lag and earlyness
    response_step_pct: float = 75.0       # first "move" = 5 s step >= prior p75
    sync_bars: int = 2                    # responses within 10 s = SYNCHRONIZED

    # ---- option response classes (10 s response of the direction leg vs prior pctls) -----
    strong_pct: float = 90.0
    moderate_pct: float = 75.0
    weak_pct: float = 50.0
    response_horizons_s: tuple = (5, 10, 15, 30)

    # ---- research approval gates (fixed a priori) ------------------------------------------
    approval_windows: tuple = ("MODE_A_EARLY", "MODE_A_MIDDLE", "MODE_A_LATE")
    approval_min_response: tuple = ("STRONG", "MODERATE")
    early_onset_s: int = 15
    mid_onset_s: int = 30                 # onset age > 30 s -> LATE_OPPORTUNITY (not approved)
    extension_pct: float = 90.0           # |5-min move| in direction >= prior p90 -> extended
    max_spread_pct: float = 1.0
    max_quote_age_s: float = 10.0
    min_volume_bars: int = 3              # traded volume in the last 15 s
    expiry_no_approval_from: str = "15:10:00"   # mirrors the existing 12A expiry restriction (never relaxed)

    # ---- entry / exit research -------------------------------------------------------------
    entry_offsets: dict = field(default_factory=lambda: {"event_bar": 0, "i+1": 1, "i+2": 2})
    executable_entries: tuple = ("i+1", "i+2")   # event-bar fill is NEVER executable
    primary_entry: str = "i+2"                   # current 5-s DB poller
    fixed_exits_s: tuple = (10, 15, 20, 30, 45, 60)
    trade_horizon_s: int = 60
    profit_levels: tuple = (0.5, 1.0, 2.0)
    hit_level_pct: float = 1.0          # '+1% before -1%' outcome metric (never an input)
    underlying_horizons_s: tuple = (5, 10, 15, 30, 60, 120, 180, 300)
    option_horizons_s: tuple = (5, 10, 15, 30, 60)
    leg_rule: str = "direction leg (CE for up, PE for down) at the strike nearest the futures mid at the decision bar -- fixed a priori, never chosen by outcome"
    strike_universe_offsets: int = 5
    no_progress_s: int = 20
    adverse_pct: float = -1.0
    giveback_activation_pct: float = 1.0
    giveback_frac: float = 0.5

    # ---- random baseline ---------------------------------------------------------------------
    baseline_per_event: int = 3
    baseline_seed: int = 20260919

    # ---- closing state (15:15-15:30) -----------------------------------------------------------
    implied_min_strikes: int = 5
    implied_move_pct: float = 75.0        # |implied 10 s change| >= prior p75 -> implied movement
    persistence_horizons_s: tuple = (5, 10, 15, 30, 60)
    persistence_keep_frac: float = 0.5    # >= 50% of the move still present = persisted
    gap_trend_bars: int = 6               # |gap| rising/falling over 30 s -> DIVERGING / CONVERGING

    # ---- news -------------------------------------------------------------------------------------
    news_lookback_min: int = 60

    def config_hash(self) -> str:
        blob = json.dumps({"version": VERSION, "dataset_version": DATASET_VERSION, "config": asdict(self)},
                          sort_keys=True, default=str).encode("utf-8")
        return hashlib.sha256(blob).hexdigest()[:16]

    def to_json(self) -> dict:
        return {"version": VERSION, "dataset_version": DATASET_VERSION, "config_hash": self.config_hash(), "parameters": asdict(self)}


DEFAULT = OMConfig()
