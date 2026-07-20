import logging
import time
from datetime import date, datetime, timedelta

import pandas as pd

from dhan_client.auth import build_dhan_client
from dhan_client.exceptions import DhanAPIError
from dhan_client.rate_limiter import option_chain_limiter
from dhan_client.scrip_master import resolve_instrument

logger = logging.getLogger(__name__)

_client = None


def get_client():
    global _client
    if _client is None:
        _client = build_dhan_client()
    return _client


def _unwrap(endpoint: str, response: dict) -> dict:
    if response.get("status") != "success":
        raise DhanAPIError(endpoint, response.get("remarks"))
    return response["data"]


def _candles_to_df(payload: dict) -> pd.DataFrame:
    """Dhan returns parallel arrays: open/high/low/close/volume/timestamp[/open_interest]."""
    if not payload or not payload.get("timestamp"):
        return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])
    df = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(payload["timestamp"], unit="s", utc=True).tz_convert("Asia/Kolkata"),
            "open": payload["open"],
            "high": payload["high"],
            "low": payload["low"],
            "close": payload["close"],
            "volume": payload["volume"],
        }
    )
    if "open_interest" in payload and payload["open_interest"]:
        df["open_interest"] = payload["open_interest"]
    return df.sort_values("timestamp").reset_index(drop=True)


def _date_windows(from_date: date, to_date: date, max_chunk_days: int):
    windows = []
    cur = from_date
    while cur <= to_date:
        window_end = min(cur + timedelta(days=max_chunk_days - 1), to_date)
        windows.append((cur, window_end))
        cur = window_end + timedelta(days=1)
    return windows


def fetch_intraday_candles(
    symbol_key: str,
    from_date: date,
    to_date: date,
    interval: int = 1,
    oi: bool = False,
    max_chunk_days: int = 90,
) -> pd.DataFrame:
    """Fetch minute candles for [from_date, to_date] (inclusive), auto-chunking.

    Dhan's own package docstring claims intraday_minute_data only returns
    "last 5 trading days", while the public docs describe a 90-day-per-request
    cap with up to ~5 years of total history. Those disagree, so instead of
    trusting either blindly, we request in `max_chunk_days` windows and, if a
    window comes back covering less than requested, recursively split the
    missing portion into smaller windows (down to 1 day) rather than silently
    dropping data.
    """
    instr = resolve_instrument(symbol_key)
    client = get_client()
    frames = []

    def _fetch_window(w_start: date, w_end: date, depth: int = 0):
        resp = client.intraday_minute_data(
            security_id=instr["security_id"],
            exchange_segment=instr["exchange_segment"],
            instrument_type=instr["instrument_type"],
            from_date=w_start.isoformat(),
            to_date=w_end.isoformat(),
            interval=interval,
            oi=oi,
        )
        data = _unwrap("/charts/intraday", resp)
        df = _candles_to_df(data)
        if df.empty:
            return
        frames.append(df)

        got_start = df["timestamp"].min().date()
        if got_start > w_start and depth < 6:
            # Server gave us less history than asked for this window — recurse
            # on the uncovered earlier portion with a smaller window.
            shortfall_end = got_start - timedelta(days=1)
            if shortfall_end >= w_start:
                sub_chunk = max(1, (w_end - w_start).days // 2)
                for sub_start, sub_end in _date_windows(w_start, shortfall_end, sub_chunk):
                    time.sleep(0.3)
                    _fetch_window(sub_start, sub_end, depth + 1)

    for w_start, w_end in _date_windows(from_date, to_date, max_chunk_days):
        _fetch_window(w_start, w_end)
        time.sleep(0.3)

    if not frames:
        return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])

    combined = pd.concat(frames, ignore_index=True).drop_duplicates(subset="timestamp").sort_values("timestamp")
    combined = combined.reset_index(drop=True)

    actual_start = combined["timestamp"].min().date()
    if actual_start > from_date:
        logger.warning(
            "%s intraday data only available from %s (requested from %s) — gap of %d day(s)",
            symbol_key,
            actual_start,
            from_date,
            (actual_start - from_date).days,
        )
    return combined


def fetch_daily_candles(symbol_key: str, from_date: date, to_date: date, oi: bool = False) -> pd.DataFrame:
    instr = resolve_instrument(symbol_key)
    client = get_client()
    resp = client.historical_daily_data(
        security_id=instr["security_id"],
        exchange_segment=instr["exchange_segment"],
        instrument_type=instr["instrument_type"],
        from_date=from_date.isoformat(),
        to_date=to_date.isoformat(),
        oi=oi,
    )
    data = _unwrap("/charts/historical", resp)
    return _candles_to_df(data)


def fetch_expiry_list(symbol_key: str) -> list[str]:
    instr = resolve_instrument(symbol_key)
    client = get_client()
    option_chain_limiter.wait()
    resp = client.expiry_list(
        under_security_id=int(instr["security_id"]),
        under_exchange_segment=instr["exchange_segment"],
    )
    data = _unwrap("/optionchain/expirylist", resp)
    return data if isinstance(data, list) else data.get("data", [])


def fetch_option_chain(symbol_key: str, expiry: str) -> dict:
    """Raw option chain payload for one expiry: {"last_price": ..., "oc": {strike: {"ce": {...}, "pe": {...}}}}."""
    instr = resolve_instrument(symbol_key)
    client = get_client()
    option_chain_limiter.wait()
    resp = client.option_chain(
        under_security_id=int(instr["security_id"]),
        under_exchange_segment=instr["exchange_segment"],
        expiry=expiry,
    )
    payload = _unwrap("/optionchain", resp)
    # Dhan wraps this endpoint's body in its own {"data": ..., "status": "success"}
    # envelope on top of the dhanhq client's own status/data wrapper.
    return payload.get("data", payload) if isinstance(payload, dict) else payload
