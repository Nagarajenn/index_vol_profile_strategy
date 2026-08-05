import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from app.exceptions import NoDataAvailableError, SymbolNotFoundError
from app.models import RawCandle
from app.services.volume_intelligence_service import VolumeIntelligenceService


def _day(days_ago: int):
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).date()


def _session_rows(days_ago: int, n: int = 30, base_price: float = 100.0) -> list[RawCandle]:
    d = _day(days_ago)
    rows = []
    price = base_price
    for i in range(n):
        minute = 15 + i
        hour = 9 + minute // 60
        min_ = minute % 60
        price += 0.3
        rows.append(
            RawCandle(
                symbol="NIFTY",
                timestamp=datetime(d.year, d.month, d.day, hour, min_, tzinfo=timezone.utc),
                open=price - 0.3,
                high=price + 0.5,
                low=price - 0.6,
                close=price,
                volume=100 + (i % 5) * 10,
            )
        )
    return rows


def test_group_by_date_splits_rows_into_per_day_frames():
    rows = _session_rows(1, n=2) + _session_rows(0, n=1)
    grouped = VolumeIntelligenceService._group_by_date(rows)

    assert set(grouped.keys()) == {_day(1), _day(0)}
    assert len(grouped[_day(1)]) == 2
    assert len(grouped[_day(0)]) == 1
    assert list(grouped[_day(1)].columns) == ["timestamp", "open", "high", "low", "close", "volume"]


def test_group_by_date_empty_input():
    assert VolumeIntelligenceService._group_by_date([]) == {}


class _FakeCandleRepo:
    def __init__(self, rows: list[RawCandle]) -> None:
        self._rows = rows

    async def list_since(self, symbol: str, since: datetime) -> list[RawCandle]:
        return [r for r in self._rows if r.timestamp >= since]


@pytest.mark.asyncio
async def test_get_latest_raises_for_unknown_symbol():
    service = VolumeIntelligenceService(_FakeCandleRepo([]))
    with pytest.raises(SymbolNotFoundError):
        await service.get_latest("DOGE")


@pytest.mark.asyncio
async def test_get_latest_raises_when_no_candles():
    service = VolumeIntelligenceService(_FakeCandleRepo([]))
    with pytest.raises(NoDataAvailableError):
        await service.get_latest("NIFTY")


@pytest.mark.asyncio
async def test_get_latest_returns_populated_dto():
    rows: list[RawCandle] = []
    for days_ago in range(30, 0, -1):
        rows.extend(_session_rows(days_ago, n=30))
    rows.extend(_session_rows(0, n=30))
    service = VolumeIntelligenceService(_FakeCandleRepo(rows))

    dto = await service.get_latest("NIFTY")

    assert dto.symbol == "NIFTY"
    assert dto.as_of is not None
    assert dto.rvol is not None
    assert dto.dominance is not None
    assert dto.momentum is not None
    assert dto.institutional is not None
    assert dto.trend is not None
    assert dto.character is not None
    assert dto.daily_volume_trend is not None
    assert len(dto.daily_volume_trend.days) == 5
    assert isinstance(dto.significant_intervals, list)
    assert dto.forecast is not None
    assert dto.narrative is not None
    assert dto.narrative.headline != ""
