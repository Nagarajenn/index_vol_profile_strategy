import sys
from datetime import date, datetime, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from app.core.config import settings
from app.exceptions import NoDataAvailableError, SymbolNotFoundError
from app.models import OptionChainRaw, RawCandle
from app.services.option_risk_service import OptionRiskService

D = date(2026, 9, 18)


def _snap(minute: int, spot: float) -> OptionChainRaw:
    oc = {}
    for off in range(-6, 7):
        k = 23400.0 + 50 * off
        ce = max(spot - k, 0) + 40.0
        pe = max(k - spot, 0) + 40.0
        oc[f"{k:.6f}"] = {t: dict(last_price=p, top_bid_price=p - 0.1, top_ask_price=p + 0.1, top_bid_quantity=100,
                                  top_ask_quantity=100, volume=1000 + minute * 10, oi=5000, implied_volatility=12.0,
                                  greeks=dict(delta=0.5, gamma=0.001, theta=-2.0, vega=1.0))
                          for t, p in (("ce", ce), ("pe", pe))}
    ts = datetime.combine(D, time(15, 0), tzinfo=settings.ist).replace(minute=minute)
    return OptionChainRaw(symbol="NIFTY", expiry=D, fetched_at=ts, spot=spot, raw_payload={"oc": oc, "last_price": spot})


class _FakeRepo:
    def __init__(self, snaps):
        self.snaps = snaps

    async def latest_session_date(self, symbol):
        return D if self.snaps else None

    async def list_snapshots(self, symbol, start, end):
        return self.snaps

    async def list_candles(self, symbol, start, end):
        return [RawCandle(symbol="NIFTY", timestamp=s.fetched_at, open=s.spot, high=s.spot, low=s.spot, close=s.spot, volume=0)
                for s in self.snaps]

    async def list_positions(self, symbol, session_date):
        return []


@pytest.mark.asyncio
async def test_unknown_symbol_raises():
    with pytest.raises(SymbolNotFoundError):
        await OptionRiskService(_FakeRepo([])).get_closing_state("NOPE")


@pytest.mark.asyncio
async def test_no_data_raises():
    with pytest.raises(NoDataAvailableError):
        await OptionRiskService(_FakeRepo([])).get_closing_state("NIFTY")


@pytest.mark.asyncio
async def test_closing_state_is_advisory_and_covers_1500_1530():
    snaps = [_snap(m, 23400.0 + (m if m <= 15 else 15)) for m in range(0, 30)]
    dto = await OptionRiskService(_FakeRepo(snaps)).get_closing_state("NIFTY", D)
    assert dto.advisory_only is True and dto.version == "12B-option-risk-v1"
    assert dto.minutes[0]["minute"] == "15:00" and dto.minutes[-1]["minute"] == "15:30"
    assert dto.summary["missing_option_minutes"] == ["15:30"]
    assert any(m["underlying"]["state"] == "STALE" for m in dto.minutes if m["minute"] > "15:16")
