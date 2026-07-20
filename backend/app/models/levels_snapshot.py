from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Double,
    Index,
    SmallInteger,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class LevelsSnapshot(Base):
    __tablename__ = "levels_snapshots"
    __table_args__ = (
        UniqueConstraint("symbol", "as_of", name="levels_snapshots_symbol_as_of_key"),
        CheckConstraint("mode IN ('live', 'backfill')", name="levels_snapshots_mode_check"),
        Index("idx_levels_symbol_asof", "symbol", text("as_of DESC")),
        Index("idx_levels_symbol_mode_asof", "symbol", "mode", text("as_of DESC")),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    symbol: Mapped[str] = mapped_column(Text, nullable=False)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    mode: Mapped[str] = mapped_column(Text, nullable=False)

    close: Mapped[float] = mapped_column(Double, nullable=False)
    vwap_now: Mapped[float | None] = mapped_column(Double, nullable=True)

    today_poc: Mapped[float | None] = mapped_column(Double, nullable=True)
    today_vah: Mapped[float | None] = mapped_column(Double, nullable=True)
    today_val: Mapped[float | None] = mapped_column(Double, nullable=True)
    today_total_volume: Mapped[float | None] = mapped_column(Double, nullable=True)

    yesterday_poc: Mapped[float | None] = mapped_column(Double, nullable=True)
    yesterday_vah: Mapped[float | None] = mapped_column(Double, nullable=True)
    yesterday_val: Mapped[float | None] = mapped_column(Double, nullable=True)

    support_low: Mapped[float | None] = mapped_column(Double, nullable=True)
    support_high: Mapped[float | None] = mapped_column(Double, nullable=True)
    resistance_low: Mapped[float | None] = mapped_column(Double, nullable=True)
    resistance_high: Mapped[float | None] = mapped_column(Double, nullable=True)

    trend_label: Mapped[str | None] = mapped_column(Text, nullable=True)
    trend_score: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)

    institutional_bias_label: Mapped[str | None] = mapped_column(Text, nullable=True)
    institutional_bias_score: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    institutional_bias_data: Mapped[str | None] = mapped_column(Text, nullable=True)

    confidence_score: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    sub_score_trend_alignment: Mapped[float | None] = mapped_column(Double, nullable=True)
    sub_score_vwap_position: Mapped[float | None] = mapped_column(Double, nullable=True)
    sub_score_structure_hh_hl: Mapped[float | None] = mapped_column(Double, nullable=True)
    sub_score_trendline_confluence: Mapped[float | None] = mapped_column(Double, nullable=True)
    sub_score_sr_proximity: Mapped[float | None] = mapped_column(Double, nullable=True)
    sub_score_breakout_confirmation: Mapped[float | None] = mapped_column(Double, nullable=True)
    sub_score_institutional_bias: Mapped[float | None] = mapped_column(Double, nullable=True)

    confidence_weights_used: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    confidence_partial_data: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    action_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    today_vp_bins: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    swings: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    trendlines: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    breakout_boxes: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    chart_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    chart_triggered_by: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
