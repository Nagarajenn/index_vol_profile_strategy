import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from app.core.config import settings
from app.exceptions import NoDataAvailableError, SymbolNotFoundError
from app.models import RawCandle
from app.services.session_amd_service import SessionAmdService


def _today_rows(n: int = 15, base_price: float = 100.0) -> list[RawCandle]:
    """A thin (still-accumulating) session's worth of today's candles --
    enough to exercise the service's fetch/convert/compute/DTO-map path
    without needing a full 30-minute accumulation window (that's what
    tests/test_session_amd.py already covers thoroughly at the pure-
    function layer). Timestamps are anchored directly off `settings.ist`
    "now" (not a UTC offset guess), so this can't flake near the UTC/IST
    day-boundary mismatch window -- it always matches whatever the service
    itself computes as "today"."""
    ist_now = datetime.now(settings.ist)
    rows = []
    price = base_price
    for i in range(n):
        price += 0.2
        rows.append(
            RawCandle(
                symbol="NIFTY",
                timestamp=ist_now.replace(hour=9, minute=15 + i, second=0, microsecond=0),
                open=price - 0.2, high=price + 0.3, low=price - 0.4, close=price,
                volume=100 + i,
            )
        )
    return rows


class _FakeCandleRepo:
    def __init__(self, rows: list[RawCandle]) -> None:
        self._rows = rows

    async def list_since(self, symbol: str, since: datetime) -> list[RawCandle]:
        return [r for r in self._rows if r.timestamp >= since]


@pytest.mark.asyncio
async def test_get_latest_raises_for_unknown_symbol():
    service = SessionAmdService(_FakeCandleRepo([]))
    with pytest.raises(SymbolNotFoundError):
        await service.get_latest("DOGE")


@pytest.mark.asyncio
async def test_get_latest_raises_when_no_candles_today():
    service = SessionAmdService(_FakeCandleRepo([]))
    with pytest.raises(NoDataAvailableError):
        await service.get_latest("NIFTY")


@pytest.mark.asyncio
async def test_get_latest_returns_populated_dto_for_a_thin_session():
    service = SessionAmdService(_FakeCandleRepo(_today_rows(n=15)))

    dto = await service.get_latest("NIFTY")

    assert dto.symbol == "NIFTY"
    assert dto.as_of is not None
    # 15 minutes of candles is short of the 30-minute accumulation window --
    # honestly reports "still accumulating", not a fabricated phase.
    assert dto.accumulation is not None
    assert dto.accumulation.is_complete is False
    assert dto.current_phase == "Accumulating"
    assert dto.sweeps == []
    assert dto.distribution is None
    assert dto.narrative != ""


@pytest.mark.asyncio
async def test_to_dataframe_sorts_by_timestamp():
    rows = list(reversed(_today_rows(n=5)))
    df = SessionAmdService._to_dataframe(rows)
    assert list(df["timestamp"]) == sorted(df["timestamp"])
