"""Every 12C threshold in one place. All values are RESEARCH DEFAULTS, chosen a priori
from the instrument's own tick/noise scale -- none was fitted to historical outcomes.
Changing any value changes the config hash, which is stamped on every decision trace.
"""

import hashlib
import json
from dataclasses import asdict, dataclass, field

VERSION = "12C-scalp-decision-v1"

BUY_CE, BUY_PE, WAIT = "BUY_CE", "BUY_PE", "WAIT"
HOLD, CAUTION, PREPARE_EXIT, EXIT = "HOLD", "CAUTION", "PREPARE_EXIT", "EXIT"
CONFIRMATION = ("STRONG", "MODERATE", "WEAK", "NONE")
RISK_LEVELS = ("LOW", "NORMAL", "ELEVATED", "HIGH", "EXTREME")


@dataclass(frozen=True)
class DecisionConfig:
    # ---- underlying ------------------------------------------------------------------
    min_move_pts: dict = field(default_factory=lambda: {"NIFTY": 8.0, "SENSEX": 25.0})
    # basis: roughly one 1-minute noise band; below this a move is described as flat
    level_proximity_pts: dict = field(default_factory=lambda: {"NIFTY": 10.0, "SENSEX": 35.0})
    underlying_windows_min: tuple = (1, 3, 5)

    # ---- option premium / relative strength ---------------------------------------------
    premium_move_pct: float = 1.0        # |3-minute ATM premium change| that counts as a move
    strong_premium_pct: float = 2.5      # a clearly strong 3-minute move
    persistence_window: int = 3          # look at the last 3 one-minute changes
    persistence_min: int = 2             # >= 2 of 3 in the same direction = persistent (never a 1-minute spike)
    spike_ratio: float = 2.5             # 1m change >= 2.5x the 3m change and not persistent = spike

    # ---- participation / OI ---------------------------------------------------------------
    volume_strong_ratio: float = 1.3     # minute volume vs its own trailing 5-minute average
    volume_weak_ratio: float = 0.7
    oi_move_pct: float = 0.1             # |3-minute OI change %| below this carries no information

    # ---- liquidity / execution ------------------------------------------------------------
    good_spread_pct: float = 1.0
    wide_spread_pct: float = 3.0         # mirrors 11D's own quote-width rejection
    spread_widening_ratio: float = 1.5   # vs the position's entry spread

    # ---- straddle ---------------------------------------------------------------------------
    straddle_move_pct: float = 0.5
    severe_contraction_pct: float = -1.5  # strong premium contraction blocks a new entry

    # ---- entry gate ---------------------------------------------------------------------------
    min_support_for_entry: int = 4        # independent supporting categories
    max_contradictions_for_entry: int = 1
    strong_support: int = 5
    min_confirmation: str = "MODERATE"    # WEAK never becomes a BUY
    stale_underlying_needs_strong: bool = True   # with no live underlying, option evidence must be exceptional
    stale_min_support: int = 5                  # supporting categories required on option evidence alone

    # ---- risk brake ------------------------------------------------------------------------------
    core_families: tuple = ("MOMENTUM", "RELATIVE", "UNDERLYING")
    caution_min_families: int = 1
    prepare_exit_min_families: int = 3
    exit_min_families: int = 4
    exit_requires_broken_thesis: bool = True   # own momentum persistently negative
    low_risk_min_support: int = 2

    def config_hash(self) -> str:
        blob = json.dumps({"version": VERSION, "config": asdict(self)}, sort_keys=True, default=str).encode()
        return hashlib.sha256(blob).hexdigest()[:16]

    def to_json(self) -> dict:
        return {"version": VERSION, "config_hash": self.config_hash(), "parameters": asdict(self),
                "note": "RESEARCH DEFAULTS. Advisory only -- not validated trading rules."}


DEFAULT = DecisionConfig()
