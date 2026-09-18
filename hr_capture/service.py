"""Capture-session orchestration.

One run == one ``hr_capture_sessions`` row. The service wires the feed, the
aggregator, the recorder and the writer together, enforces the persistence
window (window_start <= receive_ts < window_end) and closes the session
with a health/quality summary. Every handler is contained: nothing raised
while processing market data can escape into the event loop, and the
process has no connection to the live loop or the paper agent.
"""

import asyncio
import logging
import time
import uuid
from collections import defaultdict
from datetime import date, datetime

from psycopg.types.json import Jsonb

from config.settings import IST
from hr_capture import db as hr_db
from hr_capture.aggregator import Aggregator
from hr_capture.config import HR_PIPELINE_VERSION, IMPLIED_SPOT_METHOD, PARSER_VERSION, HRConfig
from hr_capture.feed import STATUS_FAILED_AUTH, STATUS_FAILED_CONNECTION, FeedClient
from hr_capture.protocol import parse_message
from hr_capture.timeutil import (
    LTT_UNDETERMINED, NS_PER_S, ist_ns, ltt_offset_seconds, ltt_to_datetime, ns_to_ist,
)
from hr_capture.universe import ResolvedUniverse

logger = logging.getLogger(__name__)

MODE_LIVE = "LIVE"
MODE_DRY_RUN = "DRY_RUN"
MODE_REPLAY = "REPLAY"


def raw_tick_row(session_id: str, seq: int, inst, receive_ns: int, ev, ltt_convention: str) -> dict:
    level1 = ev.level1()
    return {
        "session_id": session_id, "packet_seq": seq, "symbol": inst.symbol, "exchange_segment": inst.exchange_segment,
        "security_id": inst.security_id, "instrument_type": inst.instrument_type, "expiry": inst.expiry,
        "strike": inst.strike, "option_type": inst.option_type, "packet_type": ev.packet_type,
        "ltt_epoch": ev.ltt_epoch, "exchange_ts": ltt_to_datetime(ev.ltt_epoch, ltt_convention),
        "receive_ts": ns_to_ist(receive_ns), "receive_ns": receive_ns, "ltp": ev.ltp, "ltq": ev.ltq,
        "avg_price": ev.avg_price, "volume": ev.volume, "oi": ev.oi, "oi_day_high": ev.oi_day_high,
        "oi_day_low": ev.oi_day_low, "total_buy_qty": ev.total_buy_qty, "total_sell_qty": ev.total_sell_qty,
        "day_open": ev.day_open, "day_high": ev.day_high, "day_low": ev.day_low,
        "day_close_field": ev.day_close_field, "prev_close": ev.prev_close, "prev_oi": ev.prev_oi,
        "bid_price_1": level1["bid_price"] if level1 else None, "bid_qty_1": level1["bid_qty"] if level1 else None,
        "bid_orders_1": level1["bid_orders"] if level1 else None, "ask_price_1": level1["ask_price"] if level1 else None,
        "ask_qty_1": level1["ask_qty"] if level1 else None, "ask_orders_1": level1["ask_orders"] if level1 else None,
        "depth": ev.depth, "payload_hash": ev.payload_hash, "raw_packet": ev.raw,
    }


