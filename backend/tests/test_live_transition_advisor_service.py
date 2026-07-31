import sys
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from app.core.config import settings
from app.exceptions import SymbolNotFoundError
from app.models import LevelsSnapshot, MtiDailyTransition, MtiFactorCorrelation, RawCandle
from app.services import live_transition_advisor_service as service_module
from app.services.live_transition_advisor_service import LiveTransitionAdvisorService
from app.services.market_intelligence_service import MarketIntelligenceService


class _FakeDatetime(datetime):
    """Monkeypatched in place of the service module's `datetime` so
    `datetime.now(settings.ist)` returns a fixed, test-controlled instant --
    the service reads real wall-clock time otherwise (same as
    VolumeProfileIntelligenceService), which isn't independently mockable
    via the stdlib type directly."""

    _fixed: datetime = datetime(2026, 7, 30, 14, 30, tzinfo=timezone.utc)

    @classmethod
    def now(cls, tz=None):
        return cls._fixed.astimezone(tz) if tz else cls._fixed


def _candle(session_date: date, hour: int, minute: int, price: float = 100.0, volume: float = 10.0) -> RawCandle:
    return RawCandle(
        symbol="NIFTY", timestamp=datetime(session_date.year, session_date.month, session_date.day, hour, minute, tzinfo=timezone.utc),
        open=price, high=price, low=price, close=price, volume=volume,
    )


def _session_candles(session_date: date, up_to: str) -> list[RawCandle]:
    """09:15 through `up_to` (e.g. "14:30"), one candle per minute."""
    d = session_date.isoformat()
    rows = []
    for i, t in enumerate(pd.date_range(f"{d} 09:15", f"{d} {up_to}", freq="1min")):
        rows.append(_candle(session_date, t.hour, t.minute, price=100 + i * 0.01))
    return rows


def _mti_row(session_date: date, poc_migration: float, outcome: str) -> MtiDailyTransition:
    return MtiDailyTransition(
        symbol="NIFTY", session_date=session_date,
        poc_migration_1400_1459=poc_migration, vwap_distance_1459=None, vwap_distance_1459_pct=None,
        volume_slope_1400_1459=None, realized_range_1400_1459=None, profile_shape_1459="D",
        rotation_label_1459=None, market_regime_1459=None, is_inside_initial_balance_1459=None,
        day_of_week=session_date.weekday(), expiry_type=None, prior_day_profile_shape=None, prior_day_close_vs_poc=None,
        close_1459=100, close_1501=101, market_close=101 + (10 if outcome != "reversal" else -10),
        transition_move=1, transition_direction="up", post_transition_move=10 if outcome != "reversal" else -10,
        outcome=outcome, outcome_magnitude=10,
    )


class _FakeCandleRepo:
    def __init__(self, since_rows: list[RawCandle], between_rows: list[RawCandle] | None = None) -> None:
        self._since_rows = since_rows
        self._between_rows = between_rows or []

    async def list_since(self, symbol: str, since):
        return self._since_rows

    async def list_between(self, symbol: str, start, end):
        return self._between_rows


class _FakeMtiRepo:
    def __init__(self, daily: list[MtiDailyTransition], correlations: list[MtiFactorCorrelation]) -> None:
        self._daily = daily
        self._correlations = correlations

    async def list_daily(self, symbol: str, limit: int = 500):
        return self._daily[:limit]

    async def list_correlations(self, symbol: str):
        return self._correlations


class _FakeLevelsRepo:
    def __init__(self, bias_label: str | None) -> None:
        self._bias_label = bias_label

    async def get_latest(self, symbol: str, mode: str = "live"):
        if self._bias_label is None:
            return None
        return LevelsSnapshot(symbol=symbol, as_of=datetime.now(timezone.utc), mode="live", close=100, institutional_bias_label=self._bias_label)


class _FakeMiRepo:
    async def list_recent(self, limit, relevant_only=True, published_since=None):
        return []


@pytest.mark.asyncio
async def test_get_live_advisory_raises_for_unknown_symbol():
    service = LiveTransitionAdvisorService(_FakeCandleRepo([]), _FakeMtiRepo([], []), _FakeLevelsRepo(None), MarketIntelligenceService(_FakeMiRepo()))
    with pytest.raises(SymbolNotFoundError):
        await service.get_live_advisory("DOGE")


@pytest.mark.asyncio
async def test_get_live_advisory_inactive_outside_window(monkeypatch):
    class _OutsideWindow(_FakeDatetime):
        _fixed = datetime(2026, 7, 30, 16, 0, tzinfo=timezone.utc)  # well after 3:01pm IST

    monkeypatch.setattr(service_module, "datetime", _OutsideWindow)

    service = LiveTransitionAdvisorService(_FakeCandleRepo([]), _FakeMtiRepo([], []), _FakeLevelsRepo(None), MarketIntelligenceService(_FakeMiRepo()))
    result = await service.get_live_advisory("NIFTY")

    assert result.is_active is False
    assert result.risk_level == "Observe"
    assert result.statistical_confidence == "Insufficient data"


@pytest.mark.asyncio
async def test_get_live_advisory_active_returns_scored_result(monkeypatch):
    # 14:30 IST = 09:00 UTC.
    class _InsideWindow(_FakeDatetime):
        _fixed = datetime(2026, 7, 30, 9, 0, tzinfo=timezone.utc)

    monkeypatch.setattr(service_module, "datetime", _InsideWindow)

    today = date(2026, 7, 30)
    today_candles = _session_candles(today, "14:30")

    daily = [_mti_row(date(2026, 1, 1 + i), poc_migration=50 + i, outcome="reversal") for i in range(20)]
    daily += [_mti_row(date(2026, 2, 1 + i), poc_migration=1 + i * 0.1, outcome="continuation") for i in range(20)]

    service = LiveTransitionAdvisorService(
        _FakeCandleRepo(today_candles), _FakeMtiRepo(daily, []), _FakeLevelsRepo("Mildly Bearish"), MarketIntelligenceService(_FakeMiRepo())
    )
    result = await service.get_live_advisory("NIFTY")

    assert result.stage == "Pre-Transition Monitoring"
    assert result.institutional_bias_label == "Mildly Bearish"
    assert 0.0 <= result.probability_reversal <= 1.0
    assert result.risk_level in ("Observe", "Low", "Medium", "High", "Very High")
