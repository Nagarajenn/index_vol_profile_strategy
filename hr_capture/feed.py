"""Independent Dhan market-feed WebSocket client with explicit failure policy.

Deliberately not the SDK's MarketFeed loop, which (in dhanhq 2.2.0) lets a
first-connect failure escape, has no backoff, retries forever with an
expired token and does not surface disconnect intervals. This client:

* catches initial-connect failures and retries with bounded backoff;
* resubscribes the full universe on every (re)connect;
* reports CONNECT / SUBSCRIBED / DISCONNECT / RECONNECT_SCHEDULED events so
  the service can record reconnects and data gaps;
* stops immediately on authentication/entitlement failures (806-809, HTTP
  401/403) instead of retrying;
* retries a connection-limit disconnect (805) once, then stops;
* never logs the access token (it travels in the URL query string).

Market-data only: the only messages it can send are subscription and
disconnect requests.
"""

import asyncio
import logging
import time

from websockets.asyncio.client import connect as ws_connect
from websockets.exceptions import ConnectionClosed, InvalidStatus

from hr_capture.config import CONNECTION_LIMIT_CODE, FATAL_DISCONNECT_CODES, HRConfig
from hr_capture.protocol import DISCONNECT, build_feed_url, disconnect_message, redact_url, subscription_messages

logger = logging.getLogger(__name__)

STATUS_STOPPED = "STOPPED"
STATUS_FAILED_AUTH = "FAILED_AUTH"
STATUS_FAILED_CONNECTION = "FAILED_CONNECTION"


class FatalFeedError(Exception):
    def __init__(self, status: str, reason: str):
        super().__init__(reason)
        self.status = status
        self.reason = reason


def _disconnect_code(message: bytes) -> int | None:
    if len(message) >= DISCONNECT.size and message[0] == 50:
        return DISCONNECT.unpack_from(message, 0)[4]
    return None


