"""Every 12D threshold in one place.

READ THIS BEFORE USING ANY NUMBER HERE. These are PROVISIONAL measurement boundaries, not
findings. They exist because a UI needs a word to print, not because any of them has been shown
to be optimal. Nothing in 12D was fitted to outcomes -- that is the whole point of the milestone:
first measure, then decide whether anything should change.

Changing any value changes the config hash, which is stamped on every row of the dataset, so an
analysis run can always be traced back to the boundaries that produced it.
"""

import hashlib
import json
from dataclasses import asdict, dataclass, field

from signal_learning_12d import VERSION

# ---------------------------------------------------------------- vocabularies
EARLY, GOOD, LATE, EXHAUSTED = "EARLY", "GOOD", "LATE", "EXHAUSTED"
UNKNOWN, INSUFFICIENT = "UNKNOWN", "INSUFFICIENT_DATA"
ENTRY_TIMING = (EARLY, GOOD, LATE, EXHAUSTED, UNKNOWN, INSUFFICIENT)

ACCELERATING, RISING, PERSISTENT = "ACCELERATING", "RISING", "PERSISTENT"
DECELERATING, FALLING, FLAT, REVERSING = "DECELERATING", "FALLING", "FLAT", "REVERSING"
MOMENTUM_STATES = (ACCELERATING, RISING, PERSISTENT, DECELERATING, FALLING, FLAT, REVERSING, INSUFFICIENT)

ACTIVE, EXTENDING, SLOWING, EXHAUSTING, REV = "ACTIVE", "EXTENDING", "SLOWING", "EXHAUSTING", "REVERSING"
EXHAUSTION_STATES = (ACTIVE, EXTENDING, SLOWING, EXHAUSTING, REV, UNKNOWN)

HOLD, CAUTION, PREPARE_EXIT, EXIT = "HOLD", "CAUTION", "PREPARE_EXIT", "EXIT"
POSITION_STATES = (HOLD, CAUTION, PREPARE_EXIT, EXIT, UNKNOWN)

# exit reasons are kept in separate categories on purpose (spec 13): a stop breach and a
# directional contradiction are different events and must never be counted together.
STOP_LOSS, POSITION_SIGNAL, DATA_RISK = "STOP_LOSS", "POSITION_SIGNAL", "DATA_RISK"
SESSION_END, SIGNAL_FLIP, STILL_OPEN = "SESSION_END", "SIGNAL_FLIP", "STILL_OPEN"
EXIT_REASONS = (STOP_LOSS, POSITION_SIGNAL, DATA_RISK, SESSION_END, SIGNAL_FLIP, STILL_OPEN, UNKNOWN)

STRONG_WIN, WIN, SMALL_WIN = "STRONG_WIN", "WIN", "SMALL_WIN"
FLAT_OUT, SMALL_LOSS, LOSS, STRONG_LOSS = "FLAT", "SMALL_LOSS", "LOSS", "STRONG_LOSS"
OUTCOME_LABELS = (STRONG_WIN, WIN, SMALL_WIN, FLAT_OUT, SMALL_LOSS, LOSS, STRONG_LOSS)

LIFECYCLE_LABELS = (
    "GOOD_ENTRY_GOOD_FOLLOW_THROUGH",
    "GOOD_DIRECTION_LATE_ENTRY",
    "GOOD_DIRECTION_BAD_EXIT",
    "INITIAL_ADVERSE_THEN_RECOVERED",
    "IMMEDIATE_FALSE_SIGNAL",
    "MOMENTUM_EXHAUSTION_ENTRY",
    "CHOPPY_SIGNAL",
    "INCONCLUSIVE",
)

HORIZONS = (1, 3, 5, 10)


@dataclass(frozen=True)
class LearningConfig:
    # ---- momentum classification (provisional boundaries on the 12C premium series) --------
    flat_pct: float = 0.5
    """|3-minute premium change| below this is described as flat rather than directional."""
    accel_ratio: float = 1.25
    """1-minute change vs the average of the previous minutes: above = accelerating, below its
    reciprocal = decelerating. A ratio, not a magnitude, so it is scale-free across contracts."""
    persistence_window: int = 3
    persistence_min: int = 2

    # ---- move extension / exhaustion --------------------------------------------------------
    extension_pct: float = 4.0
    """5-minute premium extension beyond which the move is described as extended. Provisional."""
    strong_extension_pct: float = 8.0

    # ---- entry timing -------------------------------------------------------------------------
    early_move_pct: float = 1.0
    """If the premium has barely moved yet, the signal is described as EARLY rather than GOOD.
    Neither is a judgement of quality -- only of where in the move the signal landed."""
    late_move_pct: float = 4.0

    # ---- position management (12D's OWN manager -- 12C's brake is untouched) ------------------
    caution_min_families: int = 1
    prepare_exit_min_families: int = 2
    exit_min_families: int = 3
    """Independent adverse-evidence families required at each step."""
    exit_confirm_minutes: int = 2
    """Consecutive minutes at PREPARE_EXIT strength before a signal exit is taken. This is the
    parameter the milestone exists to learn; 2 is a starting value, NOT a finding."""
    caution_confirm_minutes: int = 1
    recover_minutes: int = 2
    """Consecutive clean minutes that step the state back down towards HOLD."""

    # ---- outcome labelling (percentage of entry price) ------------------------------------------
    strong_pct: float = 10.0
    win_pct: float = 3.0
    small_pct: float = 0.5

    # ---- analysis ---------------------------------------------------------------------------------
    min_sample: int = 20
    """Below this a group is reported as INSUFFICIENT SAMPLE and no average is interpreted."""

    horizons: tuple = field(default_factory=lambda: HORIZONS)

    def config_hash(self) -> str:
        blob = json.dumps({"version": VERSION, "config": asdict(self)}, sort_keys=True, default=str).encode()
        return hashlib.sha256(blob).hexdigest()[:16]

    def to_json(self) -> dict:
        return {"version": VERSION, "config_hash": self.config_hash(), "parameters": asdict(self),
                "note": "PROVISIONAL measurement boundaries. Not fitted to outcomes, not validated."}


DEFAULT = LearningConfig()
