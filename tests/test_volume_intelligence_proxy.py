import pytest

from analytics.volume_intelligence.proxy import attach_buy_sell_columns
from tests.fixtures.synthetic_candles import make_candles


def test_close_near_high_is_mostly_buy():
    df = make_candles([{"time": "09:15", "o": 100, "h": 110, "l": 90, "c": 105, "v": 1000}])
    result = attach_buy_sell_columns(df)
    # mfm = ((105-90)-(110-105))/(110-90) = (15-5)/20 = 0.5
    assert result["mfm"].iloc[0] == pytest.approx(0.5)
    assert result["buy_volume"].iloc[0] == pytest.approx(500.0)
    assert result["sell_volume"].iloc[0] == pytest.approx(0.0)


def test_close_near_low_is_mostly_sell():
    df = make_candles([{"time": "09:15", "o": 100, "h": 110, "l": 90, "c": 92, "v": 1000}])
    result = attach_buy_sell_columns(df)
    # mfm = ((92-90)-(110-92))/20 = (2-18)/20 = -0.8
    assert result["mfm"].iloc[0] == pytest.approx(-0.8)
    assert result["buy_volume"].iloc[0] == pytest.approx(0.0)
    assert result["sell_volume"].iloc[0] == pytest.approx(800.0)


def test_flat_candle_has_no_directional_volume():
    df = make_candles([{"time": "09:15", "o": 100, "h": 100, "l": 100, "c": 100, "v": 500}])
    result = attach_buy_sell_columns(df)
    assert result["mfm"].iloc[0] == 0.0
    assert result["buy_volume"].iloc[0] == 0.0
    assert result["sell_volume"].iloc[0] == 0.0


def test_buy_plus_sell_never_exceeds_volume():
    df = make_candles(
        [
            {"time": "09:15", "o": 100, "h": 110, "l": 90, "c": 105, "v": 1000},
            {"time": "09:16", "o": 105, "h": 108, "l": 100, "c": 101, "v": 800},
            {"time": "09:17", "o": 101, "h": 101, "l": 101, "c": 101, "v": 200},
        ]
    )
    result = attach_buy_sell_columns(df)
    assert (result["buy_volume"] + result["sell_volume"] <= result["volume"] + 1e-9).all()


def test_empty_dataframe_returns_empty_with_columns():
    df = make_candles([])
    result = attach_buy_sell_columns(df)
    assert result.empty
    assert set(["mfm", "buy_volume", "sell_volume"]).issubset(result.columns)