class FeedClient:
    def __init__(self, config: HRConfig, client_id: str, access_token: str,
                 subscriptions: list[tuple[str, int, str]], on_message, on_event,
                 connect_fn=None, sleep_fn=None, clock_ns=time.time_ns):
        self.config = config
        self._url = build_feed_url(client_id, access_token)
        self.subscriptions = subscriptions
        self.on_message = on_message
        self.on_event = on_event
        self._connect_fn = connect_fn or (lambda url: ws_connect(
            url, open_timeout=10, ping_interval=20, ping_timeout=20, close_timeout=5,
            max_size=4 * 1024 * 1024, compression=None))
        self._sleep = sleep_fn or asyncio.sleep
        self._clock_ns = clock_ns
        self.connects = 0
        self.limit_retry_used = False
        self._delay_override: float | None = None
        self._got_packet = False

    def _event(self, event_type: str, **detail) -> None:
        try:
            self.on_event(event_type, self._clock_ns(), detail)
        except Exception:
            logger.exception("HR feed event handler failed (contained)")

    async def _sleep_or_stop(self, seconds: float, stop: asyncio.Event) -> None:
        remaining = float(seconds)
        while remaining > 0 and not stop.is_set():
            step = min(0.5, remaining)
            await self._sleep(step)
            remaining -= step

    async def run(self, stop: asyncio.Event) -> str:
        attempt = 0
        rate_limited = 0
        immediate_closes = 0
        while not stop.is_set():
            connected = False
            connected_at = None
            self._got_packet = False
            try:
                async with self._connect_fn(self._url) as ws:
                    connected = True
                    connected_at = time.monotonic()
                    self.connects += 1
                    self._event("CONNECT", attempt=attempt, url=redact_url(self._url))
                    for message in subscription_messages(self.subscriptions):
                        await ws.send(message)
                    self._event("SUBSCRIBED", instruments=len(self.subscriptions))
                    await self._receive(ws, stop)
                    if stop.is_set():
                        try:
                            await ws.send(disconnect_message())
                        except Exception:
                            pass
                        return STATUS_STOPPED
            except FatalFeedError as exc:
                self._event("AUTH_FAIL" if exc.status == STATUS_FAILED_AUTH else "CONNECTION_FAIL", reason=exc.reason)
                return exc.status
            except InvalidStatus as exc:
                code = getattr(getattr(exc, "response", None), "status_code", None)
                if code in (401, 403):
                    self._event("AUTH_FAIL", reason=f"HTTP {code} during WebSocket handshake")
                    return STATUS_FAILED_AUTH
                if code == 429:
                    cooldowns = self.config.rate_limit_backoff_seconds
                    self._delay_override = cooldowns[min(rate_limited, len(cooldowns) - 1)]
                    rate_limited += 1
                    self._event("RATE_LIMITED", http_status=429, cooldown_s=self._delay_override)
                self._event("DISCONNECT", reason=f"handshake rejected: HTTP {code}", connected=connected)
            except (ConnectionClosed, OSError, asyncio.TimeoutError, TimeoutError) as exc:
                self._event("DISCONNECT", reason=f"{type(exc).__name__}: {exc}"[:300], connected=connected)
            except Exception as exc:  # contained: unexpected client/library error
                self._event("DISCONNECT", reason=f"unexpected {type(exc).__name__}: {exc}"[:300], connected=connected)

            if stop.is_set():
                break
            if connected_at is not None:
                lived = time.monotonic() - connected_at
                if self._got_packet or lived >= self.config.stable_connection_seconds:
                    attempt, rate_limited, immediate_closes = 0, 0, 0
                else:
                    immediate_closes += 1
                    self._event("IMMEDIATE_CLOSE", lived_s=round(lived, 3), packets_received=False,
                                consecutive=immediate_closes)
                    if immediate_closes >= self.config.max_consecutive_immediate_closes:
                        self._event("CONNECTION_FAIL", reason=(
                            f"server closed {immediate_closes} consecutive connections immediately with no data; "
                            "stopping to avoid hammering the feed"))
                        return STATUS_FAILED_CONNECTION
            delays = self.config.backoff_seconds
            delay = delays[min(attempt, len(delays) - 1)]
            if self._delay_override is not None:
                delay, self._delay_override = self._delay_override, None
            attempt += 1
            self._event("RECONNECT_SCHEDULED", delay_s=delay, attempt=attempt)
            await self._sleep_or_stop(delay, stop)
        return STATUS_STOPPED

    async def _receive(self, ws, stop: asyncio.Event) -> None:
        while not stop.is_set():
            try:
                message = await asyncio.wait_for(ws.recv(), timeout=self.config.recv_poll_seconds)
            except (asyncio.TimeoutError, TimeoutError):
                continue
            receive_ns = self._clock_ns()
            if isinstance(message, str):
                self._event("TEXT_MESSAGE", text=message[:300])
                continue
            code = _disconnect_code(message)
            if code is not None:
                self._handle_server_disconnect(code)
                raise ConnectionClosed(None, None)
            self._got_packet = True
            try:
                self.on_message(receive_ns, message)
            except Exception:
                logger.exception("HR message handler failed (contained)")

    def _handle_server_disconnect(self, code: int) -> None:
        self._event("SERVER_DISCONNECT", code=code, reason=FATAL_DISCONNECT_CODES.get(code, "unknown"))
        if code in FATAL_DISCONNECT_CODES:
            raise FatalFeedError(STATUS_FAILED_AUTH, f"{code}: {FATAL_DISCONNECT_CODES[code]}")
        if code == CONNECTION_LIMIT_CODE:
            if self.limit_retry_used:
                raise FatalFeedError(STATUS_FAILED_CONNECTION, "805: active WebSocket connection limit exceeded (retry exhausted)")
            self.limit_retry_used = True
            self._delay_override = self.config.connection_limit_retry_s
