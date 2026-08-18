import math
from datetime import date as date_cls

import pandas as pd
import pytest

from config.instruments import INSTRUMENTS
from quant_features.engine import (
    WARMUP_MIN_CANDLES,
    compute_forward_outcomes_row,
    compute_market_features_row,
    compute_option_features_row,
)
from quant_features.labeling import compute_forward_outcome_row
from quant_features.option_features import compute_option_feature_row
from tests.fixtures.synthetic_candles import make_candles

NIFTY_META = INSTRUMENTS["NIFTY"]
BIN_SIZE = NIFTY_META["volume_profile_bin_size"]


def _minute_time(i: int) -> str:
    minute = 15 + i
    hh = 9 + minute // 60
    mm = minute % 60
    return f"{hh:02d}:{mm:02d}"


def _zigzag_session(n_minutes: int, date_str: str, base: float = 100.0) -> pd.DataFrame:
    rows = []
    for i in range(n_minutes):
        price = base + 5 * math.sin(i / 6) + i * 0.02
        rows.append(
            {
                "time": _minute_time(i),
                "date": date_str,
                "o": price - 0.2,
                "h": price + 1.0,
                "l": price - 1.0,
                "c": price,
                "v": 300 + (i % 7) * 40,
            }
        )
    return make_candles(rows)


@pytest.fixture
def today_candles():
    return _zigzag_session(150, "2026-07-15")


@pytest.fixture
def historical_by_date():
    return {
        date_cls(2026, 7, d): _zigzag_session(150, f"2026-07-{d:02d}", base=95.0 + d) for d in range(1, 15)
    }


@pytest.fixture
def prior_day_candles():
    return _zigzag_session(150, "2026-07-14", base=98.0)


def test_market_features_row_basic_wiring(today_candles, historical_by_date, prior_day_candles):
    prior_day_ohlc = {
        "high": float(prior_day_candles["high"].max()),
        "low": float(prior_day_candles["low"].min()),
        "close": float(prior_day_candles["close"].iloc[-1]),
    }
    row = compute_market_features_row(
        "NIFTY",
        today_candles,
        historical_by_date,
        NIFTY_META,
        prior_day_candles_1min=prior_day_candles,
        prior_day_ohlc=prior_day_ohlc,
        prior_day_close=prior_day_ohlc["close"],
    )

    assert row.symbol == "NIFTY"
    assert row.timestamp == today_candles["timestamp"].iloc[-1].to_pydatetime()
    assert row.feature_version == "v1"
    assert row.price.close == pytest.approx(float(today_candles["close"].iloc[-1]))
    assert row.vwap.vwap_now is not None
    assert row.volume_profile.today_poc is not None
    assert row.volume_intelligence.volume_trend_label is not None
    assert row.decision.trend_label is not None
    assert row.regime.market_regime_3way is not None
    assert row.expiry.day_of_week == 2  # 2026-07-15 is a Wednesday
    assert row.news.event_count_30m == 0  # no events supplied


def test_market_features_row_matches_compute_levels_directly(today_candles, historical_by_date):
    from analytics.levels import compute_levels

    row = compute_market_features_row("NIFTY", today_candles, historical_by_date, NIFTY_META)
    direct_levels = compute_levels("NIFTY", today_candles, NIFTY_META)

    assert row.decision.trend_label == direct_levels.trend.label
    assert row.decision.trend_score == direct_levels.trend.score
    assert row.decision.confidence_score == direct_levels.confidence.score


def test_market_features_row_data_quality_flags_thin_session(historical_by_date):
    thin_candles = _zigzag_session(3, "2026-07-15")
    row = compute_market_features_row("NIFTY", thin_candles, historical_by_date, NIFTY_META)
    assert row.data_quality.warmup_incomplete is True
    assert len(thin_candles) < WARMUP_MIN_CANDLES


def test_market_features_row_data_quality_flags_missing_context(today_candles):
    row = compute_market_features_row("NIFTY", today_candles, {}, NIFTY_META)
    assert row.data_quality.baseline_thin is True
    assert row.data_quality.option_data_unavailable is True
    assert row.data_quality.news_data_unavailable is True


def test_market_features_row_full_session_not_flagged_warmup(today_candles, historical_by_date):
    row = compute_market_features_row("NIFTY", today_candles, historical_by_date, NIFTY_META)
    assert row.data_quality.warmup_incomplete is False


def test_compute_option_features_row_delegates_to_option_features_module():
    chain = {
        "oc": {
            "100.000000": {"ce": {"oi": 1000, "previous_oi": 0}, "pe": {"oi": 500, "previous_oi": 0}},
            "105.000000": {"ce": {"oi": 1200, "previous_oi": 0}, "pe": {"oi": 600, "previous_oi": 0}},
        },
        "expiry": "2026-08-20",
        "last_price": 102.0,
    }
    timestamp = pd.Timestamp("2026-07-15 10:30", tz="Asia/Kolkata").to_pydatetime()

    via_engine = compute_option_features_row("NIFTY", timestamp, chain, None, atm_window_strikes=2)
    direct = compute_option_feature_row("NIFTY", timestamp, "v1", chain, None, atm_window_strikes=2)

    assert via_engine == direct


def test_compute_forward_outcomes_row_delegates_to_labeling_module(today_candles):
    timestamp = today_candles["timestamp"].iloc[0]
    via_engine = compute_forward_outcomes_row("NIFTY", timestamp, today_candles, t_index=0, atr_at_t=1.5)
    direct = compute_forward_outcome_row("NIFTY", timestamp, "v1", today_candles, t_index=0, atr_at_t=1.5)
    assert via_engine == direct
