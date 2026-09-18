"""Process-level entry logic for the HR capture service (used by
scripts/run_hr_capture.py). Owns the trading-day check, universe resolution,
the hard-stop watchdog and the offline connectivity test."""

import asyncio
import logging
import os
import threading
import time
from collections import Counter
from datetime import date, datetime, timedelta

from config.settings import IST, require_credentials
from hr_capture import db as hr_db
from hr_capture.config import RECORDING_DIR, SCRIP_MASTER_CSV, HRConfig
from hr_capture.feed import FeedClient
from hr_capture.protocol import parse_message
from hr_capture.recorder import PacketRecorder, write_sidecar
from hr_capture.service import MODE_DRY_RUN, MODE_LIVE, CaptureSession, run_live_capture
from hr_capture.timeutil import detect_ltt_convention
from hr_capture.universe import (
    load_latest_chain_row, load_latest_spot, load_scrip_frame, resolve_symbol_universe,
)
from hr_capture.writer import HRWriter
from pipeline.trading_calendar import is_trading_day

logger = logging.getLogger(__name__)


def resolve_universes(config: HRConfig, trading_date: date, as_of: datetime, universe_date: date | None = None,
                      wait_for_chain: bool = True) -> dict:
    """Resolve every symbol's universe from data the existing pipeline has
    already captured. Retries until ``universe_fallback_after`` for the
    option_chain_raw row, then falls back to the scrip master."""
    source_date = universe_date or trading_date
    day_start = datetime.combine(source_date, datetime.min.time(), tzinfo=IST)
    scrip = load_scrip_frame(SCRIP_MASTER_CSV)
    fallback_deadline = datetime.combine(trading_date, config.universe_fallback_after, tzinfo=IST)
    universes = {}
    conn = hr_db.connect(config)
    try:
        for symbol in config.symbols:
            chain = load_latest_chain_row(conn, symbol, day_start, as_of)
            while chain is None and wait_for_chain and datetime.now(IST) < fallback_deadline:
                time.sleep(config.universe_retry_seconds)
                chain = load_latest_chain_row(conn, symbol, day_start, datetime.now(IST))
            spot = load_latest_spot(conn, symbol, day_start, as_of) if chain is None else None
            universes[symbol] = resolve_symbol_universe(
                symbol, trading_date, chain, spot, scrip, config.atm_band_strikes,
                config.index_mode, config.futures_mode, config.option_mode,
            )
            u = universes[symbol]
            logger.info("%s universe: %d instruments, band ATM %s, spot %s, expiry %s, issues %s",
                        symbol, len(u.instruments), u.band_atm_strike, u.reference_spot, u.expiry, u.issues)
    finally:
        conn.close()
    return universes


def start_hard_stop_watchdog(trading_date: date, config: HRConfig, on_hard_stop=None) -> threading.Thread:
    """Wall-clock hard stop. Independent of the event loop, so a hung loop
    or a stuck library call still cannot keep the process alive past it."""
    deadline = datetime.combine(trading_date, config.hard_stop, tzinfo=IST)

    def _watch():
        while datetime.now(IST) < deadline:
            time.sleep(1.0)
        logger.error("HR hard stop reached (%s) -- terminating process", deadline.isoformat())
        if on_hard_stop is not None:
            try:
                on_hard_stop()
            except Exception:
                pass
        logging.shutdown()
        os._exit(3)

    thread = threading.Thread(target=_watch, name="hr-hard-stop", daemon=True)
    thread.start()
    return thread


