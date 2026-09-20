"""Every 12B parameter in one place. All thresholds are RESEARCH DEFAULTS.

None was selected by looking at outcomes. Each carries the basis for its value.
Changing any value changes the config hash, which is stamped on every output.
"""

import hashlib
import json
from dataclasses import asdict, dataclass, field

VERSION = "12B-option-risk-v1"


@dataclass(frozen=True)
class RiskConfig:
    # ---- windows (IST) -------------------------------------------------------------
    window_start: str = "15:15"          # primary research window start
    window_end: str = "15:30"            # primary research window end (inclusive minute)
    context_start: str = "15:00"         # 15:00-15:14 shown as ACTUAL UNDERLYING context
    lookback_start: str = "14:55"        # trajectory look-back (3m / 5m changes at 15:00)
    ltp_chart_start: str = "14:30"       # the ATM CE/PE last-traded-price series starts earlier than the risk window
    load_end: str = "15:40"              # snapshots after 15:30 kept only for the audit / next print

    # ---- universe --------------------------------------------------------------------
    strikes_each_side: int = 5           # raw layer ATM +/- 5
    display_strikes_each_side: int = 2   # primary display ATM +/- 2
    symbols: tuple = ("NIFTY", "SENSEX")

    # ---- underlying state ---------------------------------------------------------------
    stale_after_minutes: int = 2         # basis: 1-min capture; >= 2 identical consecutive prints = not updating
    underlying_move_pts: dict = field(default_factory=lambda: {"NIFTY": 5.0, "SENSEX": 15.0})
    # basis: roughly one NIFTY/SENSEX tick-cluster; below this a live move is FLAT (description only)

    # ---- option activity / quality ----------------------------------------------------------
    active_min_changed_legs: int = 4     # >= 4 of the ATM+/-5 legs' mids changed vs previous minute = options ACTIVE
    wide_spread_pct: float = 3.0         # basis: 11D rejects quotes wider than 3 % (reused as a label, not a gate)
    spread_expansion_ratio: float = 1.5  # spread % >= 1.5 x its 15:15 value = EXPANDING

    # ---- trajectory ------------------------------------------------------------------------
    horizons_min: tuple = (1, 3, 5)
    flat_pct: dict = field(default_factory=lambda: {"premium": 0.5, "volume": 5.0, "oi": 0.1, "iv": 0.5,
                                                    "straddle": 0.3, "pcr": 0.5})
    # basis: |3m change %| below these is described as FLAT (premium 0.5 % ~ one tick on a 20-rupee option)
    accel_min_pct: float = 0.3           # |change in 1m change| below this is not called accelerating

    # ---- pressure normalisation (tanh(x / scale)) -------------------------------------------
    scale_premium_pct: float = 3.0       # a 3 % 3-minute premium move maps to tanh(1) = 0.76
    scale_volume_accel: float = 1.0      # (1m volume delta / trailing mean delta) - 1
    scale_delta_change: float = 0.03     # 0.03 delta in 3 minutes ~ a clear move for an ATM option
    scale_rel_strength_pct: float = 4.0  # CE% - PE% over 3 minutes
    directional_threshold: float = 0.25  # |OPTION_DIRECTIONAL_PRESSURE| >= 0.25 -> UP / DOWN, else NEUTRAL

    # ---- position risk (count of independent evidence categories) ------------------------------
    adverse_premium_pct: float = -1.0    # own premium 2m change <= -1 % counts as adverse evidence
    favourable_premium_pct: float = 1.0
    opposite_rise_pct: float = 1.0
    iv_collapse_pts: float = -0.5        # IV points in 2 minutes
    # Independent evidence FAMILIES. Signals inside one family describe the same observation (e.g. own
    # premium falling and relative strength against are one price move), so the risk ladder counts
    # families, not signals. Basis: the spec's "multiple independent pieces of evidence".
    families: dict = field(default_factory=lambda: {
        "PRICE": ("OWN_PREMIUM_FALLING", "OWN_ACCELERATION_NEGATIVE"),
        "RELATIVE": ("OPPOSITE_PREMIUM_RISING", "RELATIVE_STRENGTH_AGAINST"),
        "FLOW": ("OWN_VOLUME_WEAKENING", "OPPOSITE_VOLUME_ACCELERATING"),
        "POSITIONING": ("OWN_OI_PRICE_ADVERSE",),
        "LIQUIDITY": ("OWN_BID_WEAKENING", "OWN_SPREAD_EXPANDING"),
        "VOLATILITY": ("IV_COLLAPSE_WITH_WEAK_PREMIUM", "STRADDLE_CONTRADICTS"),
    })
    core_families: tuple = ("PRICE", "RELATIVE")   # a warning needs at least one of these
    elevated_min_families: int = 1       # one core family negative -> ELEVATED / CAUTION
    high_min_families: int = 3           # >= 3 families incl. a core family -> HIGH / PREPARE_EXIT
    extreme_min_families: int = 4        # >= 4 families incl. BOTH core families -> EXTREME / BREAK_EXIT
    strong_min_positive: int = 3

    # ---- implied spot (research indicator only) -----------------------------------------------
    risk_free_rate: float = 0.065        # basis: approximate Indian short rate; effect over <= 1 week is < 0.1 pt per 1000
    implied_min_strikes: int = 5
    implied_max_iqr_pct: float = 0.05    # IQR of estimates > 0.05 % of spot -> LOW confidence
    implied_max_spread_pct: float = 5.0  # legs with wider quotes are excluded from parity

    def config_hash(self) -> str:
        blob = json.dumps({"version": VERSION, "config": asdict(self)}, sort_keys=True, default=str).encode()
        return hashlib.sha256(blob).hexdigest()[:16]

    def to_json(self) -> dict:
        return {"version": VERSION, "config_hash": self.config_hash(), "parameters": asdict(self),
                "note": "All thresholds are RESEARCH DEFAULTS, advisory only, not validated rules."}


DEFAULT = RiskConfig()
