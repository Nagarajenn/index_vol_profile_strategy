from datetime import date, datetime

from sqlalchemy import BigInteger, Boolean, Date, DateTime, Double, ForeignKey, Integer, SmallInteger, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class PaperDecision(Base):
    """The immutable 14:59 snapshot, including every NO TRADE. Read-only
    from the API's perspective -- only the paper agent process writes."""
    __tablename__ = "paper_decisions"
    __table_args__ = (UniqueConstraint("symbol", "session_date", "configuration_hash"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    symbol: Mapped[str] = mapped_column(Text, nullable=False)
    session_date: Mapped[date] = mapped_column(Date, nullable=False)
    decision_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    decision: Mapped[str] = mapped_column(Text, nullable=False)
    decision_reason: Mapped[str] = mapped_column(Text, nullable=False)
    no_trade_reason: Mapped[str | None] = mapped_column(Text)
    trend_assessment: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[int] = mapped_column(SmallInteger, nullable=False)

    strategy_version: Mapped[str] = mapped_column(Text, nullable=False)
    decision_version: Mapped[str] = mapped_column(Text, nullable=False)
    configuration_version: Mapped[str] = mapped_column(Text, nullable=False)
    configuration_hash: Mapped[str] = mapped_column(Text, nullable=False)

    spot: Mapped[float | None] = mapped_column(Double)
    trend_label: Mapped[str | None] = mapped_column(Text)
    institutional_bias_label: Mapped[str | None] = mapped_column(Text)
    vwap: Mapped[float | None] = mapped_column(Double)
    poc: Mapped[float | None] = mapped_column(Double)
    vah: Mapped[float | None] = mapped_column(Double)
    val: Mapped[float | None] = mapped_column(Double)
    support_low: Mapped[float | None] = mapped_column(Double)
    support_high: Mapped[float | None] = mapped_column(Double)
    resistance_low: Mapped[float | None] = mapped_column(Double)
    resistance_high: Mapped[float | None] = mapped_column(Double)
    atr_14: Mapped[float | None] = mapped_column(Double)

    rvol_pct: Mapped[float | None] = mapped_column(Double)
    dominant_side: Mapped[str | None] = mapped_column(Text)
    volume_character: Mapped[str | None] = mapped_column(Text)
    amd_phase: Mapped[str | None] = mapped_column(Text)

    pcr: Mapped[float | None] = mapped_column(Double)
    atm_iv_call: Mapped[float | None] = mapped_column(Double)
    atm_iv_put: Mapped[float | None] = mapped_column(Double)
    option_snapshot_age_sec: Mapped[float | None] = mapped_column(Double)

    transition_verdict: Mapped[str | None] = mapped_column(Text)
    probability_up: Mapped[float | None] = mapped_column(Double)
    probability_down: Mapped[float | None] = mapped_column(Double)
    probability_no_move: Mapped[float | None] = mapped_column(Double)
    expected_move_low: Mapped[float | None] = mapped_column(Double)
    expected_move_high: Mapped[float | None] = mapped_column(Double)
    transition_risk_tier: Mapped[str | None] = mapped_column(Text)
    n_analogs: Mapped[int | None] = mapped_column(Integer)

    option_type: Mapped[str | None] = mapped_column(Text)
    strike: Mapped[float | None] = mapped_column(Double)
    expiry: Mapped[date | None] = mapped_column(Date)
    entry_bid: Mapped[float | None] = mapped_column(Double)
    entry_ask: Mapped[float | None] = mapped_column(Double)
    entry_spread: Mapped[float | None] = mapped_column(Double)
    entry_spread_pct: Mapped[float | None] = mapped_column(Double)
    option_delta: Mapped[float | None] = mapped_column(Double)

    dynamic_stop: Mapped[float | None] = mapped_column(Double)
    dynamic_target: Mapped[float | None] = mapped_column(Double)
    underlying_invalidation: Mapped[float | None] = mapped_column(Double)
    underlying_target: Mapped[float | None] = mapped_column(Double)
    reward_risk: Mapped[float | None] = mapped_column(Double)
    risk_amount: Mapped[float | None] = mapped_column(Double)
    quantity: Mapped[int | None] = mapped_column(Integer)
    capital_allocated: Mapped[float | None] = mapped_column(Double)

    supporting_factors: Mapped[list | None] = mapped_column(JSONB)
    conflicting_factors: Mapped[list | None] = mapped_column(JSONB)
    risk_factors: Mapped[list | None] = mapped_column(JSONB)
    explanation: Mapped[list | None] = mapped_column(JSONB)
    data_quality: Mapped[str] = mapped_column(Text, nullable=False)
    missing_fields: Mapped[list | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PaperPosition(Base):
    """A simulated position. entry_price is always the ASK and exit_price
    always the BID; all P&L is PRE-COST (pnl_basis records that)."""
    __tablename__ = "paper_positions"
    __table_args__ = (UniqueConstraint("symbol", "session_date", "entry_timestamp"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    decision_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("paper_decisions.id"))
    symbol: Mapped[str] = mapped_column(Text, nullable=False)
    session_date: Mapped[date] = mapped_column(Date, nullable=False)
    option_type: Mapped[str] = mapped_column(Text, nullable=False)
    strike: Mapped[float] = mapped_column(Double, nullable=False)
    expiry: Mapped[date | None] = mapped_column(Date)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)

    entry_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    entry_bid: Mapped[float | None] = mapped_column(Double)
    entry_ask: Mapped[float | None] = mapped_column(Double)
    entry_ltp: Mapped[float | None] = mapped_column(Double)
    entry_spread: Mapped[float | None] = mapped_column(Double)
    entry_spread_pct: Mapped[float | None] = mapped_column(Double)
    entry_price: Mapped[float] = mapped_column(Double, nullable=False)
    capital_allocated: Mapped[float] = mapped_column(Double, nullable=False)
    spot_at_entry: Mapped[float | None] = mapped_column(Double)

    initial_stop: Mapped[float] = mapped_column(Double, nullable=False)
    initial_target: Mapped[float] = mapped_column(Double, nullable=False)
    current_stop: Mapped[float] = mapped_column(Double, nullable=False)
    current_target: Mapped[float] = mapped_column(Double, nullable=False)

    is_open: Mapped[bool] = mapped_column(Boolean, nullable=False)
    exit_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    exit_bid: Mapped[float | None] = mapped_column(Double)
    exit_ask: Mapped[float | None] = mapped_column(Double)
    exit_price: Mapped[float | None] = mapped_column(Double)
    exit_reason: Mapped[str | None] = mapped_column(Text)
    gross_pnl: Mapped[float | None] = mapped_column(Double)
    costs: Mapped[float | None] = mapped_column(Double)
    net_pnl: Mapped[float | None] = mapped_column(Double)
    pnl_basis: Mapped[str] = mapped_column(Text, nullable=False)
    return_pct: Mapped[float | None] = mapped_column(Double)
    mfe_pct: Mapped[float | None] = mapped_column(Double)
    mae_pct: Mapped[float | None] = mapped_column(Double)
    underlying_move: Mapped[float | None] = mapped_column(Double)
    direction_correct: Mapped[bool | None] = mapped_column(Boolean)
    data_quality: Mapped[str] = mapped_column(Text, nullable=False)
    strategy_version: Mapped[str] = mapped_column(Text, nullable=False)
    configuration_hash: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PaperPositionEvent(Base):
    """Append-only management audit -- one row per managed minute."""
    __tablename__ = "paper_position_events"
    __table_args__ = (UniqueConstraint("position_id", "event_timestamp"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    position_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("paper_positions.id"), nullable=False)
    event_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    minutes_in_trade: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    underlying_price: Mapped[float | None] = mapped_column(Double)
    option_bid: Mapped[float | None] = mapped_column(Double)
    option_ask: Mapped[float | None] = mapped_column(Double)
    unrealized_pnl: Mapped[float | None] = mapped_column(Double)
    momentum: Mapped[str | None] = mapped_column(Text)
    current_stop: Mapped[float | None] = mapped_column(Double)
    current_target: Mapped[float | None] = mapped_column(Double)
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PaperAccountSnapshot(Base):
    __tablename__ = "paper_account_snapshots"
    __table_args__ = (UniqueConstraint("session_date", "configuration_hash"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    session_date: Mapped[date] = mapped_column(Date, nullable=False)
    starting_capital: Mapped[float] = mapped_column(Double, nullable=False)
    current_capital: Mapped[float] = mapped_column(Double, nullable=False)
    available_capital: Mapped[float] = mapped_column(Double, nullable=False)
    capital_in_trade: Mapped[float] = mapped_column(Double, nullable=False)
    realized_pnl: Mapped[float] = mapped_column(Double, nullable=False)
    unrealized_pnl: Mapped[float] = mapped_column(Double, nullable=False)
    daily_pnl: Mapped[float] = mapped_column(Double, nullable=False)
    total_pnl: Mapped[float] = mapped_column(Double, nullable=False)
    daily_drawdown: Mapped[float] = mapped_column(Double, nullable=False)
    max_drawdown: Mapped[float] = mapped_column(Double, nullable=False)
    trade_count: Mapped[int] = mapped_column(Integer, nullable=False)
    win_count: Mapped[int] = mapped_column(Integer, nullable=False)
    loss_count: Mapped[int] = mapped_column(Integer, nullable=False)
    consecutive_wins: Mapped[int] = mapped_column(Integer, nullable=False)
    consecutive_losses: Mapped[int] = mapped_column(Integer, nullable=False)
    average_win: Mapped[float | None] = mapped_column(Double)
    average_loss: Mapped[float | None] = mapped_column(Double)
    largest_win: Mapped[float | None] = mapped_column(Double)
    largest_loss: Mapped[float | None] = mapped_column(Double)
    profit_factor: Mapped[float | None] = mapped_column(Double)
    strategy_version: Mapped[str] = mapped_column(Text, nullable=False)
    configuration_hash: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PaperSession(Base):
    """Operational state of the paper engine, including the kill switch."""
    __tablename__ = "paper_sessions"
    __table_args__ = (UniqueConstraint("session_date", "configuration_hash"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    session_date: Mapped[date] = mapped_column(Date, nullable=False)
    agent_state: Mapped[str] = mapped_column(Text, nullable=False)
    kill_switch_active: Mapped[bool] = mapped_column(Boolean, nullable=False)
    kill_switch_reason: Mapped[str | None] = mapped_column(Text)
    last_heartbeat: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    strategy_version: Mapped[str] = mapped_column(Text, nullable=False)
    configuration_hash: Mapped[str] = mapped_column(Text, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
