"""Instrument universe resolution (index + current futures + ATM +/- band).

Nothing is hard-coded: strikes, expiry and security IDs come from the most
recent ``option_chain_raw`` row already captured by the existing pipeline
(read-only SELECT, no Dhan call), with the locally cached scrip master as a
read-only fallback. HR never downloads the scrip master and never calls the
option-chain REST endpoint, so it cannot interfere with the live loop's
rate limit.
"""

from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from config.instruments import INSTRUMENTS

INDEX = "INDEX"
FUTIDX = "FUTIDX"
OPTIDX = "OPTIDX"

SRC_CHAIN = "OPTION_CHAIN_RAW"
SRC_SCRIP = "SCRIP_MASTER"

SCRIP_COLUMNS = [
    "SEM_EXM_EXCH_ID", "SEM_SEGMENT", "SEM_SMST_SECURITY_ID", "SEM_INSTRUMENT_NAME", "SEM_TRADING_SYMBOL",
    "SEM_EXPIRY_DATE", "SEM_STRIKE_PRICE", "SEM_OPTION_TYPE", "SEM_EXCH_INSTRUMENT_TYPE",
]


@dataclass
class HRInstrument:
    symbol: str
    exchange_segment: str
    security_id: int
    instrument_type: str
    subscribe_mode: str
    id_source: str
    trading_symbol: str | None = None
    expiry: date | None = None
    strike: float | None = None
    option_type: str | None = None
    atm_offset: int | None = None

    @property
    def key(self) -> tuple[str, int]:
        return (self.exchange_segment, int(self.security_id))

    def as_dict(self) -> dict:
        out = asdict(self)
        out["expiry"] = self.expiry.isoformat() if self.expiry else None
        return out


@dataclass
class ResolvedUniverse:
    symbol: str
    instruments: list[HRInstrument]
    band_atm_strike: float | None
    reference_spot: float | None
    expiry: date | None
    strike_step: float | None
    issues: list[str] = field(default_factory=list)

    @property
    def options(self) -> list[HRInstrument]:
        return [i for i in self.instruments if i.instrument_type == OPTIDX]


# ---------------------------------------------------------------- pure helpers

def infer_strike_step(strikes: list[float]) -> float | None:
    ordered = sorted(set(float(s) for s in strikes))
    diffs = [round(b - a, 6) for a, b in zip(ordered, ordered[1:]) if b > a]
    if not diffs:
        return None
    return Counter(diffs).most_common(1)[0][0]


def select_band(strikes: list[float], spot: float, band: int) -> tuple[float, list[tuple[int, float]]]:
    """ATM = listed strike nearest the reference spot; the band is taken by
    position in the actual strike list (no step arithmetic, no hard-coded
    strike values). Returns (atm_strike, [(offset, strike), ...])."""
    ordered = sorted(set(float(s) for s in strikes))
    if not ordered:
        raise ValueError("no strikes available")
    atm_index = min(range(len(ordered)), key=lambda i: (abs(ordered[i] - spot), ordered[i]))
    lo, hi = max(0, atm_index - band), min(len(ordered) - 1, atm_index + band)
    return ordered[atm_index], [(i - atm_index, ordered[i]) for i in range(lo, hi + 1)]


def _expiry_date(value) -> date | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    return pd.to_datetime(str(value)).date()


def _scrip_symbol_rows(scrip: pd.DataFrame, symbol: str, instrument_name: str) -> pd.DataFrame:
    meta = INSTRUMENTS[symbol]
    return scrip[
        (scrip["SEM_EXM_EXCH_ID"] == meta["exchange"])
        & (scrip["SEM_INSTRUMENT_NAME"] == instrument_name)
        & (scrip["SEM_TRADING_SYMBOL"].astype(str).str.startswith(f"{meta['trading_symbol']}-"))
    ]


def index_from_scrip(symbol: str, scrip: pd.DataFrame, mode: str) -> HRInstrument | None:
    """Same matching criteria as dhan_client.scrip_master.resolve_instrument
    (reimplemented read-only so HR never triggers that module's download)."""
    meta = INSTRUMENTS[symbol]
    rows = scrip[
        (scrip["SEM_EXM_EXCH_ID"] == meta["exchange"])
        & (scrip["SEM_SEGMENT"] == meta["segment"])
        & (scrip["SEM_EXCH_INSTRUMENT_TYPE"] == meta["instrument_type"])
        & (scrip["SEM_TRADING_SYMBOL"].astype(str).str.upper() == meta["trading_symbol"].upper())
    ]
    if len(rows) != 1:
        return None
    row = rows.iloc[0]
    return HRInstrument(symbol, meta["exchange_segment_api"], int(row["SEM_SMST_SECURITY_ID"]), INDEX, mode, SRC_SCRIP,
                        trading_symbol=str(row["SEM_TRADING_SYMBOL"]))


