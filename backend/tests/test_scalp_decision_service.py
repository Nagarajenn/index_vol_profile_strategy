import sys
from datetime import date, datetime, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from app.core.config import settings
from app.exceptions import NoDataAvailableError, SymbolNotFoundError
from app.models import LevelsSnapshot, OptionChainRaw, PaperPosition, RawCandle
from app.services.scalp_decision_service import ScalpDecisionService

D = date(2026, 9, 18)
ATM = 23400.0


def _snap(minute: int, spot: float, ce_bias: float = 0.0) -> OptionChainRaw:
    oc = {}
    for off in range(-6, 7):
        k = ATM + 50 * off
        ce = (max(spot - k, 0) + 40.0) * (1 + ce_bias)
        pe = max(k - spot, 0) + 40.0
        oc[f"{k:.6f}"] = {t: dict(last_price=p, top_bid_price=p - 0.05, top_ask_price=p + 0.05, top_bid_quantity=100,
                                  top_ask_quantity=100, volume=1000 + minute * 25, oi=5000 + minute * 10,
                                  implied_volatility=12.0, greeks=dict(delta=0.5, gamma=0.001, theta=-2.0, vega=1.0))
                          for t, p in (("ce", ce), ("pe", pe))}
    ts = datetime.combine(D, time(15, 0), tzinfo=settings.ist).replace(minute=minute)
    return OptionChainRaw(symbol="NIFTY", expiry=D, fetched_at=ts, spot=spot, raw_payload={"oc": oc, "last_price": spot})


class _FakeOptionRepo:
    def __init__(self, snaps, positions=()):
        self.snaps = snaps
        self.positions = list(positions)

    async def latest_session_date(self, symbol):
        return D if self.snaps else None

    async def list_snapshots(self, symbol, start, end):
        return self.snaps

    async def list_candles(self, symbol, start, end):
        return [RawCandle(symbol="NIFTY", timestamp=s.fetched_at, open=s.spot, high=s.spot, low=s.spot,
                          close=s.spot, volume=0) for s in self.snaps]

    async def list_positions(self, symbol, session_date):
        return self.positions


class _FakeLevelsRepo:
    def __init__(self, row=None):
        self.row = row

    async def levels_at_or_before(self, symbol, as_of):
        return self.row

    async def levels_between(self, symbol, start, end):
        return [self.row] if self.row else []


def _levels():
    return LevelsSnapshot(symbol="NIFTY", as_of=datetime.combine(D, time(15, 0), tzinfo=settings.ist), mode="live",
                          close=ATM, vwap_now=ATM - 25, today_poc=ATM - 40)


def _rising(n=30):
    return [_snap(m, ATM + 2.0 * m) for m in range(n)]


@pytest.mark.asyncio
async def test_unknown_symbol_raises():
    with pytest.raises(SymbolNotFoundError):
        await ScalpDecisionService(_FakeOptionRepo([]), _FakeLevelsRepo()).get_decision("NOPE")


@pytest.mark.asyncio
async def test_no_data_raises():
    with pytest.raises(NoDataAvailableError):
        await ScalpDecisionService(_FakeOptionRepo([]), _FakeLevelsRepo()).get_decision("NIFTY")


@pytest.mark.asyncio
async def test_decision_is_advisory_and_explainable():
    dto = await ScalpDecisionService(_FakeOptionRepo(_rising()), _FakeLevelsRepo(_levels())).get_decision("NIFTY", D)
    assert dto.version == "12C-scalp-decision-v1" and dto.advisory_only is True
    assert dto.decision in ("BUY_CE", "BUY_PE", "WAIT") and dto.confirmation in ("STRONG", "MODERATE", "WEAK", "NONE")
    assert dto.position_state == "NONE" and dto.risk_brake is None
    assert dto.reason and dto.summary and dto.summary["evidence_row"]
    assert dto.trace and dto.trace["decision"] == dto.decision
    # the hypothetical position view rides along, and is advisory only
    assert dto.position_simulation is not None and dto.position_simulation["advisory_only"] is True
    op = dto.position_simulation["open_position"]
    if op:
        assert op["entry_price_type"] == "ASK" and op["notice"].startswith("Hypothetical")


@pytest.mark.asyncio
async def test_user_supplied_position_switches_to_the_brake():
    svc = ScalpDecisionService(_FakeOptionRepo(_rising()), _FakeLevelsRepo(_levels()))
    dto = await svc.get_decision("NIFTY", D, "PE", ATM)
    assert dto.position_state == "BUY_PE" and dto.position_source == "USER_SUPPLIED"
    assert dto.risk_brake["risk_action"] in ("HOLD", "CAUTION", "PREPARE_EXIT", "EXIT")
    assert dto.risk_brake["advisory_only"] is True


@pytest.mark.asyncio
async def test_open_paper_position_takes_precedence_over_a_typed_one():
    pos = PaperPosition(symbol="NIFTY", session_date=D, option_type="CE", strike=ATM, quantity=1, is_open=True,
                        entry_timestamp=datetime.combine(D, time(15, 0), tzinfo=settings.ist), entry_price=40.0,
                        entry_spread_pct=0.5, capital_allocated=1000.0, initial_stop=1.0, initial_target=2.0,
                        current_stop=1.0, current_target=2.0, strategy_version="11d-paper-v1", configuration_hash="x")
    svc = ScalpDecisionService(_FakeOptionRepo(_rising(), [pos]), _FakeLevelsRepo(_levels()))
    dto = await svc.get_decision("NIFTY", D, "PE", ATM + 100)
    assert dto.position_state == "BUY_CE" and dto.position_source == "PAPER_POSITION"
