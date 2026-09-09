"""DTOs for the Paper Trading Command Center.

Everything here is read-only. The API exposes no write endpoint for the
paper engine: only the agent process (paper_trading/) creates decisions
and positions, so no frontend request can ever cause a trade.
"""

from datetime import date, datetime

from pydantic import BaseModel


class PaperDecisionDTO(BaseModel):
    symbol: str
    session_date: date
    decision_timestamp: datetime
    decision: str
    decision_reason: str
    no_trade_reason: str | None = None
    trend_assessment: str
    confidence: int

    strategy_version: str
    configuration_hash: str

    spot: float | None = None
    trend_label: str | None = None
    institutional_bias_label: str | None = None
    vwap: float | None = None
    poc: float | None = None
    support_low: float | None = None
    support_high: float | None = None
    resistance_low: float | None = None
    resistance_high: float | None = None
    atr_14: float | None = None
    rvol_pct: float | None = None
    dominant_side: str | None = None
    pcr: float | None = None
    atm_iv_call: float | None = None
    atm_iv_put: float | None = None

    transition_verdict: str | None = None
    probability_up: float | None = None
    probability_down: float | None = None
    probability_no_move: float | None = None
    expected_move_low: float | None = None
    expected_move_high: float | None = None
    transition_risk_tier: str | None = None
    n_analogs: int | None = None

    option_type: str | None = None
    strike: float | None = None
    expiry: date | None = None
    entry_bid: float | None = None
    entry_ask: float | None = None
    entry_spread_pct: float | None = None
    option_delta: float | None = None
    dynamic_stop: float | None = None
    dynamic_target: float | None = None
    underlying_invalidation: float | None = None
    underlying_target: float | None = None
    reward_risk: float | None = None
    quantity: int | None = None
    capital_allocated: float | None = None

    supporting_factors: list[str] = []
    conflicting_factors: list[str] = []
    risk_factors: list[str] = []
    explanation: list[str] = []
    data_quality: str
    missing_fields: list[str] = []

    model_config = {"from_attributes": True}


class PaperPositionEventDTO(BaseModel):
    event_timestamp: datetime
    minutes_in_trade: int
    event_type: str
    underlying_price: float | None = None
    option_bid: float | None = None
    option_ask: float | None = None
    unrealized_pnl: float | None = None
    momentum: str | None = None
    current_stop: float | None = None
    current_target: float | None = None
    note: str | None = None

    model_config = {"from_attributes": True}


class PaperPositionDTO(BaseModel):
    id: int
    symbol: str
    session_date: date
    option_type: str
    strike: float
    expiry: date | None = None
    quantity: int
    entry_timestamp: datetime
    entry_bid: float | None = None
    entry_ask: float | None = None
    entry_spread_pct: float | None = None
    entry_price: float
    capital_allocated: float
    spot_at_entry: float | None = None
    initial_stop: float
    initial_target: float
    current_stop: float
    current_target: float
    is_open: bool
    exit_timestamp: datetime | None = None
    exit_bid: float | None = None
    exit_price: float | None = None
    exit_reason: str | None = None
    gross_pnl: float | None = None
    net_pnl: float | None = None
    pnl_basis: str
    return_pct: float | None = None
    mfe_pct: float | None = None
    mae_pct: float | None = None
    underlying_move: float | None = None
    direction_correct: bool | None = None
    data_quality: str
    events: list[PaperPositionEventDTO] = []

    model_config = {"from_attributes": True}


class PaperAccountDTO(BaseModel):
    session_date: date | None = None
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
    max_drawdown_pct: float
    trade_count: int
    win_count: int
    loss_count: int
    win_rate: float | None = None
    consecutive_wins: int
    consecutive_losses: int
    average_win: float | None = None
    average_loss: float | None = None
    largest_win: float | None = None
    largest_loss: float | None = None
    profit_factor: float | None = None
    pnl_basis: str = "PRE_COST"


class PaperStatusDTO(BaseModel):
    paper_mode: bool
    agent_state: str
    kill_switch_active: bool
    session_date: date | None = None
    last_heartbeat: datetime | None = None
    strategy_version: str
    configuration_version: str
    configuration_hash: str
    experiment_day: int | None = None
    experiment_total_days: int = 5
    underlying_data_age_sec: float | None = None
    option_data_age_sec: float | None = None
    database_ok: bool = True


class DecisionOutcomeDTO(BaseModel):
    """Direction correctness and option profitability are separate
    questions -- a correct call that lost money is not a good trade, and
    a wrong call that made money is not evidence of skill."""
    symbol: str
    session_date: date
    decision: str
    forecast_direction: str | None = None
    actual_direction: str | None = None
    direction_correct: bool | None = None
    option_profitable: bool | None = None
    net_pnl: float | None = None
    decision_quality: str


class PaperTodayDTO(BaseModel):
    session_date: date
    status: PaperStatusDTO
    account: PaperAccountDTO
    decisions: list[PaperDecisionDTO]
    open_position: PaperPositionDTO | None = None
    closed_today: list[PaperPositionDTO] = []
    outcomes: list[DecisionOutcomeDTO] = []
