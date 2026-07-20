import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import IST
from pipeline.run_snapshot import should_render_chart


def _fake_reader(baseline):
    def _fn(symbol, mode, session_date):
        return baseline
    return _fn


def test_backfill_mode_passes_through_force_chart():
    now = datetime(2026, 7, 20, 10, 0, tzinfo=IST)
    assert should_render_chart("SENSEX", "Bullish", 100, now, "backfill", bin_size=25, force_chart=True) == (
        True, "backfill_checkpoint",
    )
    assert should_render_chart("SENSEX", "Bullish", 100, now, "backfill", bin_size=25, force_chart=False) == (
        False, None,
    )


def test_live_mode_no_baseline_is_first_of_session():
    now = datetime(2026, 7, 20, 9, 15, tzinfo=IST)
    should, trigger = should_render_chart(
        "SENSEX", "Bullish intraday", 78000, now, "live", bin_size=25,
        get_last_chart_row_fn=_fake_reader(None),
    )
    assert (should, trigger) == (True, "first_of_session")


def test_live_mode_trend_change_fires():
    now = datetime(2026, 7, 20, 10, 0, tzinfo=IST)
    baseline = {"as_of": now - timedelta(minutes=5), "trend_label": "Bearish intraday", "today_poc": 78000}
    should, trigger = should_render_chart(
        "SENSEX", "Bullish intraday", 78000, now, "live", bin_size=25,
        get_last_chart_row_fn=_fake_reader(baseline),
    )
    assert (should, trigger) == (True, "trend_change")


def test_live_mode_poc_move_beyond_bin_size_fires():
    now = datetime(2026, 7, 20, 10, 0, tzinfo=IST)
    baseline = {"as_of": now - timedelta(minutes=5), "trend_label": "Bullish intraday", "today_poc": 78000}
    should, trigger = should_render_chart(
        "SENSEX", "Bullish intraday", 78030, now, "live", bin_size=25,  # 30pt move >= 25pt bin
        get_last_chart_row_fn=_fake_reader(baseline),
    )
    assert (should, trigger) == (True, "poc_change")


def test_live_mode_poc_move_within_bin_size_does_not_fire():
    now = datetime(2026, 7, 20, 10, 0, tzinfo=IST)
    baseline = {"as_of": now - timedelta(minutes=5), "trend_label": "Bullish intraday", "today_poc": 78000}
    should, trigger = should_render_chart(
        "SENSEX", "Bullish intraday", 78010, now, "live", bin_size=25,  # 10pt move < 25pt bin
        get_last_chart_row_fn=_fake_reader(baseline),
    )
    assert (should, trigger) == (False, None)


def test_live_mode_interval_backstop_fires():
    now = datetime(2026, 7, 20, 10, 30, tzinfo=IST)
    baseline = {"as_of": now - timedelta(minutes=16), "trend_label": "Bullish intraday", "today_poc": 78000}
    should, trigger = should_render_chart(
        "SENSEX", "Bullish intraday", 78000, now, "live", bin_size=25,
        get_last_chart_row_fn=_fake_reader(baseline),
    )
    assert (should, trigger) == (True, "interval_backstop")


def test_live_mode_no_trigger_when_nothing_changed_and_within_backstop():
    now = datetime(2026, 7, 20, 10, 5, tzinfo=IST)
    baseline = {"as_of": now - timedelta(minutes=5), "trend_label": "Bullish intraday", "today_poc": 78000}
    should, trigger = should_render_chart(
        "SENSEX", "Bullish intraday", 78000, now, "live", bin_size=25,
        get_last_chart_row_fn=_fake_reader(baseline),
    )
    assert (should, trigger) == (False, None)
