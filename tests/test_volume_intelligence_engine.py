from datetime import date, timedelta

import pandas as pd

from analytics.volume_intelligence.engine import compute_volume_intelligence
from market_transition.expiry_calendar import build_expiry_calendar
from tests.fixtures.synthetic_candles import make_candles


def _session_candles(date_str: str, n: int = 30, base_price: float = 100.0, base_volume: float = 100.0) -> pd.DataFrame:
    rows = []
    price = base_price
    for i in range(n):
        minute = 15 + i
        hh = 9 + minute // 60
        mm = minute % 60
        price += 0.3
        v = base_volume + (i % 5) * 10
        rows.append({"time": f"{hh:02d}:{mm:02d}", "o": price - 0.3, "h": price + 0.5, "l": price - 0.6, "c": price, "v": v, "date": date_str})
    return make_candles(rows)


def test_engine_full_orchestration_smoke():
    today = date(2026, 8, 1)
    today_df = _session_candles(today.isoformat(), n=30)
    historical_by_date = {today - timedelta(days=i): _session_candles((today - timedelta(days=i)).isoformat(), n=30) for i in range(1, 26)}

    result = compute_volume_intelligence("NIFTY", today_df, historical_by_date)

    assert result.symbol == "NIFTY"
    assert result.as_of is not None
    assert result.rvol is not None
    assert result.acceleration is not None
    assert result.dominance is not None
    assert result.cumulative_pressure is not None
    assert result.momentum is not None
    assert result.institutional is not None
    assert result.spike is not None
    assert result.dryup is not None
    assert result.absorption is not None
    assert result.exhaustion is not None
    assert result.trend is not None
    assert result.character is not None
    assert result.similarity is not None
    assert result.forecast is not None
    assert result.narrative is not None
    assert result.narrative.headline != ""


def test_engine_empty_today_candles_returns_all_none():
    result = compute_volume_intelligence("NIFTY", make_candles([]), {})

    assert result.as_of is None
    assert result.rvol is None
    assert result.forecast is None
    assert result.narrative is None


def test_engine_single_candle_session_does_not_crash():
    today_df = _session_candles("2026-08-01", n=1)

    result = compute_volume_intelligence("NIFTY", today_df, {})

    assert result.as_of is not None
    assert result.acceleration is None
    assert result.trend is None


def test_engine_no_historical_data_still_computes_intraday_metrics():
    today_df = _session_candles("2026-08-01", n=30)

    result = compute_volume_intelligence("NIFTY", today_df, {})

    assert result.as_of is not None
    assert result.dominance is not None
    assert result.momentum is not None
    assert result.trend is not None
    assert result.rvol is not None
    assert result.rvol.primary is None


def test_engine_accepts_expiry_calendar_param():
    today = date(2026, 8, 4)
    calendar = build_expiry_calendar("NIFTY", today - timedelta(days=60), today)
    today_df = _session_candles(today.isoformat(), n=30)
    historical_by_date = {today - timedelta(days=i): _session_candles((today - timedelta(days=i)).isoformat(), n=30) for i in range(1, 10)}

    result = compute_volume_intelligence("NIFTY", today_df, historical_by_date, expiry_calendar=calendar)

    assert result.as_of is not None
