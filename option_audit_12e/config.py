"""12E measurement bands. All PROVISIONAL and configurable; none is fitted to outcomes.

12E is a diagnosis milestone: these boundaries exist so results can be grouped and counted,
not because any of them has been shown to be right. Changing one changes the config hash
stamped on every diagnostic row.
"""

import hashlib
import json
from dataclasses import asdict, dataclass, field

from option_audit_12e import VERSION

HORIZONS = (1, 3, 5, 10)
PRE_HORIZONS = (1, 3, 5)

# ---------------------------------------------------------------- vocabularies
TRENDING_UP, TRENDING_DOWN, RANGE, REVERSING, UNKNOWN = \
    "TRENDING_UP", "TRENDING_DOWN", "RANGE", "REVERSING", "UNKNOWN"
MARKET_STATES = (TRENDING_UP, TRENDING_DOWN, RANGE, REVERSING, UNKNOWN)

IV_HEADWIND, IV_TAILWIND, IV_NEUTRAL, IV_UNKNOWN = \
    "IV_HEADWIND", "IV_TAILWIND", "IV_NEUTRAL", "IV_UNKNOWN"

ATM, NEAR_ATM, MOD_OTM, FAR_OTM, ITM = "ATM", "NEAR_ATM", "MODERATELY_OTM", "FAR_OTM", "ITM"

LOSS_REASONS = (
    "UNDERLYING_DID_NOT_CONTINUE",
    "LATE_ENTRY",
    "WEAK_OPTION_RESPONSE",
    "IV_HEADWIND",
    "SPREAD_FRICTION",
    "STRIKE_DISTANCE",
    "MOMENTUM_REVERSAL",
    "SIGNAL_FLIP",
    "STOP_LOSS",
    "DATA_ISSUE",
    "MIXED",
    "UNKNOWN",
)

# The four categories that replace the old single "direction_correct" flag (spec 14).
A_UND_OK_OPT_OK = "UNDERLYING_CORRECT_OPTION_PROFITABLE"
B_UND_OK_OPT_BAD = "UNDERLYING_CORRECT_OPTION_LOSS"
C_UND_BAD_OPT_OK = "UNDERLYING_WRONG_OPTION_PROFITABLE"
D_UND_BAD_OPT_BAD = "UNDERLYING_WRONG_OPTION_LOSS"
QUADRANTS = (A_UND_OK_OPT_OK, B_UND_OK_OPT_BAD, C_UND_BAD_OPT_OK, D_UND_BAD_OPT_BAD)


@dataclass(frozen=True)
class AuditConfig:
    # ---- underlying direction -------------------------------------------------------------
    und_flat_pct: float = 0.02
    """|underlying % move| below this is treated as no move rather than a direction. Roughly a
    one-minute noise band on an index; deliberately small so 'did not continue' is not
    manufactured out of noise."""

    # ---- market state at the signal minute (causal) -----------------------------------------
    trend_lookback_min: int = 10
    trend_pct: float = 0.10
    """|move over the lookback| above which the underlying is described as trending."""
    range_pct: float = 0.05
    reversal_ratio: float = 0.5
    """Last 3 minutes retracing at least this fraction of the lookback move = REVERSING."""

    # ---- option response ----------------------------------------------------------------------
    min_und_move_for_ratio: float = 0.05
    """A response ratio is only computed when the underlying actually moved this much. Dividing
    an option's move by a 0.01% wobble produces a number, not a measurement."""

    weak_response_efficiency: float = 0.5
    strong_response_efficiency: float = 1.2
    """RESPONSE_EFFICIENCY = measured elasticity / first-order theoretical elasticity.

    The raw ratio |option %| / |underlying %| is an ELASTICITY, and for an ATM option it is
    normally 10-30x simply because the premium is a small number -- so the raw ratio on its own
    says almost nothing about whether the option responded properly. What matters is the measured
    elasticity against what delta says to expect: (|delta| x spot / premium). 1.0 means the
    premium moved as first-order theory predicts; below 0.5 it materially under-responded."""

    # ---- IV --------------------------------------------------------------------------------------
    iv_move_pct: float = 1.0
    """|IV % change| below this is IV_NEUTRAL."""

    # ---- strike distance bands (as % of spot) -------------------------------------------------------
    atm_band_pct: float = 0.10
    near_band_pct: float = 0.35
    moderate_band_pct: float = 1.00

    # ---- delta buckets ----------------------------------------------------------------------------------
    delta_buckets: tuple = ((0.0, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 1.0))

    # ---- attribution ---------------------------------------------------------------------------------------
    spread_dominant_share: float = 0.6
    """If the round-trip spread accounts for at least this share of the loss, SPREAD_FRICTION."""
    late_entry_pre_move_share: float = 0.6
    """If the move in the 5 minutes BEFORE the signal is at least this share of the total move
    around the signal, the entry is described as late."""

    # ---- analysis -------------------------------------------------------------------------------------------
    min_sample: int = 20
    horizons: tuple = field(default_factory=lambda: HORIZONS)
    pre_horizons: tuple = field(default_factory=lambda: PRE_HORIZONS)

    def config_hash(self) -> str:
        blob = json.dumps({"version": VERSION, "config": asdict(self)}, sort_keys=True, default=str).encode()
        return hashlib.sha256(blob).hexdigest()[:16]

    def to_json(self) -> dict:
        return {"version": VERSION, "config_hash": self.config_hash(), "parameters": asdict(self),
                "note": "PROVISIONAL measurement bands for diagnosis. Not fitted, not validated, not rules."}


DEFAULT = AuditConfig()
