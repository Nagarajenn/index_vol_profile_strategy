"""Every live-trading limit in one place.

The values in CAPS_* are the trader's stated risk decisions (2026-09-23) and are deliberately
NOT read from the environment or a config file: changing one is a code change that must fail
tests/test_live_trading_guards.py. This mirrors paper_trading/safety.py's structural posture.
"""

import hashlib
import json
from dataclasses import asdict, dataclass, field

from live_trading import VERSION

# ---------------------------------------------------------------- trader's risk decisions
MAX_ENTRIES_PER_DAY = 2           # "1 or 2 trades per day"
LOTS_PER_ENTRY = 1                # exactly one lot; quantity is quantised to the lot
HALT_AFTER_FIRST_LOSS = True      # a losing trade ends the session
MAX_ENTRY_COST_RS = 9000.0        # per-entry ceiling; NIFTY's 65-lot needs > Rs 6,000
STARTING_CAPITAL_RS = 10000.0

# Mon/Tue NIFTY, Wed/Thu SENSEX, Fri either. Monday is weekday 0.
SYMBOL_BY_WEEKDAY = {0: ("NIFTY",), 1: ("NIFTY",), 2: ("SENSEX",), 3: ("SENSEX",),
                     4: ("NIFTY", "SENSEX")}


@dataclass(frozen=True)
class LiveConfig:
    # ---- entry qualifiers (which two of the day's many BUY episodes get the slots) --------
    min_confirmation: str = "STRONG"      # 12C grades BUY as WEAK/MODERATE/STRONG
    min_episode_minutes: int = 2          # entry on the 2nd consecutive minute; a flicker cannot fire
    entry_window_start: str = "09:45"     # the opening 30 minutes are excluded
    entry_window_end: str = "14:45"       # well clear of the ~15:15 underlying freeze

    # ---- the one agent-initiated exit ----------------------------------------------------
    force_flat_at: str = "15:10"          # no live position survives the session

    # ---- execution ------------------------------------------------------------------------
    order_type: str = "LIMIT"             # never MARKET: a spread blowout must fail, not fill
    ticks_through: int = 2                # limit = ask + 2 ticks
    fill_timeout_sec: int = 45            # unfilled after this -> cancel and journal NOT_FILLED
    product_type: str = "INTRADAY"

    # ---- refusal thresholds ----------------------------------------------------------------
    max_spread_pct: float = 3.0           # same ceiling 12C/11D use for an unusable quote
    max_snapshot_age_min: int = 2         # stale data must never become an order

    def config_hash(self) -> str:
        blob = json.dumps({"version": VERSION, "config": asdict(self),
                           "caps": dict(max_entries=MAX_ENTRIES_PER_DAY, lots=LOTS_PER_ENTRY,
                                        halt_after_loss=HALT_AFTER_FIRST_LOSS,
                                        max_cost=MAX_ENTRY_COST_RS, capital=STARTING_CAPITAL_RS)},
                          sort_keys=True, default=str).encode()
        return hashlib.sha256(blob).hexdigest()[:16]


DEFAULT = LiveConfig()

# ---------------------------------------------------------------- the safety switch
DRY_RUN_DEFAULT = True
"""No order leaves this machine unless the operator explicitly passes --live.
The default is True in source so that an accidental run cannot place an order."""
