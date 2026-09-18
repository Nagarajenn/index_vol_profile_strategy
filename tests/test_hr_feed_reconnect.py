"""HR-1 WebSocket failure policy: reconnect, resubscribe, gaps, auth stop."""

import asyncio
import json

from websockets.datastructures import Headers
from websockets.exceptions import ConnectionClosedError, InvalidStatus
from websockets.http11 import Response

from hr_capture.config import DEFAULT_HR_CONFIG
from hr_capture.feed import STATUS_FAILED_AUTH, STATUS_FAILED_CONNECTION, STATUS_STOPPED, FeedClient
from hr_capture.service import CaptureSession
from tests.hr_packet_factory import (
    TRADING_DATE, ListWriter, disconnect_packet, full, make_universe, ns_at, option_id,
)


class FakeWS:
    def __init__(self, script, stop):
        self.script = list(script)
        self.sent = []
        self.stop = stop

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def send(self, message):
        self.sent.append(message)

    async def recv(self):
        if not self.script:
            await asyncio.sleep(0.01)
            raise ConnectionClosedError(None, None)
        item = self.script.pop(0)
        if item == "STOP":
            self.stop.set()
            await asyncio.sleep(0.05)
            raise asyncio.TimeoutError
        if isinstance(item, Exception):
            raise item
        return item


class Harness:
    """Scripted connection attempts: an Exception means the connect fails."""

    def __init__(self, attempts):
        self.attempts = list(attempts)
        self.connections: list[FakeWS] = []
        self.sleeps: list[float] = []
        self.events: list[tuple] = []
        self.messages: list[bytes] = []
        self.stop = None
        self.clock = [ns_at(14, 54, 0)]

    def connect(self, url):
        attempt = self.attempts.pop(0) if self.attempts else ["STOP"]
        if isinstance(attempt, Exception):
            raise attempt
        ws = FakeWS(attempt, self.stop)
        self.connections.append(ws)
        return ws

    async def sleep(self, seconds):
        self.sleeps.append(seconds)
        await asyncio.sleep(0)

    def clock_ns(self):
        self.clock[0] += 250_000_000
        return self.clock[0]

    def run(self, subscriptions=None, on_event=None, on_message=None):
        async def _go():
            self.stop = asyncio.Event()
            client = FeedClient(DEFAULT_HR_CONFIG, "CID", "TOKEN", subscriptions or [("NSE_FNO", 1, "FULL")],
                                on_message or (lambda ns, data: self.messages.append(data)),
                                on_event or (lambda t, ns, d: self.events.append((t, d))),
                                connect_fn=self.connect, sleep_fn=self.sleep, clock_ns=self.clock_ns)
            return await asyncio.wait_for(client.run(self.stop), timeout=10)
        return asyncio.run(_go())


def _types(h):
    return [t for t, _ in h.events]


def test_initial_connect_failure_is_retried_with_bounded_backoff():
    h = Harness([OSError("dns"), OSError("dns"), [b"x" * 16, "STOP"]])
    assert h.run() == STATUS_STOPPED
    assert _types(h)[:4] == ["DISCONNECT", "RECONNECT_SCHEDULED", "DISCONNECT", "RECONNECT_SCHEDULED"]
    delays = [d["delay_s"] for t, d in h.events if t == "RECONNECT_SCHEDULED"]
    assert delays == [1.0, 2.0]
    assert "CONNECT" in _types(h) and "SUBSCRIBED" in _types(h)


def test_drop_reconnects_and_resubscribes_everything():
    subs = [("IDX_I", 13, "QUOTE"), ("NSE_FNO", 5, "FULL"), ("NSE_FNO", 6, "FULL")]
    h = Harness([[b"a" * 16, ConnectionClosedError(None, None)], [b"b" * 16, "STOP"]])
    assert h.run(subscriptions=subs) == STATUS_STOPPED
    assert len(h.connections) == 2
    for ws in h.connections:
        subscribed = [json.loads(m) for m in ws.sent if json.loads(m).get("RequestCode") in (15, 17, 21)]
        assert sum(m["InstrumentCount"] for m in subscribed) == 3
    assert _types(h).count("SUBSCRIBED") == 2 and _types(h).count("DISCONNECT") == 1
    assert json.loads(h.connections[-1].sent[-1]) == {"RequestCode": 12}


def test_expired_token_disconnect_stops_without_retry():
    h = Harness([[disconnect_packet(807)], [b"never" * 4]])
    assert h.run() == STATUS_FAILED_AUTH
    assert len(h.connections) == 1 and "RECONNECT_SCHEDULED" not in _types(h)
    assert "AUTH_FAIL" in _types(h)


