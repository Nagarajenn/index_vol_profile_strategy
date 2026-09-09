"""Frozen configuration for the paper-trading experiment.

Every value here is a DOCUMENTED STARTING DEFAULT, not a tuned or
validated parameter. Milestones 11A-11C found no validated directional
edge and no validated option-expression rule; these thresholds exist to
make the agent's behaviour explicit and auditable, not because any of
them is known to be profitable.

The five-session experiment runs against ONE frozen config. Any change
to a value here must bump CONFIG_VERSION, which changes CONFIG_HASH,
which is stamped onto every decision -- so results computed under
different settings can never be silently pooled.
"""

import hashlib
import json
from dataclasses import asdict, dataclass, field

STRATEGY_VERSION = "11d-paper-v1"
DECISION_VERSION = "decision-v1"
CONFIG_VERSION = "config-v1"


@dataclass(frozen=True)
class PaperConfig:
    # ---- account ----------------------------------------------------
    starting_capital: float = 15_000.0
    max_capital_per_trade: float = 6_000.0
    """Premium-at-risk cap per trade. Deliberately NOT the full account:
    one 19-minute long-option position should never be able to put the
    whole experiment at risk."""
    max_daily_loss: float = 2_250.0          # 15% of starting capital
    max_account_drawdown: float = 4_500.0    # 30% of starting capital
    max_trades_per_day: int = 2              # across both symbols
    max_trades_per_symbol_per_day: int = 1
    max_concurrent_positions: int = 1

    # ---- timing (IST) ------------------------------------------------
    decision_time: str = "14:59:00"
    min_holding_minutes: int = 1
    max_holding_minutes: int = 19            # HARD safety rule, force-exit

    # ---- option candidate universe -----------------------------------
    atm_window_strikes: int = 5              # ATM +/- 5
    max_spread_pct: float = 3.0              # reject wider quotes outright
    min_option_delta: float = 0.15           # below this the option barely tracks the move
    max_option_premium: float = 600.0        # keeps one lot inside max_capital_per_trade
    max_snapshot_age_sec: int = 180          # reuses 11A's staleness discipline

    # ---- directional evidence gates ----------------------------------
    min_confidence: int = 45                 # 0-100 paper-agent confidence
    min_expected_move_atr: float = 0.30      # expected move must clear 0.30 x ATR(14)
    max_conflicting_factors: int = 2         # more than this => CONFLICTED => NO TRADE
    min_supporting_factors: int = 2

    # ---- dynamic SL / target -----------------------------------------
    min_stop_distance_atr: float = 0.15      # SL must sit beyond normal noise
    max_stop_distance_atr: float = 0.80
    min_reward_risk: float = 1.2             # below this the trade is not worth taking
    min_stop_pct_of_premium: float = 8.0     # SL_TOO_TIGHT below this
    max_stop_pct_of_premium: float = 35.0    # cap catastrophic single-trade loss
    stop_spread_multiple: float = 2.0        # SL must clear 2x the round-trip spread

    # ---- post-entry management ---------------------------------------
    momentum_failure_minutes: int = 3        # consecutive adverse underlying minutes
    reversal_atr_multiple: float = 0.50      # adverse underlying move that voids the thesis
    exit_spread_pct_limit: float = 6.0       # quote deterioration => liquidity exit
    trail_activate_reward_ratio: float = 0.75  # tighten only after 75% of target is captured
    trail_lock_fraction: float = 0.50        # then lock 50% of the captured gain

    symbols: tuple[str, ...] = ("NIFTY", "SENSEX")

    def config_hash(self) -> str:
        """Stable hash of the whole config + versions, stamped onto every
        decision so a mid-experiment change is impossible to hide."""
        payload = {
            "strategy_version": STRATEGY_VERSION,
            "decision_version": DECISION_VERSION,
            "config_version": CONFIG_VERSION,
            "config": asdict(self),
        }
        blob = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
        return hashlib.sha256(blob).hexdigest()[:16]


DEFAULT_CONFIG = PaperConfig()
