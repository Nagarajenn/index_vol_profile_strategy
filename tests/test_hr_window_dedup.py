"""HR-1 capture window restriction and duplicate handling."""

from hr_capture.config import DEFAULT_HR_CONFIG
from hr_capture.db import insert_sql
from hr_capture.schema_guard import load_schema_sql
from hr_capture.service import CaptureSession
from tests.hr_packet_factory import TRADING_DATE, ListWriter, full, make_universe, ns_at, option_id


class RecorderDouble:
    def __init__(self):
        self.records = []
        self.path = "memory"
        self.bytes_written = 0
        self.errors = 0

    def append(self, receive_ns, data):
        self.records.append(receive_ns)


def _session():
    universe = make_universe()
    writer = ListWriter()
    recorder = RecorderDouble()
    session = CaptureSession(DEFAULT_HR_CONFIG, TRADING_DATE, {"NIFTY": universe}, writer, recorder=recorder,
                             session_id="s")
    return session, writer, recorder, option_id(universe, 0, "CE")


def test_only_1455_to_1530_is_persisted_with_inclusive_start_exclusive_end():
    session, writer, recorder, sid = _session()
    times = {
        "before": ns_at(14, 54, 59, 999_999), "start": ns_at(14, 55, 0), "inside": ns_at(15, 20, 0),
        "last": ns_at(15, 29, 59, 999_999), "end": ns_at(15, 30, 0), "after": ns_at(15, 33, 0),
    }
    for i, (label, t) in enumerate(times.items()):
        session.handle_message(t, full("NSE_FNO", sid, 100.0 + i, volume=10 + i, bid=99.0, ask=101.0, bid_qty=1, ask_qty=1))
    session.finalize_all()
    persisted = sorted(r["receive_ns"] for r in writer.rows["hr_raw_ticks"])
    assert persisted == [times["start"], times["inside"], times["last"]]
    assert recorder.records == [times["start"], times["inside"], times["last"]]
    bar_times = {r["bar_ts"] for r in writer.rows["hr_ohlc_5s"]}
    assert min(bar_times).strftime("%H:%M:%S") == "14:55:00" and max(bar_times).strftime("%H:%M:%S") == "15:29:55"
    assert len({r["bar_ts"] for r in writer.rows["hr_option_transition_state"]}) == 420


def test_pre_window_packets_set_baselines_without_being_persisted():
    session, writer, _, sid = _session()
    session.handle_message(ns_at(14, 54, 50), full("NSE_FNO", sid, 100.0, volume=1000, bid=99.0, ask=101.0, bid_qty=1, ask_qty=1))
    session.handle_message(ns_at(14, 55, 1), full("NSE_FNO", sid, 101.0, volume=1040, bid=100.0, ask=102.0, bid_qty=1, ask_qty=1))
    session.finalize_all()
    first = next(r for r in writer.rows["hr_ohlc_5s"] if r["security_id"] == sid and r["bar_ts"].strftime("%H:%M:%S") == "14:55:00")
    assert first["volume"] == 40 and first["trade_count"] == 1
    assert len(writer.rows["hr_raw_ticks"]) == 1


def test_consecutive_identical_packets_are_dropped_and_counted():
    session, writer, _, sid = _session()
    raw = full("NSE_FNO", sid, 100.0, volume=10, bid=99.0, ask=101.0, bid_qty=1, ask_qty=1)
    for k in range(3):
        session.handle_message(ns_at(15, 0, k), raw)
    assert len(writer.rows["hr_raw_ticks"]) == 1
    assert session.counts["duplicates_dropped"] == 2


def test_a_b_a_state_changes_are_kept():
    """A quote that changes and changes back is real information, not a duplicate."""
    session, writer, _, sid = _session()
    a = full("NSE_FNO", sid, 100.0, volume=10, bid=99.0, ask=101.0, bid_qty=5, ask_qty=5)
    b = full("NSE_FNO", sid, 100.0, volume=10, bid=99.5, ask=101.0, bid_qty=5, ask_qty=5)
    for k, raw in enumerate((a, b, a)):
        session.handle_message(ns_at(15, 0, k), raw)
    assert len(writer.rows["hr_raw_ticks"]) == 3 and session.counts["duplicates_dropped"] == 0


def test_duplicates_still_prove_the_feed_is_alive():
    """Repeated identical packets must read as FROZEN (arriving, unchanged), not STALE (silent)."""
    session, writer, _, _ = _session()
    raw_index = __import__("tests.hr_packet_factory", fromlist=["quote"]).quote("IDX_I", 13, 23400.0, ltt=1)
    for s in range(0, 60):
        session.handle_message(ns_at(15, 16, 0) + s * 1_000_000_000, raw_index)
    session.finalize_all()
    row = next(r for r in writer.rows["hr_option_transition_state"] if r["bar_ts"].strftime("%H:%M:%S") == "15:16:55")
    assert row["underlying_status"] == "FROZEN"


def test_database_rewrites_of_the_same_packet_are_idempotent():
    assert "UNIQUE (session_id, packet_seq)" in load_schema_sql()
    assert "UNIQUE (exchange_segment, security_id, bar_ts)" in load_schema_sql()
    for table in ("hr_raw_ticks", "hr_ohlc_5s", "hr_option_5s", "hr_option_transition_state"):
        assert insert_sql(table).endswith("ON CONFLICT DO NOTHING")
    session, writer, _, sid = _session()
    for k in range(4):
        session.handle_message(ns_at(15, 0, k), full("NSE_FNO", sid, 100.0 + k, volume=10 + k))
    seqs = [r["packet_seq"] for r in writer.rows["hr_raw_ticks"]]
    assert seqs == sorted(set(seqs)) == [1, 2, 3, 4]
