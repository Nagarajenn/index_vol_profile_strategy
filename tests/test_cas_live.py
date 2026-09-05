"""Phase 7D: live wiring for today's CAS windowed detail. Tests the gating
logic (only [14:30, 15:15] does anything; a forecast checkpoint is written
at most once) with the DB layer monkeypatched out -- the underlying
compute functions (build_pre_transition_windows etc.) are already covered
by tests/test_cas_windows.py and tests/test_cas_forecast_no_leakage.py.
"""

from datetime import date, datetime, time

import pandas as pd
import pytest

from config.settings import IST
from pipeline import cas_live


@pytest.fixture(autouse=True)
def _reset_context_cache():
    cas_live._contexts.clear()
    yield
    cas_live._contexts.clear()


def _patch_db(monkeypatch, *, today_candles_empty: bool = False):
    """Stubs every db_reader/db_writer call cas_live.py makes, and returns
    a dict of call-count spies keyed by function name."""
    calls = {"load_raw_candles": 0, "insert_window": 0, "insert_minute": 0, "insert_forecast": 0}

    candles = pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])
    if not today_candles_empty:
        rows = []
        price = 100.0
        for hh, mm_range in [(9, range(15, 60)), (10, range(60)), (11, range(60)), (12, range(60)), (13, range(60)), (14, range(60)), (15, range(20))]:
            for mm in mm_range:
                price += 0.05
                ts = pd.Timestamp(2026, 8, 28, hh, mm, tz=IST)
                rows.append({"timestamp": ts, "open": price, "high": price + 0.5, "low": price - 0.5, "close": price, "volume": 100})
        candles = pd.DataFrame(rows)

    def _load_raw_candles(symbol, start_date=None, end_date=None):
        calls["load_raw_candles"] += 1
        return candles

    monkeypatch.setattr(cas_live.db_reader, "load_raw_candles", _load_raw_candles)
    monkeypatch.setattr(cas_live.db_reader, "load_cas_daily_transitions", lambda symbol, limit=10_000: [])
    monkeypatch.setattr(cas_live.db_reader, "list_classified_events_between", lambda start, end: [])
    monkeypatch.setattr(cas_live.db_reader, "get_option_summary_near", lambda symbol, session_date, at_or_before: None)
    monkeypatch.setattr(cas_live.db_reader, "get_option_chain_raw_near", lambda symbol, session_date, at_or_before: None)
    monkeypatch.setattr(cas_live.db_reader, "load_final_pretransition_windows", lambda symbol: {})
    monkeypatch.setattr(cas_live, "classify_expiry_day", lambda symbol, session_date: None)

    monkeypatch.setattr(cas_live.db_writer, "insert_cas_pretransition_window", lambda *a, **k: calls.__setitem__("insert_window", calls["insert_window"] + 1))
    monkeypatch.setattr(cas_live.db_writer, "insert_cas_post_transition_minute", lambda *a, **k: calls.__setitem__("insert_minute", calls["insert_minute"] + 1))
    monkeypatch.setattr(cas_live.db_writer, "insert_cas_transition_forecast", lambda *a, **k: calls.__setitem__("insert_forecast", calls["insert_forecast"] + 1))

    return calls


def test_no_op_before_1430(monkeypatch):
    calls = _patch_db(monkeypatch)
    cas_live.maybe_update("NIFTY", datetime(2026, 8, 28, 14, 29, tzinfo=IST))
    assert calls["load_raw_candles"] == 0
    assert calls["insert_window"] == 0


def test_no_op_after_1531(monkeypatch):
    calls = _patch_db(monkeypatch)
    cas_live.maybe_update("NIFTY", datetime(2026, 8, 28, 15, 32, tzinfo=IST))
    assert calls["load_raw_candles"] == 0


def test_still_active_at_1516_through_1530_for_the_closing_snapshot(monkeypatch):
    # The window was extended past the old 15:15 cutoff specifically to
    # catch the 15:30 closing-print checkpoint -- a tick at 15:20 (before
    # that candle exists in this fixture) is expected to still run and
    # just redundantly rewrite the same native minutes.
    calls = _patch_db(monkeypatch)
    cas_live.maybe_update("NIFTY", datetime(2026, 8, 28, 15, 20, tzinfo=IST))
    assert calls["load_raw_candles"] > 0
    assert calls["insert_minute"] > 0


def test_no_op_when_no_candles_yet(monkeypatch):
    calls = _patch_db(monkeypatch, today_candles_empty=True)
    cas_live.maybe_update("NIFTY", datetime(2026, 8, 28, 14, 35, tzinfo=IST))
    # Called twice: once inside context-building (full history), once for
    # today's own slice -- both legitimate, different purposes.
    assert calls["load_raw_candles"] == 2
    assert calls["insert_window"] == 0  # candles fetched, but empty -> bails out before computing anything


def test_writes_pre_transition_windows_during_pre_window(monkeypatch):
    calls = _patch_db(monkeypatch)
    cas_live.maybe_update("NIFTY", datetime(2026, 8, 28, 14, 35, tzinfo=IST))
    assert calls["insert_window"] == 6  # build_pre_transition_windows always returns all 6 (empty ones included)
    assert calls["insert_minute"] == 0  # not yet 15:00


def test_pre_window_branch_skipped_once_past_1459(monkeypatch):
    calls = _patch_db(monkeypatch)
    cas_live.maybe_update("NIFTY", datetime(2026, 8, 28, 15, 5, tzinfo=IST))
    assert calls["insert_window"] == 0  # 14:59 <= now_time is false at 15:05 -- pre-window branch skipped
    assert calls["insert_minute"] > 0


def test_forecast_checkpoint_written_at_most_once(monkeypatch):
    calls = _patch_db(monkeypatch)
    # 14:30 checkpoint is due starting at 14:30 -- call twice at the same/later time.
    cas_live.maybe_update("NIFTY", datetime(2026, 8, 28, 14, 30, tzinfo=IST))
    first_count = calls["insert_forecast"]
    cas_live.maybe_update("NIFTY", datetime(2026, 8, 28, 14, 31, tzinfo=IST))
    # 14:30's checkpoint must not be re-written; only newly-due checkpoints (none yet, since 14:35 isn't a checkpoint) fire.
    assert calls["insert_forecast"] == first_count


def test_context_rebuilds_on_a_new_trading_day(monkeypatch):
    _patch_db(monkeypatch)
    # Day 1 at 14:59: all 7 checkpoints are due, fully populating that day's
    # written_forecast_checkpoints.
    cas_live.maybe_update("NIFTY", datetime(2026, 8, 28, 14, 59, tzinfo=IST))
    ctx_day1 = cas_live._contexts["NIFTY"]
    assert ctx_day1.session_date == date(2026, 8, 28)
    assert len(ctx_day1.written_forecast_checkpoints) == 7

    # Day 2 at 14:30: only the first checkpoint is naturally due. If the new
    # context inherited day 1's set, this would show 7 (or at least more
    # than 1) instead of exactly 1 -- proving it started fresh, not carried
    # over.
    cas_live.maybe_update("NIFTY", datetime(2026, 8, 31, 14, 30, tzinfo=IST))
    ctx_day2 = cas_live._contexts["NIFTY"]
    assert ctx_day2.session_date == date(2026, 8, 31)
    assert ctx_day2 is not ctx_day1
    assert len(ctx_day2.written_forecast_checkpoints) == 1
