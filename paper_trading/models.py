"""Every dataclass and Literal the paper agent produces -- the single
source of truth for its output vocabulary (mirrors the convention in
market_transition/models.py and analytics/volume_intelligence/models.py).
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Literal

AgentState = Literal[
    "PRE_MARKET", "MARKET_MONITORING", "PRE_14_59_ANALYSIS", "DECISION_FREEZE",
    "NO_TRADE", "TRADE_APPROVED", "PAPER_ENTRY", "POSITION_MANAGEMENT",
    "PAPER_EXIT", "TRADE_COMPLETE", "DAILY_REVIEW", "RISK_BLOCKED", "DATA_ERROR",
]

Decision = Literal["TRADE_CALL", "TRADE_PUT", "NO_TRADE"]

TrendAssessment = Literal[
    "STRONG_UP", "UP", "WEAK_UP", "NEUTRAL", "WEAK_DOWN", "DOWN", "STRONG_DOWN",
]

MomentumState = Literal["STRONG", "MODERATE", "WEAKENING", "FAILED"]

NoTradeReason = Literal[
    "NO_CLEAR_DIRECTION", "LOW_CONFIDENCE", "CONFLICTING_SIGNALS",
    "EXPECTED_MOVE_TOO_SMALL", "PRICE_AT_MAJOR_RESISTANCE", "PRICE_AT_MAJOR_SUPPORT",
    "OPTION_SPREAD_TOO_WIDE", "OPTION_LIQUIDITY_TOO_LOW", "INSUFFICIENT_OPTION_DATA",
    "STALE_OPTION_DATA", "INSUFFICIENT_TRANSITION_EVIDENCE", "TRANSITION_RISK_TOO_HIGH",
    "RISK_LIMIT", "NO_VALID_OPTION", "EXPECTED_REWARD_INSUFFICIENT", "SL_TOO_TIGHT",
    "TARGET_NOT_REALISTIC", "MARKET_TOO_FLAT", "INSUFFICIENT_DATA", "KILL_SWITCH_ACTIVE",
    "STOP_EXCEEDS_RISK_BUDGET",
]

ExitReason = Literal[
    "TARGET_HIT", "STOP_HIT", "MOMENTUM_FAILURE", "DIRECTION_REVERSAL",
    "VWAP_FAILURE", "STRUCTURE_FAILURE", "OPTION_LIQUIDITY_FAILURE",
    "TIME_EXIT", "RISK_LIMIT", "MANUAL_PAPER_KILL_SWITCH", "DATA_EXCEPTION",
]

DataQuality = Literal["GOOD", "DEGRADED", "INSUFFICIENT"]


@dataclass
class MarketStateWindow:
    """One 5-minute pre-transition window, read from the existing
    cas_pretransition_windows rows -- never recomputed here."""
    window_index: int
    window_label: str
    net_point_change: float | None
    volume: float | None
    rvol_pct: float | None
    dominant_side: str | None
    price_distance_from_vwap: float | None
    poc_change_during_window: float | None
    pcr: float | None


@dataclass
class PaperMarketState:
    """Everything the agent knows at the decision cutoff. Every field is
    sourced from an existing analytics component; a field that is
    genuinely unavailable stays None and pushes data_quality down -- it is
    never fabricated."""
    symbol: str
    session_date: date
    as_of: datetime

    spot: float | None = None
    trend_label: str | None = None
    trend_score: int | None = None
    vwap: float | None = None
    distance_from_vwap: float | None = None
    vwap_slope: float | None = None
    poc: float | None = None
    poc_migration: float | None = None
    vah: float | None = None
    val: float | None = None
    support_low: float | None = None
    support_high: float | None = None
    resistance_low: float | None = None
    resistance_high: float | None = None
    atr_14: float | None = None
    recent_range_5min: float | None = None
    momentum_5min: float | None = None
    momentum_15min: float | None = None

    rvol_pct: float | None = None
    volume_trend: str | None = None
    volume_character: str | None = None
    dominant_side: str | None = None
    dominance_ratio: float | None = None
    institutional_participation: int | None = None

    amd_phase: str | None = None
    institutional_bias_label: str | None = None

    atm_strike: float | None = None
    pcr: float | None = None
    atm_iv_call: float | None = None
    atm_iv_put: float | None = None
    option_snapshot_age_sec: float | None = None

    pre_windows: list[MarketStateWindow] = field(default_factory=list)
    transition_verdict: str | None = None
    probability_up: float | None = None
    probability_down: float | None = None
    probability_no_move: float | None = None
    transition_confidence: str | None = None
    expected_move_low: float | None = None
    expected_move_high: float | None = None
    transition_risk_tier: str | None = None
    n_analogs: int | None = None

    data_quality: DataQuality = "GOOD"
    missing_fields: list[str] = field(default_factory=list)


@dataclass
class TrendVerdict:
    assessment: TrendAssessment
    score: float
    confidence: int
    supporting_factors: list[str] = field(default_factory=list)
    conflicting_factors: list[str] = field(default_factory=list)
    risk_factors: list[str] = field(default_factory=list)
    is_conflicted: bool = False


@dataclass
class PaperOptionCandidate:
    symbol: str
    option_type: Literal["CE", "PE"]
    strike: float
    expiry: date | None
    atm_offset: int
    moneyness: float | None
    ltp: float | None
    bid: float | None
    ask: float | None
    spread: float | None
    spread_pct: float | None
    volume: float | None
    oi: float | None
    oi_change: float | None
    iv: float | None
    delta: float | None
    gamma: float | None
    theta: float | None
    vega: float | None
    eligible: bool = True
    rejection_reason: str | None = None
    selection_rationale: str | None = None


@dataclass
class RiskPlan:
    """Underlying-aware stop/target, translated into option premium terms
    through delta. Every field derives from <=14:59 information only."""
    underlying_invalidation: float | None
    underlying_target: float | None
    underlying_stop_distance: float | None
    underlying_target_distance: float | None
    stop_price: float | None
    target_price: float | None
    stop_pct: float | None
    target_pct: float | None
    reward_risk: float | None
    risk_amount: float | None
    basis: str = ""
    feasible: bool = True
    infeasible_reason: NoTradeReason | None = None


@dataclass
class PaperDecision:
    """The immutable 14:59 snapshot. Once written it is never updated --
    post-entry management appends PositionEvents instead."""
    symbol: str
    session_date: date
    decision_timestamp: datetime
    decision: Decision
    decision_reason: str
    trend_assessment: TrendAssessment
    confidence: int

    strategy_version: str
    decision_version: str
    configuration_version: str
    configuration_hash: str

    state: PaperMarketState
    trend: TrendVerdict
    no_trade_reason: NoTradeReason | None = None
    candidate: PaperOptionCandidate | None = None
    risk_plan: RiskPlan | None = None
    quantity: int | None = None
    capital_allocated: float | None = None
    explanation: list[str] = field(default_factory=list)


@dataclass
class PositionEvent:
    """One post-entry management observation. Append-only -- an event can
    never modify the frozen PaperDecision it belongs to."""
    event_timestamp: datetime
    minutes_in_trade: int
    event_type: str
    underlying_price: float | None
    option_bid: float | None
    option_ask: float | None
    unrealized_pnl: float | None
    momentum: MomentumState | None
    current_stop: float | None
    current_target: float | None
    note: str = ""


@dataclass
class PaperPosition:
    symbol: str
    session_date: date
    option_type: Literal["CE", "PE"]
    strike: float
    expiry: date | None
    quantity: int
    entry_timestamp: datetime
    entry_bid: float | None
    entry_ask: float
    entry_ltp: float | None
    entry_spread: float | None
    entry_spread_pct: float | None
    entry_price: float
    capital_allocated: float
    initial_stop: float
    initial_target: float
    current_stop: float
    current_target: float
    spot_at_entry: float | None
    is_open: bool = True
    events: list[PositionEvent] = field(default_factory=list)

    exit_timestamp: datetime | None = None
    exit_bid: float | None = None
    exit_ask: float | None = None
    exit_price: float | None = None
    exit_reason: ExitReason | None = None
    gross_pnl: float | None = None
    costs: float | None = None
    net_pnl: float | None = None
    return_pct: float | None = None
    mfe_pct: float | None = None
    mae_pct: float | None = None
    underlying_move: float | None = None
    direction_correct: bool | None = None
    data_quality: DataQuality = "GOOD"


@dataclass
class PaperAccountSnapshot:
    session_date: date
    starting_capital: float
    current_capital: float
    available_capital: float
    capital_in_trade: float
    realized_pnl: float
    unrealized_pnl: float
    daily_pnl: float
    total_pnl: float
    daily_drawdown: float
    max_drawdown: float
    trade_count: int
    win_count: int
    loss_count: int
    consecutive_wins: int
    consecutive_losses: int
    average_win: float | None = None
    average_loss: float | None = None
    largest_win: float | None = None
    largest_loss: float | None = None
    profit_factor: float | None = None
