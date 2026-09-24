"""The SignalEvent: a 12C signal promoted to a first-class object with an identity and an age.

A 12C BUY is a STATE, not a trade instruction -- it can hold for one minute or twenty. The unit
that matters for learning is therefore the EPISODE: one unbroken run of the same side. A single
episode produces exactly one SignalEvent, whose `signal_minute` is the minute the state began.

Signal age and hold time are related but different, and are kept apart on purpose:

    signal_age   minutes since the signal state began
    hold_time    minutes since the hypothetical entry

They coincide only when the entry happens on the signal minute itself.
"""

import hashlib
from dataclasses import asdict, dataclass, field

from signal_learning_12d import VERSION


@dataclass
class SignalEvent:
    signal_id: str
    market: str
    session_date: str
    signal_minute: str
    direction: str                 # BUY_CE / BUY_PE
    side: str                      # CE / PE
    strike: float | None
    expiry: str | None
    contract: str
    confidence: str | None         # 12C's confirmation: STRONG / MODERATE / WEAK
    reason: str
    episode_minutes: int = 0       # how long the state ultimately held (filled as the episode runs)
    entry_features: dict = field(default_factory=dict)
    entry_quality: dict = field(default_factory=dict)
    version: str = VERSION

    def age_at(self, minute: str) -> int:
        """Minutes since the signal state began."""
        return _idx(minute) - _idx(self.signal_minute)

    def to_dict(self) -> dict:
        return asdict(self)


def _idx(minute: str) -> int:
    h, m = (int(x) for x in minute.split(":"))
    return h * 60 + m


def signal_id(symbol: str, session_date, minute: str, direction: str) -> str:
    """Stable and content-free: the same signal always gets the same id, so a re-run updates
    rather than duplicating."""
    raw = f"{symbol}|{session_date}|{minute}|{direction}"
    return f"{symbol[:3]}-{session_date}-{minute.replace(':', '')}-{hashlib.sha1(raw.encode()).hexdigest()[:6]}"


def episodes(decisions: list) -> list[dict]:
    """Split a minute-by-minute decision stream into BUY episodes.

    `decisions` is [{minute, decision, confirmation, reason, atm, ...}, ...] ascending.
    Returns one entry per unbroken run of the same BUY side. WAIT minutes end an episode for
    SIGNAL purposes -- they say nothing about whether a POSITION should be held, which is
    position_lifecycle's job and no longer this one's."""
    out, run = [], []
    for row in decisions:
        d = row.get("decision")
        if d in ("BUY_CE", "BUY_PE"):
            if run and run[-1]["decision"] != d:
                out.append(_close(run))
                run = []
            run.append(row)
        elif run:
            out.append(_close(run))
            run = []
    if run:
        out.append(_close(run))
    return out


def _close(run: list) -> dict:
    first = run[0]
    return dict(minute=first["minute"], decision=first["decision"], confirmation=first.get("confirmation"),
                reason=first.get("reason", ""), atm=first.get("atm"), evidence=first.get("evidence"),
                episode_minutes=len(run), last_minute=run[-1]["minute"],
                confirmations=[r.get("confirmation") for r in run])
