"""HR-1 configuration. Capture/quality parameters only -- there are no
trading parameters anywhere in this package."""

from dataclasses import asdict, dataclass
from datetime import time
from pathlib import Path

HR_PIPELINE_VERSION = "hr1-capture-v1"
PARSER_VERSION = "dhan-feed-v2-binary/mirrors-dhanhq-2.2.0-marketfeed"
# RESEARCH ONLY. Never a trading input.
IMPLIED_SPOT_METHOD = "parity-mid-median-v1"

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RECORDING_DIR = PROJECT_ROOT / "data" / "cache" / "hr_capture"   # git-ignored (data/cache/*)
LOG_DIR = PROJECT_ROOT / "logs" / "hr"                              # git-ignored (logs/*)
SCRIP_MASTER_CSV = PROJECT_ROOT / "data" / "cache" / "scrip_master.csv"  # read-only; HR never downloads it

FEED_WSS = "wss://api-feed.dhan.co"

# Dhan v2 feed request codes, identical to dhanhq 2.2.0 MarketFeed.Ticker/Quote/Full.
REQUEST_CODES = {"TICKER": 15, "QUOTE": 17, "FULL": 21}
DISCONNECT_REQUEST_CODE = 12

# Server disconnection codes (dhanhq 2.2.0 MarketFeed.server_disconnection).
CONNECTION_LIMIT_CODE = 805
FATAL_DISCONNECT_CODES = {
    806: "Data API subscription required",
    807: "Access token expired",
    808: "Invalid client ID",
    809: "Authentication failed",
}


@dataclass(frozen=True)
class HRConfig:
    symbols: tuple[str, ...] = ("NIFTY", "SENSEX")

    # Session clock (IST). Persisted research data is restricted to
    # window_start <= receive_ts < window_end.
    resolve_at: time = time(14, 54, 0)
    window_start: time = time(14, 55, 0)
    window_end: time = time(15, 30, 0)
    hard_stop: time = time(15, 35, 0)
    # Observed start of the closing/auction-related period (CAS era). The feed
    # itself does not confirm the exchange phase, so states derived from this
    # are labelled conservatively (AUCTION_OR_CLOSING_STATE).
    closing_phase_start: time = time(15, 15, 0)

    bar_seconds: int = 5
    bucket_grace_seconds: float = 2.0

    # Instrument universe: index + current futures + ATM +/- band CE/PE per symbol.
    atm_band_strikes: int = 5
    index_mode: str = "QUOTE"
    futures_mode: str = "FULL"
    option_mode: str = "FULL"

    # Feed-status thresholds (descriptive data-quality labels, not signals).
    underlying_stale_after_s: float = 30.0
    underlying_frozen_after_s: float = 30.0
    futures_stale_after_s: float = 30.0
    futures_frozen_after_s: float = 30.0
    option_quote_stale_after_s: float = 30.0
    disappeared_after_s: float = 60.0

    implied_spot_min_strikes: int = 5

    # Exchange last-trade-time epoch convention detection.
    ltt_detection_samples: int = 50
    ltt_convention_tolerance_s: float = 300.0

    # Universe resolution retries (option_chain_raw may lag by a few seconds).
    universe_retry_seconds: float = 10.0
    universe_fallback_after: time = time(14, 55, 30)

    # WebSocket reconnect policy.
    backoff_seconds: tuple[float, ...] = (1.0, 2.0, 4.0, 8.0, 16.0, 30.0)
    # HTTP 429 on the handshake means we are being rate limited: back off hard.
    rate_limit_backoff_seconds: tuple[float, ...] = (60.0, 120.0, 300.0)
    # Backoff only resets once a connection has delivered data or stayed up
    # this long -- an immediate server-side close must not become a 1-second
    # reconnect loop (observed 2026-09-13: immediate closes escalated to 429).
    stable_connection_seconds: float = 30.0
    # Fail closed if the server keeps accepting then immediately dropping the
    # socket with zero packets: stop the session rather than hammer the feed
    # (and risk account-level throttling shared with the live loop's REST use).
    max_consecutive_immediate_closes: int = 5
    connection_limit_retry_s: float = 30.0
    recv_poll_seconds: float = 1.0

    # Writer / DB isolation.
    flush_interval_s: float = 2.0
    max_queue_rows: int = 500_000
    max_rows_per_insert: int = 5_000
    db_statement_timeout_ms: int = 5_000
    db_lock_timeout_ms: int = 2_000

    def as_json(self) -> dict:
        out = {}
        for key, value in asdict(self).items():
            out[key] = value.isoformat() if isinstance(value, time) else (list(value) if isinstance(value, tuple) else value)
        return out


DEFAULT_HR_CONFIG = HRConfig()
