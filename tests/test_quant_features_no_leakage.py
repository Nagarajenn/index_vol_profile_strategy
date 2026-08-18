"""Mandatory leakage-guard suite (per the Quant Feature Store plan): for
every module built on quant_features.cutoff.truncate_candles, computing
features from `truncate_candles(candles, cutoff)` must produce IDENTICAL
output whether or not `candles` happens to contain adversarial data after
`cutoff` -- proving the truncate-before-you-compute pattern this whole
package relies on is actually leak-proof, not just documented as such.

quant_features/labeling.py has the opposite-direction guarantee (never look
AT-OR-BEFORE t_index) and its own dedicated tests in
test_quant_features_labeling.py.
"""

from datetime import date

import pandas as pd
import pytest

from analytics.vwap import compute_vwap
from quant_features.cutoff import historical_by_date_before, truncate_candles
from quant_features.price_features import compute_price_volatility_features
from quant_features.regime_features import compute_regime_feature_set
from quant_features.volume_intelligence_features import compute_volume_intelligence_feature_set
from quant_features.volume_profile_features import compute_volume_profile_feature_set
from quant_features.vwap_features import compute_vwap_features
from tests.fixtures.synthetic_candles import make_candles

BIN_SIZE = 5.0


def _minute_time(i: int) -> str:
    minute = 15 + i
    hh = 9 + minute // 60
    mm = minute % 60
    return f"{hh:02d}:{mm:02d}"


def _base_session(n_minutes: int, date_str: str = "2026-07-10") -> pd.DataFrame:
    rows = []
    price = 100.0
    for i in range(n_minutes):
        price += 0.3 if i % 4 != 0 else -0.2
        rows.append(
            {
                "time": _minute_time(i),
                "date": date_str,
                "o": price - 0.1,
                "h": price + 0.4,
                "l": price - 0.4,
                "c": price,
                "v": 400 + (i % 6) * 50,
            }
        )
    return make_candles(rows)


def _adversarial_tail(start_i: int, n_minutes: int, date_str: str) -> pd.DataFrame:
    """Wildly different prices/volumes appended after the cutoff -- if any
    module accidentally reads past its truncated input, these values would
    visibly corrupt the result."""
    rows = []
    for j in range(n_minutes):
        i = start_i + j
        price = 9999.0 + j
        rows.append(
            {
                "time": _minute_time(i),
                "date": date_str,
                "o": price,
                "h": price + 500,
                "l": price - 500,
                "c": price,
                "v": 5_000_000,
            }
        )
    return make_candles(rows)


def _historical_by_date() -> dict[date, pd.DataFrame]:
    return {
        pd.Timestamp(f"2026-07-{d:02d}").date(): _base_session(60, f"2026-07-{d:02d}") for d in range(1, 9)
    }


@pytest.fixture
def base_and_extended():
    base = _base_session(40)
    tail = _adversarial_tail(40, 60, "2026-07-10")
    extended = pd.concat([base, tail], ignore_index=True)
    cutoff_ts = base["timestamp"].iloc[-1]
    return base, extended, cutoff_ts


def test_truncate_candles_itself_produces_identical_frames(base_and_extended):
    base, extended, cutoff_ts = base_and_extended
    from_base = truncate_candles(base, cutoff_ts).reset_index(drop=True)
    from_extended = truncate_candles(extended, cutoff_ts).reset_index(drop=True)
    pd.testing.assert_frame_equal(from_base, from_extended)


def test_price_volatility_features_no_leakage(base_and_extended):
    base, extended, cutoff_ts = base_and_extended
    from_base = truncate_candles(base, cutoff_ts)
    from_extended = truncate_candles(extended, cutoff_ts)
    result_base = compute_price_volatility_features(from_base, prior_day_close=95.0)
    result_extended = compute_price_volatility_features(from_extended, prior_day_close=95.0)
    assert result_base == result_extended


def test_vwap_features_no_leakage(base_and_extended):
    base, extended, cutoff_ts = base_and_extended
    from_base = truncate_candles(base, cutoff_ts)
    from_extended = truncate_candles(extended, cutoff_ts)
    vwap_base = compute_vwap(from_base)
    vwap_extended = compute_vwap(from_extended)
    result_base = compute_vwap_features(vwap_base, close=float(from_base["close"].iloc[-1]), atr_14=2.0)
    result_extended = compute_vwap_features(vwap_extended, close=float(from_extended["close"].iloc[-1]), atr_14=2.0)
    assert result_base == result_extended


def test_volume_profile_features_no_leakage(base_and_extended):
    base, extended, cutoff_ts = base_and_extended
    from_base = truncate_candles(base, cutoff_ts)
    from_extended = truncate_candles(extended, cutoff_ts)
    historical = _historical_by_date()
    close = float(from_base["close"].iloc[-1])
    result_base = compute_volume_profile_feature_set(from_base, historical, BIN_SIZE, close)
    result_extended = compute_volume_profile_feature_set(from_extended, historical, BIN_SIZE, close)
    assert result_base == result_extended


def test_volume_intelligence_features_no_leakage(base_and_extended):
    base, extended, cutoff_ts = base_and_extended
    from_base = truncate_candles(base, cutoff_ts)
    from_extended = truncate_candles(extended, cutoff_ts)
    historical = _historical_by_date()
    result_base = compute_volume_intelligence_feature_set("NIFTY", from_base, historical)
    result_extended = compute_volume_intelligence_feature_set("NIFTY", from_extended, historical)
    assert result_base == result_extended


def test_regime_features_no_leakage(base_and_extended):
    base, extended, cutoff_ts = base_and_extended
    from_base = truncate_candles(base, cutoff_ts)
    from_extended = truncate_candles(extended, cutoff_ts)
    historical = _historical_by_date()
    result_base = compute_regime_feature_set(from_base, historical, trend=None)
    result_extended = compute_regime_feature_set(from_extended, historical, trend=None)
    assert result_base == result_extended


def test_historical_by_date_before_excludes_today_and_future_dates():
    session_date = date(2026, 7, 10)
    historical = {
        date(2026, 7, 8): pd.DataFrame(),
        date(2026, 7, 9): pd.DataFrame(),
        date(2026, 7, 10): pd.DataFrame(),  # today -- must be excluded
        date(2026, 7, 11): pd.DataFrame(),  # future -- must be excluded
    }
    filtered = historical_by_date_before(historical, session_date)
    assert set(filtered) == {date(2026, 7, 8), date(2026, 7, 9)}
