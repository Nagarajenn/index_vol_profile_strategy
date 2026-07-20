import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.models import LevelsSnapshot
from app.services.interpretation import build_interpretation


def _row(**overrides) -> LevelsSnapshot:
    defaults = dict(
        symbol="SENSEX",
        close=100.0,
        vwap_now=None,
        today_poc=None,
        trend_label=None,
        institutional_bias_label=None,
    )
    defaults.update(overrides)
    return LevelsSnapshot(**defaults)


def test_none_when_trend_label_missing():
    row = _row(trend_label=None)
    assert build_interpretation(row) is None


def test_normal_case_above_vwap_and_poc_with_bias():
    row = _row(
        close=100.0,
        vwap_now=95.0,
        today_poc=98.0,
        trend_label="Strong Bullish",
        institutional_bias_label="Mildly Bullish",
    )
    result = build_interpretation(row)
    assert result == (
        "Price is trading above VWAP and above today's POC, consistent with a strong bullish trend. "
        "Institutional positioning is currently mildly bullish."
    )


def test_below_vwap_and_poc():
    row = _row(close=90.0, vwap_now=95.0, today_poc=98.0, trend_label="Bearish")
    result = build_interpretation(row)
    assert result.startswith("Price is trading below VWAP and below today's POC")


def test_price_exactly_at_vwap_and_poc():
    row = _row(close=100.0, vwap_now=100.0, today_poc=100.0, trend_label="Neutral")
    result = build_interpretation(row)
    assert "trading at VWAP" in result
    assert "at today's POC" in result


def test_falls_back_to_trend_only_when_vwap_and_poc_both_missing():
    row = _row(vwap_now=None, today_poc=None, trend_label="Neutral")
    assert build_interpretation(row) == "Trend reads neutral."


def test_unavailable_institutional_bias_is_excluded():
    row = _row(
        close=100.0,
        vwap_now=95.0,
        today_poc=98.0,
        trend_label="Bullish",
        institutional_bias_label="Unavailable (historical)",
    )
    result = build_interpretation(row)
    assert "Institutional positioning" not in result


def test_neutral_trend_reads_naturally_with_price_context():
    row = _row(close=100.0, vwap_now=99.0, today_poc=101.0, trend_label="Neutral")
    result = build_interpretation(row)
    assert result == "Price is trading above VWAP and below today's POC, consistent with a neutral trend."