def run_capture(config: HRConfig, dry_run: bool = False, now_fn=lambda: datetime.now(IST)) -> str:
    now = now_fn()
    trading_date = now.date()
    if not is_trading_day(trading_date):
        logger.info("%s is not a trading day -- HR capture exiting without a session", trading_date)
        return "NOT_TRADING_DAY"
    window_end = datetime.combine(trading_date, config.window_end, tzinfo=IST)
    hard_stop = datetime.combine(trading_date, config.hard_stop, tzinfo=IST)
    if now >= window_end:
        logger.info("Capture window already over (%s) -- exiting", window_end.time())
        return "WINDOW_PASSED"

    resolve_at = datetime.combine(trading_date, config.resolve_at, tzinfo=IST)
    if now < resolve_at:
        logger.info("Sleeping until universe resolution at %s", resolve_at.time())
        while now_fn() < resolve_at:
            time.sleep(min(30.0, max(0.5, (resolve_at - now_fn()).total_seconds())))

    session_holder: dict = {}

    def _on_hard_stop():
        session = session_holder.get("session")
        if session is not None and not dry_run:
            conn = hr_db.connect(config)
            try:
                with conn.cursor() as cur:
                    cur.execute("UPDATE hr_capture_sessions SET status = %s, ended_at = now() WHERE session_id = %s",
                                ("HARD_STOP", session.session_id))
            finally:
                conn.close()

    start_hard_stop_watchdog(trading_date, config, _on_hard_stop)
    if datetime.now(IST) >= hard_stop:
        return "HARD_STOP"

    universes = resolve_universes(config, trading_date, datetime.now(IST))
    client_id, access_token = require_credentials()
    session = CaptureSession(config, trading_date, universes, writer=None,
                             mode=MODE_DRY_RUN if dry_run else MODE_LIVE)
    session.writer = HRWriter(config, RECORDING_DIR, session.session_id, enabled=not dry_run)
    if not dry_run:
        recording = RECORDING_DIR / f"{trading_date:%Y%m%d}_{session.session_id}.bin"
        session.recorder = PacketRecorder(recording)
        write_sidecar(recording.with_suffix(".meta.json"), {
            "session_id": session.session_id, "trading_date": trading_date.isoformat(),
            "config": config.as_json(),
            "universes": {s: {"band_atm_strike": u.band_atm_strike, "reference_spot": u.reference_spot,
                              "expiry": u.expiry, "strike_step": u.strike_step, "issues": u.issues,
                              "instruments": [i.as_dict() for i in u.instruments]} for s, u in universes.items()},
        })
    session_holder["session"] = session
    status = asyncio.run(run_live_capture(session, client_id, access_token))
    logger.info("HR capture session %s finished with status %s", session.session_id, status)
    return status


def connectivity_test(config: HRConfig, seconds: float, universe_date: date, as_of: datetime) -> dict:
    """Connect, subscribe and count what arrives. Writes NOTHING: no DB rows,
    no recording. Safe outside market hours (validates auth/entitlement and
    subscription acceptance, not live update rates)."""
    trading_date = datetime.now(IST).date()
    universes = resolve_universes(config, trading_date, as_of, universe_date=universe_date, wait_for_chain=False)
    instruments = [i for u in universes.values() for i in u.instruments]
    client_id, access_token = require_credentials()
    packet_types: Counter = Counter()
    by_segment: Counter = Counter()
    per_instrument: Counter = Counter()
    events: list = []
    samples: list = []
    first_packet: dict = {}

    def on_message(receive_ns, data):
        for ev in parse_message(data):
            packet_types[ev.packet_type] += 1
            by_segment[ev.exchange_segment] += 1
            per_instrument[f"{ev.exchange_segment}:{ev.security_id}"] += 1
            first_packet.setdefault(ev.packet_type, {"segment": ev.exchange_segment, "security_id": ev.security_id,
                                                     "ltp": ev.ltp, "ltt_epoch": ev.ltt_epoch, "volume": ev.volume,
                                                     "oi": ev.oi, "has_depth": bool(ev.depth)})
            if ev.ltt_epoch:
                samples.append((receive_ns, ev.ltt_epoch))

    def on_event(event_type, event_ns, detail):
        events.append({"type": event_type, "at": datetime.fromtimestamp(event_ns / 1e9, IST).isoformat(), **detail})

    async def _run():
        stop = asyncio.Event()
        feed = FeedClient(config, client_id, access_token,
                          [(i.exchange_segment, i.security_id, i.subscribe_mode) for i in instruments],
                          on_message, on_event)
        task = asyncio.create_task(feed.run(stop))
        await asyncio.sleep(seconds)
        stop.set()
        try:
            return await asyncio.wait_for(task, timeout=15)
        except Exception:
            task.cancel()
            return "STOPPED"

    status = asyncio.run(_run())
    return {
        "feed_status": status,
        "instruments_subscribed": len(instruments),
        "universe": {s: {"band_atm_strike": u.band_atm_strike, "reference_spot": u.reference_spot,
                         "expiry": str(u.expiry), "issues": u.issues,
                         "index": [i.as_dict() for i in u.instruments if i.instrument_type == "INDEX"],
                         "futures": [i.as_dict() for i in u.instruments if i.instrument_type == "FUTIDX"],
                         "options": len(u.options)} for s, u in universes.items()},
        "events": events,
        "packet_types": dict(packet_types),
        "packets_by_segment": dict(by_segment),
        "instruments_with_packets": len(per_instrument),
        "first_packet_by_type": first_packet,
        "ltt_convention_estimate": detect_ltt_convention(samples, 5, config.ltt_convention_tolerance_s),
        "ltt_samples": len(samples),
    }
