"""Contract quantity from the data the project already has (the Dhan scrip master cache).

Never hard-coded, never invented: when the lot cannot be verified the caller is told
UNKNOWN and monetary values are withheld.
"""

import csv
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIP_MASTER = ROOT / "data" / "cache" / "scrip_master.csv"


@lru_cache(maxsize=8)
def _by_expiry(symbol: str) -> dict:
    if not SCRIP_MASTER.exists():
        return {}
    found: dict[str, set] = {}
    with open(SCRIP_MASTER, encoding="utf-8", errors="ignore") as f:
        for row in csv.DictReader(f):
            if row.get("SEM_INSTRUMENT_NAME") != "OPTIDX":
                continue
            exp = (row.get("SEM_EXPIRY_DATE") or "")[:10]
            if exp and (row.get("SEM_TRADING_SYMBOL") or "").upper().startswith(symbol.upper() + "-"):
                try:
                    found.setdefault(exp, set()).add(int(float(row["SEM_LOT_UNITS"])))
                except (TypeError, ValueError, KeyError):
                    continue
    return found


def lot_size(symbol: str, expiry) -> tuple[int | None, str]:
    """(quantity, source). None means UNKNOWN -- the caller must not fabricate a value."""
    found = _by_expiry(symbol)
    if not found:
        return None, "UNKNOWN: scrip master not available"
    exact = found.get(str(expiry))
    if exact and len(exact) == 1:
        return next(iter(exact)), f"scrip master {symbol} {expiry}"
    later = sorted((e, v) for e, v in found.items() if e > str(expiry) and len(v) == 1)
    if later:
        return next(iter(later[0][1])), f"INFERRED from the {symbol} {later[0][0]} series (expired contract not in the cached scrip master)"
    return None, "UNKNOWN: lot size not verifiable for this contract"
