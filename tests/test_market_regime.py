import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from market_transition.market_regime import classify_market_regime, compute_volatility_pace_pct
from tests.fixtures.synthetic_candles import flat_candle, make_candles


def test_classify_market_regime_none_when_today_empty():
    assert classify_market_regime(make_candles([]), {}) is None


def test_classify_market_regime_volatile_when_range_far_exceeds_history():
    today = make_candles(
        [flat_candle("09:15", 100, 10), {"time": "09:20", "o": 100, "h": 150, "l": 90, "c": 120, "v": 10}],
        tz_date="2026-07-10",
    )
    historical = {
        "2026-07-08": make_candles(
            [flat_candle("09:15", 100, 10), flat_candle("09:20", 101, 10)], tz_date="2026-07-08"
        ),
        "2026-07-09": make_candles(
            [flat_candle("09:15", 100, 10), flat_candle("09:20", 99, 10)], tz_date="2026-07-09"
        ),
    }
    assert classify_market_regime(today, historical) == "Volatile"


def test_classify_market_regime_trending_when_low_vol_and_directional():
    # Small, steady same-direction moves -> low realized range relative to
    # history, and compute_rotation_factor should read "Trending".
    today = make_candles(
        [
            {"time": "09:15", "o": 100, "h": 101, "l": 100, "c": 101, "v": 10},
            {"time": "09:45", "o": 101, "h": 103, "l": 101, "c": 103, "v": 10},
            {"time": "10:15", "o": 103, "h": 105, "l": 103, "c": 105, "v": 10},
            {"time": "10:45", "o": 105, "h": 107, "l": 105, "c": 107, "v": 10},
        ],
        tz_date="2026-07-10",
    )
    historical = {
        "2026-07-08": make_candles(
            [
                {"time": "09:15", "o": 100, "h": 110, "l": 90, "c": 105, "v": 10},
                {"time": "10:45", "o": 105, "h": 115, "l": 85, "c": 100, "v": 10},
            ],
            tz_date="2026-07-08",
        ),
        "2026-07-09": make_candles(
            [
                {"time": "09:15", "o": 100, "h": 112, "l": 88, "c": 102, "v": 10},
                {"time": "10:45", "o": 102, "h": 116, "l": 84, "c": 101, "v": 10},
            ],
            tz_date="2026-07-09",
        ),
    }
    assert classify_market_regime(today, historical) == "Trending"


def test_classify_market_regime_range_bound_when_low_vol_and_alternating():
    today = make_candles(
        [
            {"time": "09:15", "o": 100, "h": 101, "l": 100, "c": 101, "v": 10},
            {"time": "09:45", "o": 101, "h": 101, "l": 98, "c": 99, "v": 10},
            {"time": "10:15", "o": 99, "h": 102, "l": 99, "c": 101, "v": 10},
            {"time": "10:45", "o": 101, "h": 101, "l": 97, "c": 98, "v": 10},
        ],
        tz_date="2026-07-10",
    )
    historical = {
        "2026-07-08": make_candles(
            [
                {"time": "09:15", "o": 100, "h": 110, "l": 90, "c": 105, "v": 10},
                {"time": "10:45", "o": 105, "h": 115, "l": 85, "c": 100, "v": 10},
            ],
            tz_date="2026-07-08",
        ),
    }
    assert classify_market_regime(today, historical) == "Range-Bound"


def test_compute_volatility_pace_pct_none_without_history():
    today = make_candles([flat_candle("09:15", 100, 10)])
    assert compute_volatility_pace_pct(today, {}) is None