def futures_from_scrip(symbol: str, scrip: pd.DataFrame, trading_date: date, mode: str) -> HRInstrument | None:
    """Nearest-expiry index future whose expiry is on or after the trading date."""
    rows = _scrip_symbol_rows(scrip, symbol, FUTIDX)
    rows = rows[rows["SEM_TRADING_SYMBOL"].astype(str).str.endswith("-FUT")]
    candidates = [(_expiry_date(r["SEM_EXPIRY_DATE"]), r) for _, r in rows.iterrows()]
    candidates = [(e, r) for e, r in candidates if e is not None and e >= trading_date]
    if not candidates:
        return None
    expiry, row = min(candidates, key=lambda er: er[0])
    return HRInstrument(symbol, INSTRUMENTS[symbol]["fno_exchange_segment"], int(row["SEM_SMST_SECURITY_ID"]), FUTIDX,
                        mode, SRC_SCRIP, trading_symbol=str(row["SEM_TRADING_SYMBOL"]), expiry=expiry)


def _scrip_option_id(scrip: pd.DataFrame | None, symbol: str, expiry: date, strike: float, option_type: str) -> tuple[int, str] | None:
    if scrip is None:
        return None
    rows = _scrip_symbol_rows(scrip, symbol, OPTIDX)
    rows = rows[(rows["SEM_OPTION_TYPE"] == option_type) & (rows["SEM_STRIKE_PRICE"].astype(float) == float(strike))]
    for _, row in rows.iterrows():
        if _expiry_date(row["SEM_EXPIRY_DATE"]) == expiry:
            return int(row["SEM_SMST_SECURITY_ID"]), str(row["SEM_TRADING_SYMBOL"])
    return None


def options_from_chain(symbol: str, chain_row: dict, band: int, mode: str,
                       scrip: pd.DataFrame | None = None) -> tuple[list[HRInstrument], float, float, date, float | None, list[str]]:
    """ATM +/- band CE/PE from an option_chain_raw row."""
    payload = chain_row["raw_payload"]
    expiry = _expiry_date(chain_row.get("expiry") or payload.get("expiry"))
    spot = payload.get("last_price") or chain_row.get("spot")
    if spot is None:
        raise ValueError("option chain row has no spot")
    oc = payload.get("oc") or {}
    strikes = [float(k) for k in oc]
    atm, band_strikes = select_band(strikes, float(spot), band)
    step = infer_strike_step(strikes)
    segment = INSTRUMENTS[symbol]["fno_exchange_segment"]
    by_strike = {float(k): v for k, v in oc.items()}
    issues: list[str] = []
    if len(band_strikes) < 2 * band + 1:
        issues.append(f"BAND_TRUNCATED: {len(band_strikes)} of {2 * band + 1} strikes available")

    instruments = []
    for offset, strike in band_strikes:
        for leg, option_type in (("ce", "CE"), ("pe", "PE")):
            security_id = (by_strike.get(strike, {}).get(leg) or {}).get("security_id")
            source, trading_symbol = SRC_CHAIN, None
            if not security_id:
                found = _scrip_option_id(scrip, symbol, expiry, strike, option_type)
                if found is None:
                    issues.append(f"MISSING_SECURITY_ID: {strike:g} {option_type}")
                    continue
                security_id, trading_symbol = found
                source = SRC_SCRIP
            instruments.append(HRInstrument(symbol, segment, int(security_id), OPTIDX, mode, source,
                                            trading_symbol=trading_symbol, expiry=expiry, strike=strike,
                                            option_type=option_type, atm_offset=offset))
    return instruments, atm, float(spot), expiry, step, issues


