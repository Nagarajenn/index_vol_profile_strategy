from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, Double, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class OptionChainRaw(Base):
    __tablename__ = "option_chain_raw"
    __table_args__ = (
        UniqueConstraint("symbol", "expiry", "fetched_at", name="option_chain_raw_symbol_expiry_fetched_at_key"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    symbol: Mapped[str] = mapped_column(Text, nullable=False)
    expiry: Mapped[date] = mapped_column(Date, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    spot: Mapped[float | None] = mapped_column(Double, nullable=True)
    raw_payload: Mapped[dict] = mapped_column(JSONB, nullable=False)


class OptionChainSummary(Base):
    __tablename__ = "option_chain_summary"
    __table_args__ = (
        UniqueConstraint(
            "symbol", "expiry", "fetched_at", name="option_chain_summary_symbol_expiry_fetched_at_key"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    symbol: Mapped[str] = mapped_column(Text, nullable=False)
    expiry: Mapped[date] = mapped_column(Date, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    spot: Mapped[float | None] = mapped_column(Double, nullable=True)
    atm_strike: Mapped[float | None] = mapped_column(Double, nullable=True)
    pcr: Mapped[float | None] = mapped_column(Double, nullable=True)
    call_oi_change_near_atm: Mapped[float | None] = mapped_column(Double, nullable=True)
    put_oi_change_near_atm: Mapped[float | None] = mapped_column(Double, nullable=True)
    total_call_oi: Mapped[float | None] = mapped_column(Double, nullable=True)
    total_put_oi: Mapped[float | None] = mapped_column(Double, nullable=True)
    atm_iv_call: Mapped[float | None] = mapped_column(Double, nullable=True)
    atm_iv_put: Mapped[float | None] = mapped_column(Double, nullable=True)
    max_call_oi_strike: Mapped[float | None] = mapped_column(Double, nullable=True)
    max_put_oi_strike: Mapped[float | None] = mapped_column(Double, nullable=True)
