import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from market_transition.research import extract_all_records, run_research
from tests.fixtures.synthetic_candles import make_candles


def _session_rows(tz_date: str, close_1459: float, close_1501: float, market_close: float) -> list[dict]:
    rows: list[dict] = []
    price = 100.0
    for t in pd.date_range("2026-01-01 09:15", "2026-01-01 13:59", freq="1min"):
        price += 0.01
        rows.append({"time": t.strftime("%H:%M"), "o": price, "h": price + 0.5, "l": price - 0.5, "c": price, "v": 100, "date": tz_date})
    pre_start = price
    for i, t in enumerate(pd.date_range("2026-01-01 14:00", "2026-01-01 14:59", freq="1min")):
        p = pre_start + (close_1459 - pre_start) * (i / 59)
        rows.append({"time": t.strftime("%H:%M"), "o": p, "h": p + 0.5, "l": p - 0.5, "c": p, "v": 100, "date": tz_date})
    rows[-1]["c"] = close_1459
    rows.append({"time": "15:00", "o": close_1459, "h": max(close_1459, close_1501), "l": min(close_1459, close_1501), "c": (close_1459 + close_1501) / 2, "v": 200, "date": tz_date})
    rows.append({"time": "15:01", "o": (close_1459 + close_1501) / 2, "h": max(close_1459, close_1501), "l": min(close_1459, close_1501), "c": close_1501, "v": 200, "date": tz_date})
    for i, t in enumerate(pd.date_range("2026-01-01 15:02", "2026-01-01 15:29", freq="1min")):
        p = close_1501 + (market_close - close_1501) * (i / 27)
        rows.append({"time": t.strftime("%H:%M"), "o": p, "h": p + 0.5, "l": p - 0.5, "c": p, "v": 100, "date": tz_date})
    rows[-1]["c"] = market_close
    return rows


def _multi_day_candles() -> pd.DataFrame:
    all_rows = []
    all_rows += _session_rows("2026-07-06", 150, 155, 165)  # Monday, continuation
    all_rows += _session_rows("2026-07-07", 150, 155, 148)  # Tuesday, reversal
    all_rows += _session_rows("2026-07-08", 150, 154, 162)  # Wednesday, continuation
    return make_candles(all_rows, tz_date="2026-07-06")


def test_extract_all_records_returns_one_per_complete_day():
    candles = _multi_day_candles()
    records = extract_all_records("NIFTY", candles, bin_size=1.0)
    assert len(records) == 3
    dates = {r.session_date.isoformat() for r in records}
    assert dates == {"2026-07-06", "2026-07-07", "2026-07-08"}


def test_extract_all_records_empty_for_no_candles():
    assert extract_all_records("NIFTY", make_candles([]), bin_size=1.0) == []


def test_run_research_produces_correlations_and_scores_for_every_record():
    candles = _multi_day_candles()
    records, correlations, scores = run_research("NIFTY", candles, bin_size=1.0)

    assert len(records) == 3
    assert len(correlations) > 0
    assert len(scores) == 3
    assert {s.session_date for s in scores} == {r.session_date for r in records}


def test_run_research_empty_when_no_candles():
    records, correlations, scores = run_research("NIFTY", make_candles([]), bin_size=1.0)
    assert records == []
    assert correlations == []
    assert scores == []
