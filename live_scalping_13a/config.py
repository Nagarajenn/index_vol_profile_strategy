"""Every 13A threshold and risk limit, in one place, as configuration.

Two separate kinds of number live here and they must not be confused:

  GATES      measurement boundaries for the decision (regime, timing, spread, economics).
             PROVISIONAL. None was optimised on outcomes; 12E's evidence motivates their
             DIRECTION, not their exact value.

  RISK       the trader's own limits. These are not research parameters. They are the
             answer to "how much am I willing to lose today", and they belong to the trader.

EXPERIMENT_CAPITAL is NOT the daily loss limit (spec 16). Allocated capital and maximum daily
loss are different quantities and are kept apart everywhere, including on screen.
"""

import hashlib
import json
from dataclasses import asdict, dataclass, field

from live_scalping_13a import VERSION

# ---------------------------------------------------------------- vocabularies
TRENDING_UP, TRENDING_DOWN, RANGE, REVERSING, UNKNOWN = \
    "TRENDING_UP", "TRENDING_DOWN", "RANGE", "REVERSING", "UNKNOWN"
REGIMES = (TRENDING_UP, TRENDING_DOWN, RANGE, REVERSING, UNKNOWN)

EARLY, NORMAL, EXTENDED = "EARLY", "NORMAL", "EXTENDED"
TIMINGS = (EARLY, NORMAL, EXTENDED, UNKNOWN)

IV_TAILWIND, IV_NEUTRAL, IV_HEADWIND = "IV_TAILWIND", "IV_NEUTRAL", "IV_HEADWIND"
IV_STATES = (IV_TAILWIND, IV_NEUTRAL, IV_HEADWIND, UNKNOWN)

A, B, C, NO_TRADE = "A", "B", "C", "NO_TRADE"
QUALITIES = (A, B, C, NO_TRADE)

BUY_CE, BUY_PE, WAIT = "BUY_CE", "BUY_PE", "WAIT"
ACTIVE, LOCKED = "ACTIVE", "LOCKED"

# Rejection reasons, ordered by how early the gate sits. The FIRST failure in this order is
# recorded as PRIMARY_REJECTION_REASON (spec 30), so a WAIT always names one cause.
REJECTIONS = (
    "RISK_LOCKED",
    "NO_BASE_SIGNAL",
    "POSITION_OPEN",
    "CRITICAL_DATA_MISSING",
    "REGIME_RANGE",
    "REGIME_REVERSING",
    "REGIME_AGAINST",
    "REGIME_UNKNOWN",
    "UNDERLYING_NOT_CONFIRMED",
    "OPTION_NOT_CONFIRMED",
    "TIMING_EXTENDED",
    "SPREAD_TOO_WIDE",
    "ECONOMICS_INSUFFICIENT",
    "QUALITY_TOO_LOW",
)