def test_http_401_handshake_is_an_auth_failure_not_a_retry_loop():
    h = Harness([InvalidStatus(Response(401, "Unauthorized", Headers()))])
    assert h.run() == STATUS_FAILED_AUTH
    assert h.sleeps == []


def test_connection_limit_is_retried_once_then_stops():
    h = Harness([[disconnect_packet(805)], [disconnect_packet(805)]])
    assert h.run() == STATUS_FAILED_CONNECTION
    delays = [d["delay_s"] for t, d in h.events if t == "RECONNECT_SCHEDULED"]
    assert delays == [DEFAULT_HR_CONFIG.connection_limit_retry_s]


def test_http_429_uses_rate_limit_cooldown_not_fast_retry():
    h = Harness([InvalidStatus(Response(429, "Too Many Requests", Headers())),
                 InvalidStatus(Response(429, "Too Many Requests", Headers())), [b"z" * 16, "STOP"]])
    assert h.run() == STATUS_STOPPED
    delays = [d["delay_s"] for t, d in h.events if t == "RECONNECT_SCHEDULED"]
    assert delays == list(DEFAULT_HR_CONFIG.rate_limit_backoff_seconds[:2])
    assert _types(h).count("RATE_LIMITED") == 2


def test_immediate_server_closes_escalate_backoff_instead_of_resetting():
    """Observed 2026-09-13 offline: server closed ~10 ms after subscribe with no packets.
    Resetting the backoff on subscribe turned that into a 1-second loop and then HTTP 429."""
    closes = [[ConnectionClosedError(None, None)] for _ in range(4)]
    h = Harness(closes + [[b"y" * 16, "STOP"]])
    assert h.run() == STATUS_STOPPED
    delays = [d["delay_s"] for t, d in h.events if t == "RECONNECT_SCHEDULED"]
    assert delays == [1.0, 2.0, 4.0, 8.0]
    assert _types(h).count("IMMEDIATE_CLOSE") == 4


def test_persistent_immediate_closes_fail_closed_after_cap():
    """Observed 2026-09-13 with both HR and the Dhan SDK: accept, subscribe, drop in ~0.2 s, zero packets."""
    cap = DEFAULT_HR_CONFIG.max_consecutive_immediate_closes
    h = Harness([[ConnectionClosedError(None, None)] for _ in range(cap + 10)])
    assert h.run() == STATUS_FAILED_CONNECTION
    assert len(h.connections) == cap
    assert "CONNECTION_FAIL" in _types(h)


def test_reconnects_and_data_gaps_are_recorded_in_the_session():
    universe = make_universe()
    writer = ListWriter()
    session = CaptureSession(DEFAULT_HR_CONFIG, TRADING_DATE, {"NIFTY": universe}, writer, session_id="s")
    sid = option_id(universe, 0, "CE")
    session.handle_message(ns_at(15, 0, 0), full("NSE_FNO", sid, 100.0, volume=1))
    session.handle_feed_event("DISCONNECT", ns_at(15, 0, 3), {"reason": "ConnectionClosedError"})
    session.handle_feed_event("RECONNECT_SCHEDULED", ns_at(15, 0, 3), {"delay_s": 1.0})
    session.handle_feed_event("CONNECT", ns_at(15, 0, 11), {})
    session.handle_feed_event("SUBSCRIBED", ns_at(15, 0, 12), {"instruments": 24})
    session.handle_message(ns_at(15, 0, 13), full("NSE_FNO", sid, 101.0, volume=2))
    session.finalize_all()

    assert session.counts["gaps"] == 1 and session.counts["reconnects"] == 1
    assert session.gap_intervals[0]["seconds"] == 9.0
    kinds = [e["event_type"] for e in writer.rows["hr_capture_events"]]
    assert "GAP_START" in kinds and "GAP_END" in kinds
    states = {r["bar_ts"].strftime("%H:%M:%S"): r for r in writer.rows["hr_option_transition_state"]}
    assert states["15:00:05"]["market_state"] == "RECONNECT"
    assert "GAP" in states["15:00:05"]["data_quality"]
    bars = [r for r in writer.rows["hr_ohlc_5s"] if r["security_id"] == sid and r["bar_ts"].strftime("%H:%M:%S") == "15:00:05"]
    assert bars[0]["data_quality"].startswith("GAP")
    assert session.final_status("STOPPED") == "COMPLETED_WITH_GAPS"
