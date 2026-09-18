"""HR-1 5-second bars: correctness and determinism (from raw events only)."""

import random

from hr_capture.bars import build_bar
from hr_capture.config import DEFAULT_HR_CONFIG
from hr_capture.protocol import parse_message
from hr_capture.service import CaptureSession
from hr_capture.timeutil import LTT_UTC_EPOCH
from tests.hr_packet_factory import TRADING_DATE, ListWriter, full, make_universe, ns_at, option_id, quote


def _ev(raw):
    return parse_message(raw)[0]


def test_ohlc_volume_and_trade_count_from_raw_events():
    events = [
        (ns_at(15, 0, 0), _ev(full("NSE_FNO", 1, 100.0, volume=1000, ltt=1000))),
        (ns_at(15, 0, 1), _ev(full("NSE_FNO", 1, 104.0, volume=1010, ltt=1001))),
        (ns_at(15, 0, 2), _ev(full("NSE_FNO", 1, 98.5, volume=1010, ltt=1001))),
        (ns_at(15, 0, 4), _ev(full("NSE_FNO", 1, 101.0, volume=1025, ltt=1004))),
    ]
    bar, carry = build_bar(events, prev_last_volume=990, ltt_convention=LTT_UTC_EPOCH, is_gap=False)
    assert (bar["open"], bar["high"], bar["low"], bar["close"]) == (100.0, 104.0, 98.5, 101.0)
    assert bar["volume"] == 35 and bar["cumulative_volume_end"] == 1025 and carry == 1025
    assert bar["trade_count"] == 3          # 990->1000, 1000->1010, 1010->1025
    assert bar["update_count"] == 4
    assert bar["first_trade_ts"].timestamp() == 1000 and bar["last_trade_ts"].timestamp() == 1004
    assert bar["data_quality"] == "OK"


def test_empty_bucket_is_explicit_not_fabricated():
    bar, carry = build_bar([], prev_last_volume=500, ltt_convention=LTT_UTC_EPOCH, is_gap=False)
    assert bar["open"] is None and bar["close"] is None and bar["volume"] is None
    assert bar["update_count"] == 0 and bar["data_quality"] == "NO_UPDATE" and carry == 500


def test_volume_reset_and_in_bucket_baseline_are_flagged():
    reset, _ = build_bar([(1, _ev(full("NSE_FNO", 1, 1.0, volume=10)))], 50, LTT_UTC_EPOCH, False)
    assert reset["volume"] is None and "VOLUME_RESET" in reset["data_quality"]
    events = [(1, _ev(full("NSE_FNO", 1, 1.0, volume=10))), (2, _ev(full("NSE_FNO", 1, 1.0, volume=15)))]
    baseline, _ = build_bar(events, None, LTT_UTC_EPOCH, False)
    assert baseline["volume"] == 5 and "BASELINE_IN_BUCKET" in baseline["data_quality"]


def test_gap_flag_is_carried():
    bar, _ = build_bar([], None, LTT_UTC_EPOCH, is_gap=True)
    assert bar["data_quality"].startswith("GAP")


def _session_rows(messages):
    universe = make_universe()
    writer = ListWriter()
    session = CaptureSession(DEFAULT_HR_CONFIG, TRADING_DATE, {"NIFTY": universe}, writer, session_id="fixed")
    for receive_ns, data in messages:
        session.handle_message(receive_ns, data)
    session.finalize_all()
    return writer.rows


def _message_stream(seed: int):
    universe = make_universe()
    rng = random.Random(seed)
    out = []
    t = ns_at(14, 54, 50)
    atm_ce = option_id(universe, 0, "CE")
    volume = 1000
    price = 23400.0
    while t < ns_at(15, 1, 0):
        t += rng.randint(50_000_000, 900_000_000)
        volume += rng.randint(0, 20)
        price += rng.choice([-0.5, 0, 0.5])
        out.append((t, quote("IDX_I", 13, price, ltt=t // 1_000_000_000)))
        out.append((t + 1000, full("NSE_FNO", atm_ce, 100 + rng.random(), volume=volume, bid=99.0, ask=101.0,
                                   bid_qty=50, ask_qty=40, oi=5000 + rng.randint(0, 3))))
    return out


def test_aggregation_is_deterministic():
    stream = _message_stream(seed=7)
    first, second = _session_rows(stream), _session_rows(list(stream))

    def strip(rows):
        return {t: [{k: v for k, v in r.items() if k != "session_id"} for r in rs] for t, rs in rows.items()}

    assert strip(first) == strip(second)
    assert len(first["hr_ohlc_5s"]) == DEFAULT_HR_CONFIG_BUCKETS * len(make_universe().instruments)


DEFAULT_HR_CONFIG_BUCKETS = (35 * 60) // DEFAULT_HR_CONFIG.bar_seconds
