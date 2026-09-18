"""HR-1 binary protocol: decoding fidelity against the Dhan SDK itself."""

import json

from dhanhq.marketfeed import MarketFeed

from hr_capture.protocol import (
    build_feed_url, disconnect_message, parse_message, redact_url, subscription_messages,
)
from tests.hr_packet_factory import disconnect_packet, full, oi_packet, prev_close, quote, status_packet, ticker


def _sdk():
    # Parsing methods do not touch connection state, so no network/auth is needed.
    return MarketFeed.__new__(MarketFeed)


def test_ticker_matches_sdk():
    raw = ticker("IDX_I", 13, 23427.35, ltt=1789462800)
    ours = parse_message(raw)[0]
    sdk = _sdk().process_ticker(raw)
    assert ours.packet_type == "TICKER" and ours.security_id == sdk["security_id"] == 13
    assert f"{ours.ltp:.2f}" == sdk["LTP"]
    assert ours.ltt_epoch == 1789462800
    assert ours.exchange_segment == "IDX_I"


def test_quote_matches_sdk_field_mapping():
    raw = quote("IDX_I", 51, 74838.05, volume=12345, ltt=1789462800, ltq=7, avg=74800.5, sell=111, buy=222,
                o=74700.0, c=74650.0, h=74900.0, low=74600.0)
    ours = parse_message(raw)[0]
    sdk = _sdk().process_quote(raw)
    assert f"{ours.ltp:.2f}" == sdk["LTP"] and ours.ltq == sdk["LTQ"] and ours.volume == sdk["volume"]
    assert ours.total_sell_qty == sdk["total_sell_quantity"] and ours.total_buy_qty == sdk["total_buy_quantity"]
    assert f"{ours.day_open:.2f}" == sdk["open"] and f"{ours.day_close_field:.2f}" == sdk["close"]
    assert f"{ours.day_high:.2f}" == sdk["high"] and f"{ours.day_low:.2f}" == sdk["low"]


def test_full_packet_with_depth_matches_sdk():
    levels = [(100 + i, 200 + i, 3 + i, 4 + i, 150.0 - i, 151.0 + i) for i in range(5)]
    raw = full("NSE_FNO", 47293, 150.5, volume=99999, oi=4321, ltt=1789462800, ltq=25, levels=levels,
               avg=149.75, sell=800, buy=900)
    ours = parse_message(raw)[0]
    sdk = _sdk().process_full(raw)
    assert ours.packet_type == "FULL"
    assert ours.oi == sdk["OI"] == 4321 and ours.volume == sdk["volume"] == 99999
    assert ours.total_sell_qty == sdk["total_sell_quantity"] and ours.total_buy_qty == sdk["total_buy_quantity"]
    for mine, theirs in zip(ours.depth, sdk["depth"]):
        assert mine["bid_qty"] == theirs["bid_quantity"] and mine["ask_qty"] == theirs["ask_quantity"]
        assert mine["bid_orders"] == theirs["bid_orders"] and mine["ask_orders"] == theirs["ask_orders"]
        assert f"{mine['bid_price']:.2f}" == theirs["bid_price"] and f"{mine['ask_price']:.2f}" == theirs["ask_price"]
    assert ours.raw == raw


def test_oi_prev_close_status_and_disconnect_packets():
    assert parse_message(oi_packet("BSE_FNO", 867703, 555))[0].oi == 555
    pc = parse_message(prev_close("NSE_FNO", 1, 101.25, 77))[0]
    assert pc.prev_close == 101.25 and pc.prev_oi == 77
    assert parse_message(status_packet())[0].packet_type == "STATUS"
    assert parse_message(disconnect_packet(807))[0].disconnect_code == 807


def test_concatenated_packets_are_all_decoded():
    data = ticker("IDX_I", 13, 1.0) + oi_packet("NSE_FNO", 5, 9) + full("NSE_FNO", 6, 2.0)
    types = [e.packet_type for e in parse_message(data)]
    assert types == ["TICKER", "OI", "FULL"]


def test_malformed_input_never_raises():
    assert parse_message(b"")[0:] == []
    truncated = full("NSE_FNO", 6, 2.0)[:40]
    events = parse_message(truncated)
    assert len(events) == 1 and events[0].packet_type == "UNKNOWN"
    assert parse_message(b"\xff\x00\x01")[0].packet_type == "UNKNOWN"


def test_subscription_batches_by_mode_and_size():
    instruments = [("NSE_FNO", i, "FULL") for i in range(150)] + [("IDX_I", 13, "QUOTE")]
    messages = [json.loads(m) for m in subscription_messages(instruments)]
    assert {m["RequestCode"] for m in messages} == {17, 21}
    assert sum(m["InstrumentCount"] for m in messages) == 151
    assert max(m["InstrumentCount"] for m in messages) <= 100
    assert all(isinstance(item["SecurityId"], str) for m in messages for item in m["InstrumentList"])


def test_only_market_data_request_codes_are_ever_built():
    codes = {json.loads(m)["RequestCode"] for m in subscription_messages(
        [("NSE_FNO", 1, "TICKER"), ("NSE_FNO", 2, "QUOTE"), ("NSE_FNO", 3, "FULL")])}
    assert codes == {15, 17, 21}
    assert json.loads(disconnect_message()) == {"RequestCode": 12}


def test_access_token_is_redacted():
    url = build_feed_url("CLIENT", "SECRET_TOKEN")
    assert "SECRET_TOKEN" in url
    assert "SECRET_TOKEN" not in redact_url(url) and "CLIENT" not in redact_url(url)
