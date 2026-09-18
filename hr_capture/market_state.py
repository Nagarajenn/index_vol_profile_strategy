"""Conservative feed-status and market-state labels.

These are DATA labels. They exist so that later research never treats a
frozen underlying index as a continuously tradable price. They are not,
and must never be used as, trading signals.

The feed does not confirm the exchange's session phase, so the closing
period is labelled AUCTION_OR_CLOSING_STATE -- an observation that the
underlying stopped updating after the configured closing-phase start while
options/futures kept updating -- never "the auction" as a fact.
"""

VALID = "VALID"
STALE = "STALE"      # no packets received for the instrument recently
FROZEN = "FROZEN"    # packets still arriving, but the price has not changed
MISSING = "MISSING"  # never observed this session
FEED_STATUSES = (VALID, STALE, FROZEN, MISSING)

CONTINUOUS = "CONTINUOUS"
AUCTION_OR_CLOSING_STATE = "AUCTION_OR_CLOSING_STATE"
UNDERLYING_STALE = "UNDERLYING_STALE"
DATA_GAP = "DATA_GAP"
RECONNECT = "RECONNECT"
CLOSED = "CLOSED"
UNKNOWN = "UNKNOWN"
MARKET_STATES = (CONTINUOUS, AUCTION_OR_CLOSING_STATE, UNDERLYING_STALE, DATA_GAP, RECONNECT, CLOSED, UNKNOWN)


def classify_feed_status(ever_seen: bool, seconds_since_packet: float | None, seconds_since_change: float | None,
                         stale_after_s: float, frozen_after_s: float) -> str:
    if not ever_seen or seconds_since_packet is None:
        return MISSING
    if seconds_since_packet > stale_after_s:
        return STALE
    if seconds_since_change is not None and seconds_since_change > frozen_after_s:
        return FROZEN
    return VALID


def classify_market_state(*, after_window_end: bool, disconnected: bool, symbol_packets: int,
                          underlying_status: str, options_updated: int, futures_status: str,
                          closing_phase_reached: bool) -> str:
    if after_window_end:
        return CLOSED
    if disconnected:
        return RECONNECT
    if symbol_packets == 0:
        return DATA_GAP
    other_sources_active = options_updated > 0 or futures_status == VALID
    if underlying_status == VALID and options_updated > 0:
        return CONTINUOUS
    if underlying_status in (STALE, FROZEN) and closing_phase_reached and other_sources_active:
        return AUCTION_OR_CLOSING_STATE
    if underlying_status in (STALE, FROZEN, MISSING):
        return UNDERLYING_STALE
    return UNKNOWN
