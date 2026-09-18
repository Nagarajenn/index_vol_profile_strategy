"""HR-1 market-state foundation, including 15:15+ stale-underlying handling."""

from hr_capture.config import DEFAULT_HR_CONFIG
from hr_capture.market_state import (
    AUCTION_OR_CLOSING_STATE, CLOSED, CONTINUOUS, DATA_GAP, FROZEN, MISSING, RECONNECT, STALE, UNDERLYING_STALE,
    UNKNOWN, VALID, classify_feed_status, classify_market_state,
)
from hr_capture.service import CaptureSession
from tests.hr_packet_factory import TRADING_DATE, ListWriter, full, make_universe, ns_at, option_id, quote


def test_feed_status_values():
    assert classify_feed_status(False, None, None, 30, 30) == MISSING
    assert classify_feed_status(True, 45.0, 45.0, 30, 30) == STALE
    assert classify_feed_status(True, 2.0, 90.0, 30, 30) == FROZEN
    assert classify_feed_status(True, 2.0, 3.0, 30, 30) == VALID


def _state(**kw):
    base = dict(after_window_end=False, disconnected=False, symbol_packets=10, underlying_status=VALID,
                options_updated=5, futures_status=VALID, closing_phase_reached=False)
    base.update(kw)
    return classify_market_state(**base)


def test_market_state_precedence():
    assert _state() == CONTINUOUS
    assert _state(after_window_end=True) == CLOSED
    assert _state(disconnected=True) == RECONNECT
    assert _state(symbol_packets=0) == DATA_GAP
    assert _state(underlying_status=FROZEN, closing_phase_reached=True) == AUCTION_OR_CLOSING_STATE
    assert _state(underlying_status=STALE, closing_phase_reached=False) == UNDERLYING_STALE
    assert _state(underlying_status=FROZEN, closing_phase_reached=True, options_updated=0,
                  futures_status=STALE) == UNDERLYING_STALE
    assert _state(options_updated=0, futures_status=STALE) == UNKNOWN


def test_frozen_underlying_after_1515_is_represented_while_options_stay_active():
    universe = make_universe()
    writer = ListWriter()
    session = CaptureSession(DEFAULT_HR_CONFIG, TRADING_DATE, {"NIFTY": universe}, writer, session_id="s")
    atm_ce = option_id(universe, 0, "CE")
    volume = 1_000
    t = ns_at(14, 54, 30)
    price = 23400.0
    while t < ns_at(15, 29, 59):
        t += 1_000_000_000
        before_close = t < ns_at(15, 15, 0)
        if before_close:
            price += 0.05
        # the index keeps publishing the same price after 15:15 (frozen), options keep trading
        session.handle_message(t, quote("IDX_I", 13, price, ltt=t // 1_000_000_000))
        volume += 3
        session.handle_message(t + 5, full("NSE_FNO", atm_ce, 100.0 + (volume % 7) * 0.05, volume=volume,
                                           bid=99.0, ask=101.0, bid_qty=10, ask_qty=10))
        session.handle_message(t + 9, full("NSE_FNO", 70000, 23450.0 + (volume % 5) * 0.05, volume=volume,
                                           bid=23449.0, ask=23451.0, bid_qty=5, ask_qty=5))
    session.finalize_all()
    states = {r["bar_ts"].strftime("%H:%M:%S"): r for r in writer.rows["hr_option_transition_state"]}
    assert states["15:00:00"]["market_state"] == CONTINUOUS
    assert states["15:00:00"]["underlying_status"] == VALID
    late = states["15:20:00"]
    assert late["underlying_status"] == FROZEN
    assert late["market_state"] == AUCTION_OR_CLOSING_STATE
    assert late["options_updated"] >= 1 and late["futures_status"] == VALID
    assert late["last_reliable_underlying_price"] == late["underlying_last_price"]
    assert late["last_reliable_underlying_ts"].strftime("%H:%M") == "15:14"
    changes = [e for e in writer.rows["hr_capture_events"] if e["event_type"] == "STATE_CHANGE"]
    assert any(c["detail"]["to"] == AUCTION_OR_CLOSING_STATE for c in changes)
