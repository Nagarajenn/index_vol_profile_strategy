from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, Double, Index, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class RawCandle(Base):
    __tablename__ = "raw_candles"
    __table_args__ = (
        UniqueConstraint("symbol", "timestamp", name="raw_candles_symbol_timestamp_key"),
        Index("idx_raw_candles_symbol_ts", "symbol", text("timestamp DESC")),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    symbol: Mapped[str] = mapped_column(Text, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    open: Mapped[float] = mapped_column(Double, nullable=False)
    high: Mapped[float] = mapped_column(Double, nullable=False)
    low: Mapped[float] = mapped_column(Double, nullable=False)
    close: Mapped[float] = mapped_column(Double, nullable=False)
    volume: Mapped[float] = mapped_column(Double, nullable=False)
    open_interest: Mapped[float | None] = mapped_column(Double, nullable=True)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))


class RawDailyCandle(Base):
    __tablename__ = "raw_daily_candles"
    __table_args__ = (UniqueConstraint("symbol", "date", name="raw_daily_candles_symbol_date_key"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    symbol: Mapped[str] = mapped_column(Text, nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    open: Mapped[float] = mapped_column(Double, nullable=False)
    high: Mapped[float] = mapped_column(Double, nullable=False)
    low: Mapped[float] = mapped_column(Double, nullable=False)
    close: Mapped[float] = mapped_column(Double, nullable=False)
    volume: Mapped[float] = mapped_column(Double, nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
