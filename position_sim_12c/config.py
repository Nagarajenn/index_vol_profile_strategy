"""Simulation parameters. Nothing here changes a signal; these only shape the view."""

import hashlib
import json
from dataclasses import asdict, dataclass

from position_sim_12c import VERSION


@dataclass(frozen=True)
class SimConfig:
    # ---- stop loss (ADVISORY: displayed and used for the risk state, never an order) ----
    stop_loss_pct: float = 10.0          # long option: stop = entry * (1 - pct/100)
    # Entry timing. False = the ASK of the signal minute itself (the specified convention, and the
    # optimistic one: the panel only shows a minute's decision ~15-30 s after that minute closes).
    # True = the ASK of the next minute, which is the earliest quote a human could actually have hit.
    entry_at_next_minute: bool = False
    close_on_stop_breach: bool = False   # False = keep showing the position after a breach

    # ---- risk state ----------------------------------------------------------------------
    # fraction of the entry->stop buffer still left; below these the position is "near" its stop
    buffer_elevated: float = 0.50
    buffer_high: float = 0.20
    families_elevated: int = 2           # independent 12C evidence families against the position
    families_high: int = 3

    # ---- data quality ---------------------------------------------------------------------
    stale_after_minutes: int = 2         # option snapshot older than this -> STALE

    def config_hash(self) -> str:
        return hashlib.sha256(json.dumps({"v": VERSION, "c": asdict(self)}, sort_keys=True).encode()).hexdigest()[:16]

    def to_json(self) -> dict:
        return {"version": VERSION, "config_hash": self.config_hash(), "parameters": asdict(self)}


DEFAULT = SimConfig()
