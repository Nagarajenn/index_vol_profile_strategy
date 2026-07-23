import sys
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from app.exceptions import NoDataAvailableError, SymbolNotFoundError
from app.models import RawCandle
from app.services.volume_profile_intelligence_service import VolumeProfileIntelligenceService


def _candle(day: int, hour: int, minute: int, price: float = 100.0, volume: float = 10.0) -> RawCandle:
    return RawCandle(
        symbol="NIFTY",
        timestamp=datetime(2026, 7, day, hour, minute, tzinfo=timezone.utc),
        open=price,
        high=price,
        low=price,
        close=price,
        volume=volume,
    )


def test_group_by_date_splits_rows_into_per_day_frames():
    rows = [_candle(20, 9, 15), _candle(20, 9, 16), _candle(21, 9, 15)]
    grouped = VolumeProfileIntelligenceService._group_by_date(rows)

    assert set(grouped.keys()) == {date(2026, 7, 20), date(2026, 7, 21)}
    assert len(grouped[date(2026, 7, 20)]) == 2
    assert len(grouped[date(2026, 7, 21)]) == 1
    assert list(grouped[date(2026, 7, 20)].columns) == ["timestamp", "open", "high", "low", "close", "volume"]


def test_group_by_date_empty_input():
    assert VolumeProfileIntelligenceService._group_by_date([]) == {}


class _FakeCandleRepo:
    def __init__(self, rows: list[RawCandle]) -> None:
        self._rows = rows

    async def list_since(self, symbol: str, since: datetime) -> list[RawCandle]:
        return [r for r in self._rows if r.timestamp >= since]


@pytest.mark.asyncio
async def test_get_latest_raises_for_unknown_symbol():
    service = VolumeProfileIntelligenceService(_FakeCandleRepo([]))
    with pytest.raises(SymbolNotFoundError):
        await service.get_latest("DOGE")


@pytest.mark.asyncio
async def test_get_latest_raises_when_no_candles():
    service = VolumeProfileIntelligenceService(_FakeCandleRepo([]))
    with pytest.raises(NoDataAvailableError):
        await service.get_latest("NIFTY")


@pytest.mark.asyncio
async def test_get_latest_returns_populated_dto():
    rows = [
        _candle(20, 9, 15, price=100.0, volume=50),
        _candle(20, 9, 20, price=101.0, volume=50),
        _candle(21, 9, 15, price=105.0, volume=50),
        _candle(21, 9, 20, price=105.0, volume=50),
    ]
    service = VolumeProfileIntelligenceService(_FakeCandleRepo(rows))
    dto = await service.get_latest("NIFTY")

    assert dto.symbol == "NIFTY"
    assert dto.as_of is not None
    assert dto.developing != []
    assert dto.profile_shape is not None
    assert dto.migration is not None  # two distinct days present -> migration computable