class CaptureSession:
    """Message handling + aggregation for one session. Transport-agnostic, so
    live capture, replay and tests all run exactly the same code."""

    def __init__(self, config: HRConfig, trading_date: date, universes: dict[str, ResolvedUniverse],
                 writer, recorder=None, mode: str = MODE_LIVE, session_id: str | None = None,
                 source: str = "WEBSOCKET"):
        self.config = config
        self.trading_date = trading_date
        self.universes = universes
        self.writer = writer
        self.recorder = recorder
        self.mode = mode
        self.session_id = session_id or str(uuid.uuid4())
        self.instruments = [inst for u in universes.values() for inst in u.instruments]
        self.meta = {inst.key: inst for inst in self.instruments}
        self.aggregator = Aggregator(config, trading_date, self.instruments,
                                     {s: u.band_atm_strike for s, u in universes.items()}, self.session_id, source)
        self.start_ns = ist_ns(trading_date, config.window_start)
        self.end_ns = ist_ns(trading_date, config.window_end)
        self.seq = 0
        self._last_hash: dict[tuple, str] = {}
        self._disconnected_since: int | None = None
        self.status_events: list[dict] = []
        self.counts = {
            "messages": 0, "messages_in_window": 0, "packets": 0, "packets_in_window": 0, "ticks_queued": 0,
            "duplicates_dropped": 0, "parse_errors": 0, "unknown_packets": 0, "unregistered_packets": 0,
            "status_packets": 0, "reconnects": 0, "gaps": 0, "errors": 0, "handler_errors": 0,
        }
        self.packets_by_instrument: dict[tuple, int] = defaultdict(int)
        self.last_packet_ns_by_instrument: dict[tuple, int] = {}
        self.packet_types: dict[str, int] = defaultdict(int)
        self.gap_intervals: list[dict] = []

    # ---------------------------------------------------------------- session rows

    def session_row(self, started_at: datetime) -> dict:
        return {
            "session_id": self.session_id, "trading_date": self.trading_date, "mode": self.mode,
            "pipeline_version": HR_PIPELINE_VERSION, "parser_version": PARSER_VERSION,
            "implied_spot_method": IMPLIED_SPOT_METHOD,
            "window_start": ns_to_ist(self.start_ns), "window_end": ns_to_ist(self.end_ns),
            "started_at": started_at, "status": "RUNNING", "instruments_expected": len(self.instruments),
            "config": {"hr": self.config.as_json(),
                       "universe": {s: {"band_atm_strike": u.band_atm_strike, "reference_spot": u.reference_spot,
                                        "expiry": u.expiry.isoformat() if u.expiry else None,
                                        "strike_step": u.strike_step, "issues": u.issues}
                                    for s, u in self.universes.items()}},
        }

    def instrument_rows(self) -> list[dict]:
        rows = []
        for symbol, universe in self.universes.items():
            for inst in universe.instruments:
                rows.append({
                    "session_id": self.session_id, "symbol": inst.symbol, "exchange_segment": inst.exchange_segment,
                    "security_id": inst.security_id, "instrument_type": inst.instrument_type,
                    "trading_symbol": inst.trading_symbol, "expiry": inst.expiry, "strike": inst.strike,
                    "option_type": inst.option_type, "atm_offset": inst.atm_offset,
                    "band_atm_strike": universe.band_atm_strike, "reference_spot": universe.reference_spot,
                    "subscribe_mode": inst.subscribe_mode, "id_source": inst.id_source,
                })
        return rows

    def event_row(self, event_type: str, event_ns: int, detail: dict, symbol: str | None = None) -> dict:
        return {"session_id": self.session_id, "event_ts": ns_to_ist(event_ns), "event_type": event_type,
                "symbol": symbol, "detail": detail}

    # ---------------------------------------------------------------- inbound

    def handle_message(self, receive_ns: int, data: bytes) -> None:
        try:
            self._handle_message(receive_ns, data)
        except Exception:
            self.counts["handler_errors"] += 1
            logger.exception("HR message handling failed (contained)")

    def _handle_message(self, receive_ns: int, data: bytes) -> None:
        self.counts["messages"] += 1
        in_window = self.start_ns <= receive_ns < self.end_ns
        if in_window:
            self.counts["messages_in_window"] += 1
            if self.recorder is not None:
                self.recorder.append(receive_ns, data)
        try:
            events = parse_message(data)
        except Exception:
            self.counts["parse_errors"] += 1
            return
        for ev in events:
            self.counts["packets"] += 1
            self.packet_types[ev.packet_type] += 1
            if ev.packet_type == "UNKNOWN":
                self.counts["unknown_packets"] += 1
                continue
            if ev.packet_type == "STATUS":
                self.counts["status_packets"] += 1
                if len(self.status_events) < 20:
                    self.status_events.append({"receive_ts": ns_to_ist(receive_ns).isoformat(),
                                               "raw_hex": ev.raw.hex(), "segment": ev.exchange_segment})
                continue
            if ev.packet_type == "DISCONNECT":
                continue
            inst = self.meta.get(ev.key)
            if inst is None:
                self.counts["unregistered_packets"] += 1
                continue
            self.packets_by_instrument[ev.key] += 1
            self.last_packet_ns_by_instrument[ev.key] = receive_ns

            dedupe_key = (ev.key, ev.packet_type)
            payload_hash = ev.payload_hash
            is_duplicate = self._last_hash.get(dedupe_key) == payload_hash
            self._last_hash[dedupe_key] = payload_hash

            self.aggregator.ingest(receive_ns, ev, is_duplicate)
            if not in_window:
                continue
            self.counts["packets_in_window"] += 1
            if is_duplicate:
                self.counts["duplicates_dropped"] += 1
                continue
            self.seq += 1
            self.writer.put("hr_raw_ticks", raw_tick_row(self.session_id, self.seq, inst, receive_ns, ev,
                                                         self.aggregator.ltt_convention))
            self.counts["ticks_queued"] += 1

    def handle_feed_event(self, event_type: str, event_ns: int, detail: dict) -> None:
        try:
            if event_type == "DISCONNECT" and self._disconnected_since is None:
                self._disconnected_since = event_ns
                self.aggregator.note_disconnect(event_ns)
                self.counts["gaps"] += 1
                self.writer.put("hr_capture_events", self.event_row("GAP_START", event_ns, detail))
            elif event_type == "SUBSCRIBED" and self._disconnected_since is not None:
                self.aggregator.note_reconnect(event_ns)
                self.counts["reconnects"] += 1
                self.gap_intervals.append({"start": ns_to_ist(self._disconnected_since).isoformat(),
                                           "end": ns_to_ist(event_ns).isoformat(),
                                           "seconds": round((event_ns - self._disconnected_since) / NS_PER_S, 3)})
                self.writer.put("hr_capture_events", self.event_row("GAP_END", event_ns, self.gap_intervals[-1]))
                self._disconnected_since = None
            if event_type in ("AUTH_FAIL", "CONNECTION_FAIL", "SERVER_DISCONNECT"):
                self.counts["errors"] += 1
            self.writer.put("hr_capture_events", self.event_row(event_type, event_ns, detail))
        except Exception:
            self.counts["handler_errors"] += 1
            logger.exception("HR feed-event handling failed (contained)")

    def finalize_due(self, now_ns: int) -> None:
        try:
            self.writer.put_many(self.aggregator.finalize_due(now_ns))
        except Exception:
            self.counts["handler_errors"] += 1
            logger.exception("HR aggregation failed (contained)")

    def finalize_all(self) -> None:
        try:
            if self._disconnected_since is not None:
                self.aggregator.note_reconnect(self.end_ns)
            self.writer.put_many(self.aggregator.finalize_all())
        except Exception:
            self.counts["handler_errors"] += 1
            logger.exception("HR final aggregation failed (contained)")

    # ---------------------------------------------------------------- summary

    def quality_summary(self, feed_status: str | None) -> dict:
        agg = self.aggregator.stats
        expected = set(self.meta)
        received = {k for k, n in self.packets_by_instrument.items() if n > 0}
        cutoff_ns = self.end_ns - int(self.config.disappeared_after_s * NS_PER_S)
        disappeared = [
            {"instrument": f"{k[0]}:{k[1]}", "last_packet": ns_to_ist(ns).isoformat()}
            for k, ns in self.last_packet_ns_by_instrument.items() if ns < cutoff_ns
        ]
        writer = self.writer.summary() if hasattr(self.writer, "summary") else {}
        return {
            "feed_status": feed_status,
            "counts": dict(self.counts),
            "packet_types": dict(self.packet_types),
            "instruments_expected": len(expected),
            "instruments_received": len(received),
            "instruments_never_received": sorted(f"{k[0]}:{k[1]}" for k in expected - received),
            "instruments_disappeared_before_window_end": disappeared,
            "gap_intervals": self.gap_intervals,
            "gap_buckets": agg["gap_buckets"],
            "late_events": agg["late_events"],
            "no_update_bucket_counts": dict(agg["no_update_buckets"]),
            "missing_bid_ask_bucket_counts": dict(agg["missing_bid_ask_buckets"]),
            "crossed_bucket_counts": dict(agg["crossed_buckets"]),
            "stale_quote_bucket_counts": dict(agg["stale_quote_buckets"]),
            "market_state_changes": agg["state_changes"],
            "band_edges": agg.get("band_edges", []),
            "ltt_convention": self.aggregator.ltt_convention,
            "status_packets_sample": self.status_events,
            "writer": writer,
            "recorder": ({"path": str(self.recorder.path), "records": self.recorder.records,
                          "bytes": self.recorder.bytes_written, "errors": self.recorder.errors}
                         if self.recorder is not None else None),
        }

    def final_status(self, feed_status: str | None) -> str:
        if feed_status == STATUS_FAILED_AUTH:
            return "FAILED_AUTH"
        if feed_status == STATUS_FAILED_CONNECTION:
            return "FAILED_CONNECTION"
        received = sum(1 for n in self.packets_by_instrument.values() if n > 0)
        if self.counts["messages"] == 0:
            return "FAILED"
        if self.aggregator.stats["gap_buckets"] or received < len(self.meta):
            return "COMPLETED_WITH_GAPS"
        return "COMPLETED"

    def finalize_session_params(self, feed_status: str | None) -> tuple:
        summary = self.quality_summary(feed_status)
        return (
            datetime.now(IST), self.final_status(feed_status), summary["instruments_received"], self.counts["packets"],
            self.counts["ticks_queued"], self.counts["duplicates_dropped"], self.counts["reconnects"],
            self.counts["gaps"], self.counts["errors"] + self.counts["handler_errors"],
            self.aggregator.ltt_convention, Jsonb(summary), self.session_id,
        )


