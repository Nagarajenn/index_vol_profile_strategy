"""HR-1 session health, timestamps, missing intervals and fail-closed writing."""

from datetime import timezone

from hr_capture.config import DEFAULT_HR_CONFIG
from hr_capture.recorder import PacketRecorder, read_recording
from hr_capture.service import CaptureSession
from hr_capture.timeutil import (
    IST_OFFSET_S, LTT_IST_WALLCLOCK_EPOCH, LTT_UNDETERMINED, LTT_UTC_EPOCH, detect_ltt_convention,
)
from hr_capture.writer import HRWriter
from tests.hr_packet_factory import TRADING_DATE, ListWriter, full, make_universe, ns_at, option_id, quote


def _session(writer=None):
    universe = make_universe()
    writer = writer or ListWriter()
    return CaptureSession(DEFAULT_HR_CONFIG, TRADING_DATE, {"NIFTY": universe}, writer, session_id="s"), writer, universe


def test_exchange_time_and_receive_time_are_kept_separately():
    session, writer, universe = _session()
    sid = option_id(universe, 1, "CE")
    receive = ns_at(15, 1, 2, 345_678)
    ltt = receive // 1_000_000_000 - 3
    session.handle_message(receive, full("NSE_FNO", sid, 50.0, volume=7, ltt=ltt))
    tick = writer.rows["hr_raw_ticks"][0]
    assert tick["receive_ns"] == receive
    assert tick["receive_ts"].microsecond == 345_678
    assert tick["receive_ts"].strftime("%H:%M:%S") == "15:01:02"
    assert tick["ltt_epoch"] == ltt
    assert tick["raw_packet"] and tick["payload_hash"]


def test_ltt_convention_is_detected_not_assumed():
    now = ns_at(15, 0, 0)
    utc = [(now, now // 1_000_000_000 - 1)] * 60
    ist = [(now, now // 1_000_000_000 + IST_OFFSET_S)] * 60
    assert detect_ltt_convention(utc, 50, 300) == LTT_UTC_EPOCH
    assert detect_ltt_convention(ist, 50, 300) == LTT_IST_WALLCLOCK_EPOCH
    assert detect_ltt_convention(utc[:10], 50, 300) == LTT_UNDETERMINED
    assert detect_ltt_convention([(now, 5)] * 60, 50, 300) == LTT_UNDETERMINED


def test_missing_intervals_are_explicit_rows_and_data_gap_state():
    session, writer, universe = _session()
    sid = option_id(universe, 0, "PE")
    session.handle_message(ns_at(15, 0, 1), full("NSE_FNO", sid, 80.0, volume=5, bid=79.0, ask=81.0, bid_qty=1, ask_qty=1))
    session.finalize_all()
    per_contract = [r for r in writer.rows["hr_ohlc_5s"] if r["security_id"] == sid]
    assert len(per_contract) == 420
    assert sum(1 for r in per_contract if r["data_quality"] == "NO_UPDATE") == 419
    states = {r["bar_ts"].strftime("%H:%M:%S"): r["market_state"] for r in writer.rows["hr_option_transition_state"]}
    assert states["15:10:00"] == "DATA_GAP"
    summary = session.quality_summary("STOPPED")
    assert summary["instruments_received"] == 1 and len(summary["instruments_never_received"]) == 23
    assert session.final_status("STOPPED") == "COMPLETED_WITH_GAPS"


def test_session_rows_carry_versions_window_and_research_only_label():
    session, _, _ = _session()
    row = session.session_row(__import__("datetime").datetime.now(timezone.utc))
    assert row["mode"] == "LIVE" and row["status"] == "RUNNING" and row["instruments_expected"] == 24
    assert row["window_start"].strftime("%H:%M:%S") == "14:55:00" and row["window_end"].strftime("%H:%M:%S") == "15:30:00"
    assert row["implied_spot_method"].startswith("parity")
    assert len(session.instrument_rows()) == 24


def test_malformed_and_unregistered_data_never_raise():
    session, writer, _ = _session()
    session.handle_message(ns_at(15, 0, 0), b"\x08\x00garbage")
    session.handle_message(ns_at(15, 0, 1), full("NSE_FNO", 424242, 1.0))
    session.handle_message(ns_at(15, 0, 2), b"")
    assert session.counts["unknown_packets"] >= 1 and session.counts["unregistered_packets"] == 1
    assert "hr_raw_ticks" not in writer.rows


class ExplodingConnection:
    closed = False

    def cursor(self):
        raise RuntimeError("database is down")

    def close(self):
        self.closed = True


def test_database_failure_is_contained_and_spilled(tmp_path):
    writer = HRWriter(DEFAULT_HR_CONFIG, tmp_path, "sess", connection_factory=ExplodingConnection)
    writer.put("hr_capture_events", {"session_id": "sess", "event_ts": None, "event_type": "X", "symbol": None, "detail": {}})
    writer.stop(timeout=1)                     # flushes synchronously; must not raise
    assert writer.stats["failed"]["hr_capture_events"] == 1
    assert writer.stats["spilled"]["hr_capture_events"] == 1
    assert (tmp_path / "sess_spill_hr_capture_events.jsonl").exists()
    assert writer.execute_now("SELECT 1", None) is False


def test_writer_refuses_non_hr_tables(tmp_path):
    import pytest
    from hr_capture.db import insert_sql
    for table in ("raw_candles", "paper_decisions", "option_chain_raw", "levels_snapshots"):
        with pytest.raises(ValueError):
            insert_sql(table)


def test_recording_round_trip_and_truncated_tail(tmp_path):
    path = tmp_path / "rec.bin"
    recorder = PacketRecorder(path)
    payloads = [(ns_at(15, 0, i), quote("IDX_I", 13, 23400.0 + i)) for i in range(5)]
    for ns, data in payloads:
        recorder.append(ns, data)
    recorder.close()
    with open(path, "ab") as fh:
        fh.write(b"\x01\x02\x03")               # simulated crash mid-record
    assert list(read_recording(path)) == payloads
