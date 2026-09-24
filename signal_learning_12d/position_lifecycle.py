"""The architectural correction: position management that is INDEPENDENT of the entry decision.

The existing simulator closes a hypothetical position the minute the entry engine says WAIT.
That conflates two questions. WAIT means "I would not open a position right now" -- it does not
mean "get out of the one you have". A scalp that is working will routinely sit through minutes
where no fresh entry is warranted.

This manager never reads the entry decision to decide whether to stay in. It reads only evidence
about the position itself, and it separates three kinds of exit that the current pipeline mixes:

    STOP_LOSS        a hard risk condition. Immediate, no confirmation, no debate.
    DATA_RISK        the position can no longer be evaluated or priced. Immediate.
    POSITION_SIGNAL  directional contradiction. Requires confirmation across minutes.

The one thing the entry engine still does is flip the side: a BUY on the opposite side is a new
signal, and closing the old position is the simulator's existing SIGNAL_FLIP, kept as its own
category rather than folded into POSITION_SIGNAL.

12C's brake is consumed READ-ONLY for its per-minute family count. Nothing in scalp_decision_12c
is modified; what 12D adds is the state machine and the confirmation across minutes that the
brake, being a single-minute reading, cannot express.
"""

from dataclasses import dataclass, field

from scalp_decision_12c import brake as BRAKE
from scalp_decision_12c.config import DEFAULT as DECISION_CFG
from signal_learning_12d.config import (CAUTION, DATA_RISK, DEFAULT, EXIT, HOLD, POSITION_SIGNAL,
                                        PREPARE_EXIT, STOP_LOSS, UNKNOWN)

LADDER = (HOLD, CAUTION, PREPARE_EXIT, EXIT)


@dataclass
class PositionManager:
    """A per-position state machine. One instance follows one hypothetical position."""
    side: str
    strike: float | None
    entry_price: float | None
    stop_price: float | None
    cfg: object = field(default=DEFAULT)
    state: str = HOLD
    adverse_streak: int = 0
    clean_streak: int = 0
    exit_reason: str | None = None
    exit_minute: str | None = None
    path: list = field(default_factory=list)
    """Every state this position passed through, so the exit can be read as a sequence."""

    # ------------------------------------------------------------------ helpers
    def _record(self, minute: str, state: str, why: str, families: list) -> dict:
        step = dict(minute=minute, state=state, reason=why, families_against=list(families),
                    adverse_streak=self.adverse_streak)
        self.path.append(step)
        return step

    @staticmethod
    def _strength(n_families: int, cfg) -> str:
        """Per-minute severity from independent adverse families. No time element here --
        that is the state machine's job."""
        if n_families >= cfg.exit_min_families:
            return PREPARE_EXIT      # never EXIT on one minute: EXIT requires confirmation
        if n_families >= cfg.prepare_exit_min_families:
            return PREPARE_EXIT
        if n_families >= cfg.caution_min_families:
            return CAUTION
        return HOLD

    # ------------------------------------------------------------------ the step
    def step(self, minute: str, evidence: dict | None, quote: dict | None, entry_decision: str | None = None) -> dict:
        """Advance one minute.

        `entry_decision` is accepted ONLY so the caller can record it alongside the position
        state for later comparison. It is deliberately never read here -- that is the whole
        point of this module. The one exception, an opposite-side BUY, is handled by the
        replay driver as SIGNAL_FLIP, not by this manager."""
        if self.state == EXIT:
            return self._record(minute, EXIT, "already exited", [])

        bid = (quote or {}).get("bid")
        usable = quote is not None and quote.get("status") == "OK" and bid is not None

        # -- 1. hard risk: a stop breach is not a matter of evidence -------------------------
        if usable and self.stop_price is not None and bid <= self.stop_price:
            self.state, self.exit_reason, self.exit_minute = EXIT, STOP_LOSS, minute
            return self._record(minute, EXIT, f"stop breached: bid {bid} at or below stop {self.stop_price}", [])

        # -- 2. hard risk: the position can no longer be priced or evaluated -------------------
        if not usable:
            self.adverse_streak += 1
            if self.adverse_streak >= self.cfg.exit_confirm_minutes:
                self.state, self.exit_reason, self.exit_minute = EXIT, DATA_RISK, minute
                return self._record(minute, EXIT, "no usable two-sided quote for consecutive minutes", [])
            self.state = CAUTION if self.state == HOLD else self.state
            return self._record(minute, self.state, "no usable quote this minute", [])

        if evidence is None:
            return self._record(minute, self.state if self.state != HOLD else UNKNOWN,
                                "no evidence available this minute", [])

        # -- 3. directional evidence, graded by INDEPENDENT families ----------------------------
        reading = BRAKE.assess(evidence, dict(option_type=self.side, strike=self.strike), DECISION_CFG)
        fams = reading["families_against"]
        minute_state = self._strength(len(fams), self.cfg)

        if minute_state == HOLD:
            self.clean_streak += 1
            self.adverse_streak = 0
            if self.clean_streak >= self.cfg.recover_minutes and self.state != HOLD:
                # evidence has cleared: step back down rather than staying permanently elevated
                self.state = LADDER[max(LADDER.index(self.state) - 1, 0)]
                return self._record(minute, self.state, f"{self.clean_streak} clean minutes; easing", fams)
            return self._record(minute, self.state, reading["summary"], fams)

        self.clean_streak = 0
        self.adverse_streak += 1

        if minute_state == CAUTION:
            self.state = CAUTION if self.state == HOLD else self.state
            return self._record(minute, self.state, reading["summary"], fams)

        # PREPARE_EXIT strength: escalate, and only EXIT once it has been confirmed across minutes
        if self.state in (HOLD, CAUTION):
            self.state = PREPARE_EXIT
            return self._record(minute, PREPARE_EXIT, reading["summary"], fams)
        if self.adverse_streak >= self.cfg.exit_confirm_minutes and reading.get("thesis_broken"):
            self.state, self.exit_reason, self.exit_minute = EXIT, POSITION_SIGNAL, minute
            return self._record(minute, EXIT,
                                f"{self.adverse_streak} consecutive adverse minutes and the premium trend has broken; "
                                f"{reading['summary']}", fams)
        return self._record(minute, PREPARE_EXIT, reading["summary"], fams)

    # ------------------------------------------------------------------ summary
    def summary(self) -> dict:
        states = [p["state"] for p in self.path]
        return dict(final_state=self.state, exit_reason=self.exit_reason, exit_minute=self.exit_minute,
                    path="->".join(_compress(states)), minutes_observed=len(self.path),
                    minutes_in_caution=states.count(CAUTION), minutes_in_prepare_exit=states.count(PREPARE_EXIT),
                    max_state=max(states, key=lambda s: LADDER.index(s) if s in LADDER else -1) if states else UNKNOWN)


def _compress(states: list) -> list:
    """HOLD HOLD CAUTION CAUTION HOLD -> HOLD CAUTION HOLD. The shape of the path is what matters."""
    out = []
    for s in states:
        if not out or out[-1] != s:
            out.append(s)
    return out
