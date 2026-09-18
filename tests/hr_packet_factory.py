"""Synthetic Dhan v2 feed packets for HR-1 tests (exact binary layouts)."""

import struct
from datetime import date, datetime, time

from config.settings import IST
from hr_capture.protocol import CODE_BY_SEGMENT
from hr_capture.timeutil import dt_to_ns
from hr_capture.universe import FUTIDX, INDEX, OPTIDX, HRInstrument, ResolvedUniverse

TRADING_DATE = date(2026, 9, 15)


def ns_at(hh: int, mm: int, ss: int = 0, micro: int = 0, d: date = TRADING_DATE) -> int:
    return dt_to_ns(datetime.combine(d, time(hh, mm, ss, micro), tzinfo=IST))


def ticker(segment: str, security_id: int, ltp: float, ltt: int = 0) -> bytes:
    return struct.pack("<BHBIfI", 2, 16, CODE_BY_SEGMENT[segment], security_id, ltp, ltt)


def prev_close(segment: str, security_id: int, close: float, prev_oi: int = 0) -> bytes:
    return struct.pack("<BHBIfI", 6, 16, CODE_BY_SEGMENT[segment], security_id, close, prev_oi)


def quote(segment: str, security_id: int, ltp: float, volume: int = 0, ltt: int = 0, ltq: int = 0,
          avg: float = 0.0, sell: int = 0, buy: int = 0, o: float = 0.0, c: float = 0.0, h: float = 0.0,
          low: float = 0.0) -> bytes:
    return struct.pack("<BHBIfHIfIIIffff", 4, 50, CODE_BY_SEGMENT[segment], security_id, ltp, ltq, ltt, avg,
                       volume, sell, buy, o, c, h, low)


def oi_packet(segment: str, security_id: int, oi: int) -> bytes:
    return struct.pack("<BHBII", 5, 12, CODE_BY_SEGMENT[segment], security_id, oi)


def status_packet() -> bytes:
    return struct.pack("<BHBI", 7, 8, 0, 0)


def disconnect_packet(code: int) -> bytes:
    return struct.pack("<BHBIH", 50, 10, 0, 0, code)


def full(segment: str, security_id: int, ltp: float, volume: int = 0, oi: int = 0, ltt: int = 0, ltq: int = 0,
         bid: float = 0.0, ask: float = 0.0, bid_qty: int = 0, ask_qty: int = 0, levels=None,
         avg: float = 0.0, sell: int = 0, buy: int = 0) -> bytes:
    if levels is None:
        levels = [(bid_qty, ask_qty, 1, 1, bid, ask)] + [(0, 0, 0, 0, 0.0, 0.0)] * 4
    depth = b"".join(struct.pack("<IIHHff", *level) for level in levels)
    return struct.pack("<BHBIfHIfIIIIIIffff100s", 8, 162, CODE_BY_SEGMENT[segment], security_id, ltp, ltq, ltt, avg,
                       volume, sell, buy, oi, oi, oi, 0.0, 0.0, 0.0, 0.0, depth)


def make_universe(symbol: str = "NIFTY", atm: float = 23400.0, step: float = 50.0, band: int = 5,
                  index_id: int = 13, fut_id: int = 70000, first_option_id: int = 80000,
                  fno_segment: str = "NSE_FNO") -> ResolvedUniverse:
    instruments = [
        HRInstrument(symbol, "IDX_I", index_id, INDEX, "QUOTE", "SCRIP_MASTER", trading_symbol=symbol),
        HRInstrument(symbol, fno_segment, fut_id, FUTIDX, "FULL", "SCRIP_MASTER", expiry=date(2026, 9, 29)),
    ]
    sid = first_option_id
    for offset in range(-band, band + 1):
        for option_type in ("CE", "PE"):
            instruments.append(HRInstrument(symbol, fno_segment, sid, OPTIDX, "FULL", "OPTION_CHAIN_RAW",
                                            expiry=TRADING_DATE, strike=atm + offset * step,
                                            option_type=option_type, atm_offset=offset))
            sid += 1
    return ResolvedUniverse(symbol, instruments, atm, atm + 3.0, TRADING_DATE, step, [])


def option_id(universe: ResolvedUniverse, offset: int, option_type: str) -> int:
    return next(i.security_id for i in universe.options if i.atm_offset == offset and i.option_type == option_type)


class ListWriter:
    """In-memory writer double capturing every queued row."""

    def __init__(self):
        self.rows: dict[str, list[dict]] = {}

    def put(self, table, row):
        self.rows.setdefault(table, []).append(row)

    def put_many(self, rows_by_table):
        for table, rows in rows_by_table.items():
            for row in rows:
                self.put(table, row)

    def summary(self):
        return {table: len(rows) for table, rows in self.rows.items()}
