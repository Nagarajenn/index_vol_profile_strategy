from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Double,
    ForeignKey,
    SmallInteger,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class NewsItem(Base):
    __tablename__ = "news_items"
    __table_args__ = (UniqueConstraint("source", "guid", name="news_items_source_guid_key"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    link: Mapped[str] = mapped_column(Text, nullable=False)
    guid: Mapped[str] = mapped_column(Text, nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)


class ClassifiedEvent(Base):
    __tablename__ = "classified_events"
    __table_args__ = (
        UniqueConstraint("news_item_id", name="classified_events_news_item_id_key"),
        CheckConstraint("severity BETWEEN 1 AND 5", name="classified_events_severity_check"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    news_item_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("news_items.id"), nullable=False)
    is_relevant: Mapped[bool] = mapped_column(nullable=False)
    category: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    confidence: Mapped[float] = mapped_column(Double, nullable=False)
    sentiment: Mapped[str] = mapped_column(Text, nullable=False)
    expected_duration: Mapped[str] = mapped_column(Text, nullable=False)
    volatility_impact: Mapped[str] = mapped_column(Text, nullable=False)
    reversal_probability: Mapped[float] = mapped_column(Double, nullable=False)
    affected_sectors: Mapped[list] = mapped_column(JSONB, nullable=False)
    affected_indices: Mapped[list] = mapped_column(JSONB, nullable=False)
    expected_direction_nifty: Mapped[str] = mapped_column(Text, nullable=False)
    expected_direction_sensex: Mapped[str] = mapped_column(Text, nullable=False)
    expected_direction_banknifty: Mapped[str] = mapped_column(Text, nullable=False)
    recommended_action: Mapped[str] = mapped_column(Text, nullable=False)
    risk_level: Mapped[str] = mapped_column(Text, nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    classified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    news_item: Mapped[NewsItem] = relationship(lazy="joined")
