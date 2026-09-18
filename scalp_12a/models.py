"""Pure data containers for 12A. No DB, no network, no clock."""

from dataclasses import dataclass, field
from datetime import date, datetime


@dataclass(frozen=True)
class Quote:
    bid: float | None
    ask: float | None
    mid: float | None
    spread_pct: float | None
    quote_age_s: float | None = None
    volume_delta: float | None = None
    depth_imbalance: float | None = None

    @property
    def valid(self) -> bool:
        return bool(self.bid and self.ask and self.bid > 0 and self.ask >= self.bid)


@dataclass(frozen=True)
class Leg:
    option_type: str          # CE / PE
    atm_offset: int           # strike steps from the band ATM
    strike: float
    security_id: int | None = None


@dataclass
class SessionBars:
    """One symbol-day of aligned 5-second bars.

    ``times[i]`` is the bar START; bar i is complete at times[i] + 5 s.
    ``fut``/``idx`` are close prices with None where no update landed in the
    bar; ``fut_updated[i]`` is True when the futures actually printed in bar i.
    ``quotes[(type, offset)][i]`` is that leg's 5-second state (or None).
    """

    symbol: str
    trading_date: date
    expiry: date | None
    band_atm_strike: float
    strike_step: float
    times: list[datetime]
    fut: list[float | None]
    fut_updated: list[bool]
    idx: list[float | None]
    legs: dict[tuple[str, int], Leg]
    quotes: dict[tuple[str, int], list[Quote | None]]

    @property
    def is_expiry_day(self) -> bool:
        return self.expiry is not None and self.expiry == self.trading_date

    def __len__(self) -> int:
        return len(self.times)

    def fut_ffill(self, i: int) -> float | None:
        for k in range(i, -1, -1):
            if self.fut[k] is not None:
                return self.fut[k]
        return None

    def quote(self, key: tuple[str, int], i: int) -> Quote | None:
        series = self.quotes.get(key)
        if series is None or i < 0 or i >= len(series):
            return None
        return series[i]


@dataclass(frozen=True)
class Thresholds:
    """Causal thresholds: built only from HR days strictly BEFORE the session."""

    thr30_event: float | None
    thr30_weak: float | None
    thr180_event: float | None
    history_days: tuple[str, ...]
    sufficient: bool


@dataclass
class Event:
    bar_index: int
    event_type: str
    strength: str             # STRONG / WEAK
    direction: int            # +1 up (CE), -1 down (PE)
    r15: float | None
    r30: float | None
    r180: float | None
    r180_prior: float | None
    r300: float | None
    displacement: float       # the move that defines the event (30 s or 180 s)
    origin_price: float       # futures price where the event started
    consistency: float | None = None


@dataclass
class Selection:
    leg: Leg | None
    quote: Quote | None
    response_pct: float | None
    score: float | None
    considered: int
    rejections: dict[str, int] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)


@dataclass
class RiskPlan:
    entry_ref_ask: float
    stop_price: float
    target_price: float
    stop_pct: float
    target_pct: float
    quantity: int
    rupee_risk: float
    underlying_invalidation: float
    max_hold_seconds: int
    reasons: list[str] = field(default_factory=list)


@dataclass
class ExitResult:
    entry_index: int
    entry_ask: float
    exit_index: int | None
    exit_bid: float | None
    reason: str
    pnl_pct: float | None
    hold_seconds: float | None
    peak_gain_pct: float | None
    worst_pct: float | None
    stop_history: list[float] = field(default_factory=list)
    exit_ts: datetime | None = None


@dataclass
class Counterfactual:
    entry_index: int
    entry_ts: datetime
    entry_ask: float
    entry_spread_pct: float | None
    mfe_pct: float | None
    mae_pct: float | None
    t_mfe_s: float | None
    t_mae_s: float | None
    horizon_exit_pct: dict[int, float | None]
    horizon_mfe_pct: dict[int, float | None]
    horizon_mae_pct: dict[int, float | None]
    underlying_move: float | None
    complete: bool


@dataclass
class Candidate:
    symbol: str
    trading_date: date
    bar_index: int
    bar_ts: datetime
    mode: str
    event: Event
    selection: Selection | None
    risk: RiskPlan | None
    no_trade_reasons: list[str]
    passed_gates: bool          # all event/confirmation/liquidity/risk/veto gates
    would_trade: bool           # passed_gates AND policy (position/daily limits) allowed it
    confirmation: dict
    context: dict
    counterfactual: Counterfactual | None = None
    policy_exit: ExitResult | None = None
    counterfactual_exit: ExitResult | None = None   # active-exit outcome for EVERY candidate (research)
    counterfactual_leg_source: str = "SELECTED"     # SELECTED / ATM_FALLBACK / NONE
    opportunity: object = None                      # opportunity.Opportunity (research measurement)
    data_quality: str = "GOOD"
