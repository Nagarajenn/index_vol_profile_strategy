"""Repository interfaces services depend on, not concrete SQLAlchemy classes.

This is what actually buys testable services -- a test can hand a
DashboardService a fake implementing these Protocols and assert behavior
without a real Postgres connection. Concrete implementations below just need
to satisfy the shape (structural typing), no explicit inheritance required.
"""

from datetime import datetime
from typing import Protocol

from app.models import (
    CasDailyTransition,
    CasFactorCorrelation,
    ClassifiedEvent,
    LevelsSnapshot,
    MtiDailyTransition,
    MtiFactorCorrelation,
    OptionChainSummary,
    RawCandle,
)


class LevelsSnapshotRepositoryProtocol(Protocol):
    async def get_latest(self, symbol: str, mode: str = "live") -> LevelsSnapshot | None: ...


class CandleRepositoryProtocol(Protocol):
    async def list_since(self, symbol: str, since: datetime) -> list[RawCandle]: ...
    async def list_between(self, symbol: str, start: datetime, end: datetime) -> list[RawCandle]: ...


class OptionChainRepositoryProtocol(Protocol):
    async def get_latest_summary(self, symbol: str) -> OptionChainSummary | None: ...


class MarketIntelligenceRepositoryProtocol(Protocol):
    async def list_recent(
        self, limit: int, relevant_only: bool = True, published_since: datetime | None = None
    ) -> list[ClassifiedEvent]: ...


class MarketTransitionRepositoryProtocol(Protocol):
    async def list_daily(self, symbol: str, limit: int = 200) -> list[MtiDailyTransition]: ...
    async def list_correlations(self, symbol: str) -> list[MtiFactorCorrelation]: ...
    async def list_cas_daily(self, symbol: str, limit: int = 60) -> list[CasDailyTransition]: ...
    async def list_cas_correlations(self, symbol: str) -> list[CasFactorCorrelation]: ...
