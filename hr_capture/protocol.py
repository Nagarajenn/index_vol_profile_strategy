"""Dhan v2 market-feed binary protocol.

Packet layouts mirror dhanhq 2.2.0 ``marketfeed.py`` exactly (verified by
tests/test_hr_protocol.py, which decodes identical bytes with both parsers).
Unlike the SDK, this parser:

* keeps the raw packet bytes and the raw last-trade-time integer;
* never formats numbers into strings;
* tolerates several packets concatenated in one WebSocket message;
* never raises on unknown/short input (it emits an UNKNOWN event instead).

Only market-data request codes exist here. There is no order functionality.
"""

import hashlib
import json
import struct
from dataclasses import dataclass

from hr_capture.config import DISCONNECT_REQUEST_CODE, FEED_WSS, REQUEST_CODES

SEGMENT_BY_CODE = {
    0: "IDX_I", 1: "NSE_EQ", 2: "NSE_FNO", 3: "NSE_CURRENCY",
    4: "BSE_EQ", 5: "MCX_COMM", 7: "BSE_CURRENCY", 8: "BSE_FNO",
}
CODE_BY_SEGMENT = {name: code for code, name in SEGMENT_BY_CODE.items()}

HEADER = struct.Struct("<BHBI")                      # response code, message length, segment, security id
TICKER = struct.Struct("<BHBIfI")                    # 16 bytes
PREV_CLOSE = struct.Struct("<BHBIfI")                # 16 bytes
QUOTE = struct.Struct("<BHBIfHIfIIIffff")            # 50 bytes
OI = struct.Struct("<BHBII")                         # 12 bytes
STATUS = struct.Struct("<BHBI")                      # 8 bytes
FULL = struct.Struct("<BHBIfHIfIIIIIIffff100s")      # 162 bytes
DEPTH_LEVEL = struct.Struct("<IIHHff")               # 20 bytes x 5
DISCONNECT = struct.Struct("<BHBIH")                 # 10 bytes

PACKET_SPECS = {
    2: ("TICKER", TICKER),
    4: ("QUOTE", QUOTE),
    5: ("OI", OI),
    6: ("PREV_CLOSE", PREV_CLOSE),
    7: ("STATUS", STATUS),
    8: ("FULL", FULL),
    50: ("DISCONNECT", DISCONNECT),
}


@dataclass
class FeedEvent:
    packet_type: str
    response_code: int
    exchange_segment: str
    security_id: int
    raw: bytes
    ltp: float | None = None
    ltq: int | None = None
    ltt_epoch: int | None = None
    avg_price: float | None = None
    volume: int | None = None
    total_sell_qty: int | None = None
    total_buy_qty: int | None = None
    oi: int | None = None
    oi_day_high: int | None = None
    oi_day_low: int | None = None
    day_open: float | None = None
    day_close_field: float | None = None
    day_high: float | None = None
    day_low: float | None = None
    prev_close: float | None = None
    prev_oi: int | None = None
    depth: list[dict] | None = None
    disconnect_code: int | None = None

    @property
    def key(self) -> tuple[str, int]:
        return (self.exchange_segment, self.security_id)

    @property
    def payload_hash(self) -> str:
        return hashlib.sha1(self.raw).hexdigest()

    def level1(self) -> dict | None:
        return self.depth[0] if self.depth else None


def _px(value: float) -> float:
    return round(float(value), 2)


def _segment(code: int) -> str:
    return SEGMENT_BY_CODE.get(code, str(code))