async def run_live_capture(session: CaptureSession, client_id: str, access_token: str,
                           clock_ns=time.time_ns, connect_fn=None) -> str:
    """Runs one live session end to end. Returns the final session status."""
    config = session.config
    writer = session.writer
    started = datetime.now(IST)
    writer.start()
    writer.insert_now("hr_capture_sessions", session.session_row(started))
    writer.put_many({"hr_instruments": session.instrument_rows()})

    subscriptions = [(i.exchange_segment, i.security_id, i.subscribe_mode) for i in session.instruments]
    stop = asyncio.Event()
    feed = FeedClient(config, client_id, access_token, subscriptions, session.handle_message,
                      session.handle_feed_event, connect_fn=connect_fn, clock_ns=clock_ns)
    feed_task = asyncio.create_task(feed.run(stop))

    finish_ns = session.end_ns + int((config.bucket_grace_seconds + 0.5) * NS_PER_S)
    feed_status = None
    while True:
        now = clock_ns()
        session.finalize_due(now)
        if feed_task.done():
            feed_status = feed_task.result()
            if now < session.end_ns:
                logger.error("HR feed stopped early with status %s", feed_status)
            break
        if now >= finish_ns:
            break
        await asyncio.sleep(0.5)

    session.finalize_all()
    stop.set()
    if feed_status is None:
        try:
            feed_status = await asyncio.wait_for(feed_task, timeout=15)
        except Exception:
            feed_task.cancel()
            feed_status = "STOPPED"

    offset = ltt_offset_seconds(session.aggregator.ltt_convention)
    writer.stop(timeout=60)
    if offset is not None and session.aggregator.ltt_convention != LTT_UNDETERMINED:
        writer.execute_now(hr_db.BACKFILL_EXCHANGE_TS_SQL, (offset, session.session_id))
    if session.recorder is not None:
        session.recorder.close()
    params = session.finalize_session_params(feed_status)
    writer.execute_now(hr_db.FINALIZE_SESSION_SQL, params)
    return params[1]