def options_from_scrip(symbol: str, scrip: pd.DataFrame, trading_date: date, spot: float, band: int,
                       mode: str) -> tuple[list[HRInstrument], float, date, float | None, list[str]]:
    """Fallback when no option_chain_raw row exists: nearest expiry on/after
    the trading date, strikes around the latest captured spot."""
    rows = _scrip_symbol_rows(scrip, symbol, OPTIDX).copy()
    rows["_expiry"] = rows["SEM_EXPIRY_DATE"].map(_expiry_date)
    rows = rows[rows["_expiry"].map(lambda e: e is not None and e >= trading_date)]
    if rows.empty:
        raise ValueError(f"no {symbol} OPTIDX rows on/after {trading_date} in scrip master")
    expiry = min(rows["_expiry"])
    rows = rows[rows["_expiry"] == expiry]
    strikes = rows["SEM_STRIKE_PRICE"].astype(float).tolist()
    atm, band_strikes = select_band(strikes, spot, band)
    segment = INSTRUMENTS[symbol]["fno_exchange_segment"]
    instruments, issues = [], ["OPTIONS_FROM_SCRIP_MASTER_FALLBACK"]
    for offset, strike in band_strikes:
        for option_type in ("CE", "PE"):
            match = rows[(rows["SEM_STRIKE_PRICE"].astype(float) == strike) & (rows["SEM_OPTION_TYPE"] == option_type)]
            if match.empty:
                issues.append(f"MISSING_SECURITY_ID: {strike:g} {option_type}")
                continue
            row = match.iloc[0]
            instruments.append(HRInstrument(symbol, segment, int(row["SEM_SMST_SECURITY_ID"]), OPTIDX, mode, SRC_SCRIP,
                                            trading_symbol=str(row["SEM_TRADING_SYMBOL"]), expiry=expiry, strike=strike,
                                            option_type=option_type, atm_offset=offset))
    return instruments, atm, expiry, infer_strike_step(strikes), issues


def resolve_symbol_universe(symbol: str, trading_date: date, chain_row: dict | None, fallback_spot: float | None,
                            scrip: pd.DataFrame | None, band: int, index_mode: str, futures_mode: str,
                            option_mode: str) -> ResolvedUniverse:
    instruments: list[HRInstrument] = []
    issues: list[str] = []

    index = index_from_scrip(symbol, scrip, index_mode) if scrip is not None else None
    if index is None:
        issues.append("INDEX_UNRESOLVED")
    else:
        instruments.append(index)

    futures = futures_from_scrip(symbol, scrip, trading_date, futures_mode) if scrip is not None else None
    if futures is None:
        issues.append("FUTURES_UNRESOLVED")
    else:
        instruments.append(futures)

    atm = spot = expiry = step = None
    if chain_row is not None:
        opts, atm, spot, expiry, step, opt_issues = options_from_chain(symbol, chain_row, band, option_mode, scrip)
    elif scrip is not None and fallback_spot is not None:
        opts, atm, expiry, step, opt_issues = options_from_scrip(symbol, scrip, trading_date, fallback_spot, band, option_mode)
        spot = fallback_spot
    else:
        opts, opt_issues = [], ["OPTIONS_UNRESOLVED: no option_chain_raw row and no scrip-master fallback"]
    instruments.extend(opts)
    issues.extend(opt_issues)
    return ResolvedUniverse(symbol, instruments, atm, spot, expiry, step, issues)


# ---------------------------------------------------------------- read-only loaders

def load_latest_chain_row(conn, symbol: str, day_start: datetime, at_or_before: datetime) -> dict | None:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT fetched_at, expiry, spot, raw_payload FROM option_chain_raw "
            "WHERE symbol = %s AND fetched_at >= %s AND fetched_at <= %s ORDER BY fetched_at DESC LIMIT 1",
            (symbol, day_start, at_or_before),
        )
        row = cur.fetchone()
    if row is None:
        return None
    return {"fetched_at": row[0], "expiry": row[1], "spot": row[2], "raw_payload": row[3]}


def load_latest_spot(conn, symbol: str, day_start: datetime, at_or_before: datetime) -> float | None:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT close FROM raw_candles WHERE symbol = %s AND timestamp >= %s AND timestamp <= %s "
            "ORDER BY timestamp DESC LIMIT 1",
            (symbol, day_start, at_or_before),
        )
        row = cur.fetchone()
    return float(row[0]) if row else None


def load_scrip_frame(path: Path) -> pd.DataFrame | None:
    """Reads the cached CSV only. Returns None if it is absent -- HR never
    downloads it (the live loop owns that)."""
    if not path.exists():
        return None
    return pd.read_csv(path, usecols=SCRIP_COLUMNS, low_memory=False)
