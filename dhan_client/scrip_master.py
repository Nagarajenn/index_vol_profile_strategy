import logging
import time

import pandas as pd
import requests

from config.instruments import INSTRUMENTS
from config.settings import SCRIP_MASTER_CACHE, SCRIP_MASTER_MAX_AGE_HOURS, SCRIP_MASTER_URL
from dhan_client.exceptions import ScripNotFoundError

logger = logging.getLogger(__name__)

REQUIRED_COLUMNS = {
    "SEM_EXM_EXCH_ID",
    "SEM_SEGMENT",
    "SEM_SMST_SECURITY_ID",
    "SEM_INSTRUMENT_NAME",
    "SEM_TRADING_SYMBOL",
    "SEM_EXCH_INSTRUMENT_TYPE",
}

_cache_df: pd.DataFrame | None = None


def _is_cache_fresh() -> bool:
    if not SCRIP_MASTER_CACHE.exists():
        return False
    age_hours = (time.time() - SCRIP_MASTER_CACHE.stat().st_mtime) / 3600
    return age_hours < SCRIP_MASTER_MAX_AGE_HOURS


def _download() -> pd.DataFrame:
    resp = requests.get(SCRIP_MASTER_URL, timeout=60)
    resp.raise_for_status()
    SCRIP_MASTER_CACHE.write_bytes(resp.content)
    logger.info("Downloaded fresh scrip master (%d bytes)", len(resp.content))
    return pd.read_csv(SCRIP_MASTER_CACHE, low_memory=False)


def load_scrip_master(force_refresh: bool = False) -> pd.DataFrame:
    """Load the Dhan scrip master, using an on-disk cache refreshed daily."""
    global _cache_df
    if _cache_df is not None and not force_refresh:
        return _cache_df

    if not force_refresh and _is_cache_fresh():
        df = pd.read_csv(SCRIP_MASTER_CACHE, low_memory=False)
    else:
        df = _download()

    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        raise ScripNotFoundError(
            f"Scrip master schema changed — missing expected columns: {missing}. "
            f"Actual columns: {list(df.columns)}"
        )

    _cache_df = df
    return df


def resolve_instrument(symbol_key: str) -> dict:
    """Resolve a symbol key (e.g. 'SENSEX', 'NIFTY') to Dhan API identifiers.

    Returns dict with security_id (str), exchange_segment (str, e.g. 'IDX_I'),
    instrument_type (str, e.g. 'INDEX'), plus the static config metadata.
    """
    if symbol_key not in INSTRUMENTS:
        raise ScripNotFoundError(f"Unknown symbol_key '{symbol_key}', expected one of {list(INSTRUMENTS)}")

    meta = INSTRUMENTS[symbol_key]
    df = load_scrip_master()

    matches = df[
        (df["SEM_EXM_EXCH_ID"] == meta["exchange"])
        & (df["SEM_SEGMENT"] == meta["segment"])
        & (df["SEM_EXCH_INSTRUMENT_TYPE"] == meta["instrument_type"])
        & (df["SEM_TRADING_SYMBOL"].astype(str).str.upper() == meta["trading_symbol"].upper())
    ]

    if len(matches) != 1:
        raise ScripNotFoundError(
            f"Expected exactly 1 scrip master row for {symbol_key}, found {len(matches)}. "
            f"Check config/instruments.py matching criteria against the current CSV."
        )

    row = matches.iloc[0]
    return {
        "symbol_key": symbol_key,
        "security_id": str(int(row["SEM_SMST_SECURITY_ID"])),
        "exchange_segment": meta["exchange_segment_api"],
        "instrument_type": meta["instrument_type"],
        "trading_symbol": row["SEM_TRADING_SYMBOL"],
        **meta,
    }