def _decode(code: int, chunk: bytes) -> FeedEvent:
    name, layout = PACKET_SPECS[code]
    fields = layout.unpack(chunk[: layout.size])
    base = dict(packet_type=name, response_code=code, exchange_segment=_segment(fields[2]),
                security_id=int(fields[3]), raw=bytes(chunk[: layout.size]))
    if name == "TICKER":
        return FeedEvent(**base, ltp=_px(fields[4]), ltt_epoch=int(fields[5]))
    if name == "PREV_CLOSE":
        return FeedEvent(**base, prev_close=_px(fields[4]), prev_oi=int(fields[5]))
    if name == "QUOTE":
        return FeedEvent(
            **base, ltp=_px(fields[4]), ltq=int(fields[5]), ltt_epoch=int(fields[6]), avg_price=_px(fields[7]),
            volume=int(fields[8]), total_sell_qty=int(fields[9]), total_buy_qty=int(fields[10]),
            day_open=_px(fields[11]), day_close_field=_px(fields[12]), day_high=_px(fields[13]), day_low=_px(fields[14]),
        )
    if name == "OI":
        return FeedEvent(**base, oi=int(fields[4]))
    if name == "STATUS":
        return FeedEvent(**base)
    if name == "DISCONNECT":
        return FeedEvent(**base, disconnect_code=int(fields[4]))
    # FULL
    depth_blob = fields[18]
    depth = []
    for level in range(5):
        bid_qty, ask_qty, bid_orders, ask_orders, bid_price, ask_price = DEPTH_LEVEL.unpack_from(depth_blob, level * DEPTH_LEVEL.size)
        depth.append({
            "level": level + 1, "bid_price": _px(bid_price), "bid_qty": int(bid_qty), "bid_orders": int(bid_orders),
            "ask_price": _px(ask_price), "ask_qty": int(ask_qty), "ask_orders": int(ask_orders),
        })
    return FeedEvent(
        **base, ltp=_px(fields[4]), ltq=int(fields[5]), ltt_epoch=int(fields[6]), avg_price=_px(fields[7]),
        volume=int(fields[8]), total_sell_qty=int(fields[9]), total_buy_qty=int(fields[10]),
        oi=int(fields[11]), oi_day_high=int(fields[12]), oi_day_low=int(fields[13]),
        day_open=_px(fields[14]), day_close_field=_px(fields[15]), day_high=_px(fields[16]), day_low=_px(fields[17]),
        depth=depth,
    )


def parse_message(data: bytes) -> list[FeedEvent]:
    """Decode every packet in one WebSocket binary message. Never raises."""
    events: list[FeedEvent] = []
    data = bytes(data)
    offset = 0
    while len(data) - offset >= 1:
        code = data[offset]
        spec = PACKET_SPECS.get(code)
        remaining = len(data) - offset
        if spec is None or remaining < spec[1].size:
            segment, security_id = "UNKNOWN", 0
            if remaining >= HEADER.size:
                _, _, seg_code, security_id = HEADER.unpack_from(data, offset)
                segment = _segment(seg_code)
            events.append(FeedEvent("UNKNOWN", code, segment, int(security_id), data[offset:]))
            break
        events.append(_decode(code, data[offset: offset + spec[1].size]))
        offset += spec[1].size
    return events


def subscription_messages(instruments: list[tuple[str, int, str]], batch_size: int = 100) -> list[str]:
    """JSON subscription requests, batched like the SDK (<=100 per message).

    ``instruments`` is [(exchange_segment, security_id, mode)] with mode in
    TICKER / QUOTE / FULL."""
    by_mode: dict[int, list[tuple[str, int]]] = {}
    for segment, security_id, mode in instruments:
        by_mode.setdefault(REQUEST_CODES[mode], []).append((segment, int(security_id)))
    messages = []
    for request_code in sorted(by_mode):
        items = by_mode[request_code]
        for start in range(0, len(items), batch_size):
            batch = items[start: start + batch_size]
            messages.append(json.dumps({
                "RequestCode": request_code,
                "InstrumentCount": len(batch),
                "InstrumentList": [{"ExchangeSegment": seg, "SecurityId": str(sid)} for seg, sid in batch],
            }))
    return messages


def disconnect_message() -> str:
    return json.dumps({"RequestCode": DISCONNECT_REQUEST_CODE})


def build_feed_url(client_id: str, access_token: str) -> str:
    return f"{FEED_WSS}?version=2&token={access_token}&clientId={client_id}&authType=2"


def redact_url(url: str) -> str:
    """The access token travels in the query string; never log it."""
    return url.split("?", 1)[0] + "?<redacted>"