@dataclass(frozen=True)
class GateConfig:
    """PROVISIONAL decision gates. Configurable; not fitted to outcomes."""

    # ---- regime (spec 3) ------------------------------------------------------------------
    enable_range_filter: bool = True
    regime_lookback_min: int = 10
    regime_trend_pct: float = 0.10
    """|move over the lookback| above which the underlying is called trending. 0.10% of NIFTY
    is ~23 points over 10 minutes -- above the noise band, well below a real swing."""
    regime_range_pct: float = 0.05
    regime_reversal_ratio: float = 0.5
    enable_reversing_filter: bool = True

    # ---- underlying confirmation (spec 4) ---------------------------------------------------
    und_confirm_pct_3m: float = 0.04
    """3-minute underlying move required in the signal's direction."""
    und_confirm_pct_1m: float = 0.0
    """1-minute move must at least not oppose the direction."""

    # ---- option confirmation (spec 5) ---------------------------------------------------------
    option_min_categories: int = 3
    """Independent categories required of: relative strength, own momentum, participation,
    other-side weakness. No single indicator is sufficient."""

    # ---- entry timing (spec 6) ------------------------------------------------------------------
    timing_extended_opt_pre_5m: float = 6.0
    """Option premium already up this much in the 5 minutes BEFORE the signal = EXTENDED."""
    timing_extended_und_pre_5m: float = 0.25
    timing_early_opt_pre_3m: float = 0.5
    timing_extended_range_position: float = 92.0
    """Premium sitting this high in its own recent range, with momentum no longer accelerating."""
    enable_timing_filter: bool = True

    # ---- spread (spec 9) ---------------------------------------------------------------------------
    max_spread_pct_of_premium: float = 1.0
    """Relative, never a fixed rupee amount: a 0.50 spread is cheap on a 250 premium and
    ruinous on a 15 premium."""
    enable_spread_filter: bool = True

    # ---- expected move vs friction (spec 10) ----------------------------------------------------------
    min_expected_move_to_spread_ratio: float = 3.0
    """Expected first-order premium response over the round-trip spread. An ANALYTICAL estimate
    from delta and recent underlying movement -- not a prediction."""
    expected_move_lookback_min: int = 5
    enable_economics_filter: bool = True

    # ---- IV (spec 8) --------------------------------------------------------------------------------------
    iv_move_pct: float = 1.0
    iv_headwind_downgrades_quality: bool = True
    """An IV headwind never rejects on its own; it costs one quality grade."""

    # ---- quality (spec 11) -----------------------------------------------------------------------------------
    min_quality_to_buy: str = "B"
    """A and B may buy; C is surfaced but does not produce a BUY."""

    # ---- stop (spec 28) -----------------------------------------------------------------------------------------
    stop_loss_pct: float = 10.0

    def config_hash(self) -> str:
        blob = json.dumps({"version": VERSION, "gates": asdict(self)}, sort_keys=True, default=str).encode()
        return hashlib.sha256(blob).hexdigest()[:16]


@dataclass(frozen=True)
class RiskConfig:
    """The trader's limits. Not research parameters -- these are a risk appetite."""

    experiment_capital: float = 10000.0
    """Allocated experimental capital. NOT a loss limit (spec 16)."""
    max_daily_loss: float = 2000.0
    """Separate and much smaller than the capital. Realised losses drive the lockout."""
    max_loss_per_trade: float = 900.0
    max_consecutive_losses: int = 3
    max_trades_per_day: int = 6
    max_position_value: float = 9000.0

    def config_hash(self) -> str:
        blob = json.dumps({"version": VERSION, "risk": asdict(self)}, sort_keys=True, default=str).encode()
        return hashlib.sha256(blob).hexdigest()[:16]

    def to_display(self) -> dict:
        """The four numbers the UI must keep visually distinct (spec 16/22)."""
        return dict(allocated_capital=self.experiment_capital, max_daily_loss=self.max_daily_loss,
                    max_loss_per_trade=self.max_loss_per_trade,
                    max_consecutive_losses=self.max_consecutive_losses,
                    max_trades_per_day=self.max_trades_per_day,
                    max_position_value=self.max_position_value)


@dataclass(frozen=True)
class Config:
    gates: GateConfig = field(default_factory=GateConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    mode: str = "RESEARCH"

    def config_hash(self) -> str:
        blob = json.dumps({"version": VERSION, "gates": asdict(self.gates), "risk": asdict(self.risk)},
                          sort_keys=True, default=str).encode()
        return hashlib.sha256(blob).hexdigest()[:16]

    def to_json(self) -> dict:
        return {"version": VERSION, "config_hash": self.config_hash(), "mode": self.mode,
                "gates": asdict(self.gates), "risk": asdict(self.risk),
                "note": ("Gates are PROVISIONAL measurement boundaries motivated by 12E's evidence, "
                         "not optimised on outcomes. Risk limits are the trader's own and are "
                         "deliberately separate from allocated capital.")}


DEFAULT = Config()


LIVE_DECISION_SUPPORT_NOTE = (
    "LIVE DECISION SUPPORT. Live market data, real-time gates, a hypothetical position and a "
    "risk brake. No order is placed and no broker API is reachable from this engine -- the "
    "trader decides whether to execute. Gates are provisional measurement boundaries, not "
    "validated rules, and 13A is NOT VALIDATED FOR LIVE DEPLOYMENT."
)
