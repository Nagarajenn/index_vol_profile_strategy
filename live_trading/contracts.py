"""Resolve a (symbol, expiry, strike, CE/PE) into the exact tradeable contract.

Everything comes from the Dhan scrip master cache the project already downloads. Nothing
is hard-coded and nothing is inferred: if the contract cannot be resolved unambiguously the
caller is told UNKNOWN and no order is built. A wrong security id is a wrong trade.
"""

import csv
import time
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from config.instruments import INSTRUMENTS

ROOT = Path(__file__).resolve().parent.parent
SCRIP_MASTER = ROOT / "data" / "cache" / "scrip_master.csv"

MAX_SCRIP_AGE_HOURS = 30.0
"""The pipeline refreshes the scrip master daily. Beyond this the contract set may no longer
match what is tradeable -- expiries roll and strikes are added -- so resolution refuses rather
than risking a stale security id. 30 hours tolerates a late refresh without tolerating a
missed one."""


@dataclass(frozen=True)
class Contract:
    symbol: str
    expiry: str
    strike: float
    option_type: str
    security_id: str
    trading_symbol: str
    custom_symbol: str
    exchange_segment: str
    lot_size: int
    tick_size: float

    @property
    def label(self) -> str:
        return f"{self.symbol} {self.strike:g} {self.option_type} {self.expiry}"


def scrip_master_age_hours() -> float | None:
    if not SCRIP_MASTER.exists():
        return None
    return (time.time() - SCRIP_MASTER.stat().st_mtime) / 3600.0


@lru_cache(maxsize=8)
def _index(symbol: str, _mtime: float) -> dict:
    """(expiry, strike, option_type) -> row, for one symbol's OPTIDX contracts.

    Keyed on the file's mtime as well as the symbol, so a mid-run refresh of the scrip master
    invalidates the parsed index instead of being silently ignored."""
    out: dict = {}
    if not SCRIP_MASTER.exists():
        return out
    prefix = symbol.upper() + "-"
    with open(SCRIP_MASTER, encoding="utf-8", errors="ignore") as f:
        for row in csv.DictReader(f):
            if row.get("SEM_INSTRUMENT_NAME") != "OPTIDX":
                continue
            if not (row.get("SEM_TRADING_SYMBOL") or "").upper().startswith(prefix):
                continue
            try:
                key = ((row.get("SEM_EXPIRY_DATE") or "")[:10], float(row["SEM_STRIKE_PRICE"]),
                       (row.get("SEM_OPTION_TYPE") or "").upper())
            except (TypeError, ValueError, KeyError):
                continue
            out.setdefault(key, []).append(row)
    return out


def resolve(symbol: str, expiry, strike: float, option_type: str) -> tuple[Contract | None, str]:
    """(contract, reason). contract is None whenever anything is ambiguous or missing."""
    inst = INSTRUMENTS.get(symbol.upper())
    if not inst:
        return None, f"UNKNOWN: {symbol} is not a configured instrument"
    age = scrip_master_age_hours()
    if age is None:
        return None, "UNKNOWN: scrip master cache is not available"
    if age > MAX_SCRIP_AGE_HOURS:
        return None, (f"UNKNOWN: scrip master is {age:.1f}h old (max {MAX_SCRIP_AGE_HOURS:.0f}h) -- "
                      f"contracts may have rolled; refusing rather than using a stale security id")
    rows = _index(symbol.upper(), SCRIP_MASTER.stat().st_mtime).get(
        (str(expiry)[:10], float(strike), option_type.upper()))
    if not rows:
        return None, f"UNKNOWN: no {symbol} {strike:g} {option_type} contract expiring {expiry} in the scrip master"
    if len(rows) > 1:
        return None, f"UNKNOWN: {len(rows)} scrip-master rows match {symbol} {strike:g} {option_type} {expiry}"
    r = rows[0]
    try:
        lot = int(float(r["SEM_LOT_UNITS"]))
        tick = float(r.get("SEM_TICK_SIZE") or 0) / 100.0      # scrip master publishes paise
    except (TypeError, ValueError, KeyError):
        return None, "UNKNOWN: lot size or tick size is not readable for this contract"
    if lot <= 0:
        return None, "UNKNOWN: lot size is not positive"
    return Contract(symbol=symbol.upper(), expiry=str(expiry)[:10], strike=float(strike),
                    option_type=option_type.upper(), security_id=str(r["SEM_SMST_SECURITY_ID"]),
                    trading_symbol=r.get("SEM_TRADING_SYMBOL", ""), custom_symbol=r.get("SEM_CUSTOM_SYMBOL", ""),
                    exchange_segment=inst["fno_exchange_segment"], lot_size=lot,
                    tick_size=tick or 0.05), "OK"


def limit_price(ask: float, tick: float, ticks_through: int) -> float:
    """A marketable limit: ask + N ticks, rounded to the tick grid. Never a market order --
    in a spread blowout an unfilled order is the correct outcome."""
    t = tick or 0.05
    return round(round((ask + ticks_through * t) / t) * t, 2)
