"""13B thresholds. PROVISIONAL and configurable; none was fitted to P&L.

The spec is explicit that 13B must not be tuned to make the report look better, so these are
chosen from the instrument's own scale (a swing needs to be bigger than one minute of noise)
and then left alone.
"""

import hashlib
import json
from dataclasses import asdict, dataclass

from price_action_13b import VERSION

# ---------------------------------------------------------------- vocabularies
TRENDING_UP, TRENDING_DOWN, RANGE = "TRENDING_UP", "TRENDING_DOWN", "RANGE"
BREAKOUT_UP, BREAKDOWN = "BREAKOUT_UP", "BREAKDOWN"
REVERSING_UP, REVERSING_DOWN, MIXED = "REVERSING_UP", "REVERSING_DOWN", "MIXED"
INSUFFICIENT = "INSUFFICIENT_DATA"
STRUCTURES = (TRENDING_UP, TRENDING_DOWN, RANGE, BREAKOUT_UP, BREAKDOWN,
              REVERSING_UP, REVERSING_DOWN, MIXED, INSUFFICIENT)

CLEAN_BREAK, CLEAN_BREAK_FT = "CLEAN_BREAK", "CLEAN_BREAK_WITH_FOLLOW_THROUGH"
FAILED_BREAK, EXHAUSTED_BREAK, NO_BREAK = "FAILED_BREAK", "EXHAUSTED_BREAK", "NO_BREAK"
BREAKS = (CLEAN_BREAK, CLEAN_BREAK_FT, FAILED_BREAK, EXHAUSTED_BREAK, NO_BREAK, INSUFFICIENT)

BREAKOUT_CONTINUATION, PULLBACK_IN_TREND = "BREAKOUT_CONTINUATION", "PULLBACK_IN_TREND"
REVERSAL, RANGE_ROTATION, EXTENDED_MOVE = "REVERSAL", "RANGE_ROTATION", "EXTENDED_MOVE"
NO_CLEAR_SETUP = "NO_CLEAR_SETUP"
SETUPS = (BREAKOUT_CONTINUATION, PULLBACK_IN_TREND, REVERSAL, RANGE_ROTATION,
          EXTENDED_MOVE, NO_CLEAR_SETUP)

ABOVE_VWAP, BELOW_VWAP, CROSSING_VWAP = "ABOVE_VWAP", "BELOW_VWAP", "CROSSING_VWAP"
REJECTED_VWAP, DISTANT_FROM_VWAP, UNKNOWN = "REJECTED_VWAP", "DISTANT_FROM_VWAP", "UNKNOWN"
VWAP_STATES = (ABOVE_VWAP, BELOW_VWAP, CROSSING_VWAP, REJECTED_VWAP, DISTANT_FROM_VWAP, UNKNOWN)

VOLUME_EXPANDING, VOLUME_NORMAL = "VOLUME_EXPANDING", "VOLUME_NORMAL"
VOLUME_DECLINING, VOLUME_SPIKE = "VOLUME_DECLINING", "VOLUME_SPIKE"
VOLUME_STATES = (VOLUME_EXPANDING, VOLUME_NORMAL, VOLUME_DECLINING, VOLUME_SPIKE, UNKNOWN)

CONFIRMED, PARTIAL, CONTRADICTED, NO_SETUP = "CONFIRMED", "PARTIAL", "CONTRADICTED", "NO_SETUP"
CONFIRMATIONS = (CONFIRMED, PARTIAL, CONTRADICTED, NO_SETUP, UNKNOWN)


@dataclass(frozen=True)
class PriceActionConfig:
    # ---- swings -----------------------------------------------------------------------------
    swing_k: int = 2
    """Fractal pivot width: a swing high needs k bars lower on each side. Same convention the
    project's own analytics/swings.py uses."""
    structure_window: int = 20
    """Bars of completed history the structure read looks back over."""
    min_swing_pct: float = 0.03
    """A swing smaller than this is noise, not structure."""

    # ---- breaks -------------------------------------------------------------------------------
    break_buffer_pct: float = 0.01
    """Price must clear the level by this much before it counts as a break at all."""
    follow_through_bars: int = 2
    """Completed bars after the break that must hold beyond the level."""
    wick_body_ratio: float = 2.0
    """A bar whose wick beyond the level is this many times its body is a wick, not a break."""
    extension_atr_mult: float = 2.5
    """Distance from the broken level, in ATR, beyond which the break is described as exhausted."""
    atr_period: int = 14

    # ---- VWAP ----------------------------------------------------------------------------------
    vwap_near_pct: float = 0.05
    """Within this of VWAP counts as CROSSING rather than clearly above or below."""
    vwap_distant_pct: float = 0.40

    # ---- volume ---------------------------------------------------------------------------------
    volume_window: int = 10
    volume_expanding_ratio: float = 1.20
    volume_spike_ratio: float = 2.00
    volume_declining_ratio: float = 0.80

    # ---- volume profile ----------------------------------------------------------------------------
    value_edge_pct: float = 0.03
    """How far beyond VAH/VAL counts as acceptance outside value."""

    # ---- integration (spec 9) -------------------------------------------------------------------------
    block_on_partial: bool = True
    block_on_contradicted: bool = True
    block_on_no_setup: bool = True
    preserve_on_unknown: bool = True
    """UNKNOWN preserves the 13A decision and marks it, rather than silently blocking."""
    enabled: bool = True

    def config_hash(self) -> str:
        blob = json.dumps({"version": VERSION, "config": asdict(self)}, sort_keys=True, default=str).encode()
        return hashlib.sha256(blob).hexdigest()[:16]

    def to_json(self) -> dict:
        return {"version": VERSION, "config_hash": self.config_hash(), "parameters": asdict(self),
                "note": ("PROVISIONAL price-action boundaries chosen from the instrument's own scale. "
                         "Not fitted to P&L, per the milestone's explicit constraint.")}


DEFAULT = PriceActionConfig()


# ---------------------------------------------------------------- the PARTIAL experiment
EXPERIMENT_VERSION = "13B-price-action-v1-exp-allow-partial"

EXPERIMENT_ALLOW_PARTIAL = PriceActionConfig(block_on_partial=False)
"""13B-EXP-1. The ONLY difference from DEFAULT is that a PARTIAL price-action read no longer
blocks the 13A buy; CONTRADICTED and NO_SETUP still do.

Motivated by the committed 45-session replay, where PARTIAL blocks (31 of 56) had a mean
forward outcome of +1.89/unit and 45.2% moved favourably, while CONTRADICTED (-7.86/unit) and
NO_SETUP (-4.74/unit) were genuinely discriminating.

Kept as a SEPARATE config object rather than a changed default, so the baseline it is being
measured against cannot drift underneath it. Every other threshold is identical -- the two
configs differ in exactly one boolean, which `tests/test_partial_experiment_13b.py` asserts."""
