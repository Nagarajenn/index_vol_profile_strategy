import sys
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.models import RawCandle
from app.services.dashboard_service import DashboardService


def _candle(day: int, hour: int, minute: int) -> RawCandle:
    return RawCandle(
        symbol="NIFTY",
        timestamp=datetime(2026, 7, day, hour, minute, tzinfo=timezone.utc),
        open=100.0,
        high=101.0,
        low=99.0,
        close=100.5,
        volume=10.0,
    )


def test_keeps_only_today_when_no_prior_data():
    rows = [_candle(21, 9, 15), _candle(21, 9, 16)]
    trimmed = DashboardService._trim_to_prev_and_current_session(rows, today=date(2026, 7, 21))
    assert [r.timestamp.date() for r in trimmed] == [date(2026, 7, 21), date(2026, 7, 21)]


def test_keeps_most_recent_prior_session_plus_today():
    rows = [_candle(17, 15, 25), _candle(20, 9, 15), _candle(20, 15, 25), _candle(21, 9, 15)]
    trimmed = DashboardService._trim_to_prev_and_current_session(rows, today=date(2026, 7, 21))
    dates = {r.timestamp.date() for r in trimmed}
    assert dates == {date(2026, 7, 20), date(2026, 7, 21)}
    assert date(2026, 7, 17) not in dates


def test_skips_weekend_and_holiday_gap_automatically():
    # Friday 17th has data, Sat/Sun/Monday holiday have none, today is Tuesday 21st.
    rows = [_candle(17, 9, 15), _candle(17, 15, 25), _candle(21, 9, 15)]
    trimmed = DashboardService._trim_to_prev_and_current_session(rows, today=date(2026, 7, 21))
    dates = {r.timestamp.date() for r in trimmed}
    assert dates == {date(2026, 7, 17), date(2026, 7, 21)}


def test_empty_input_returns_empty():
    assert DashboardService._trim_to_prev_and_current_session([], today=date(2026, 7, 21)) == []
