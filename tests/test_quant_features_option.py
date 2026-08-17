from datetime import datetime

import pytest

from option_chain.summary import summarize_option_chain
from quant_features.option_features import (
    build_strike_ladder,
    compute_intraday_oi_deltas,
    compute_option_feature_row,
)

STRIKES = [100, 105, 110, 115, 120, 125, 130, 135, 140]
SPOT = 117.0  # nearest strike is 115 (distance 2) vs 120 (distance 3)
ATM_STRIKE = 115.0
TS = datetime(2026, 7, 20, 10, 30)


def _chain(spot: float, oi_offset: int = 0, expiry: str = "2026-08-20") -> dict:
    oc = {}
    for strike in STRIKES:
        ce_oi = strike * 10 + oi_offset
        pe_oi = strike * 5 + oi_offset
        oc[f"{strike:.6f}"] = {
            "ce": {
                "oi": ce_oi,
                "previous_oi": 0,
                "volume": ce_oi * 2,
                "implied_volatility": 15.0,
                "last_price": 10.0,
                "greeks": {"delta": 0.5},
            },
            "pe": {
                "oi": pe_oi,
                "previous_oi": 0,
                "volume": pe_oi * 2,
                "implied_volatility": 12.0,
                "last_price": 8.0,
                "greeks": {"delta": -0.5},
            },
        }
    return {"oc": oc, "expiry": expiry, "last_price": spot}


def test_current_chain_none_returns_unavailable_row():
    result = compute_option_feature_row("NIFTY", TS, "v1", current_chain=None, previous_chain=None, atm_window_strikes=2)
    assert result.data_quality.option_data_unavailable is True
    assert result.spot is None
    assert result.strike_ladder == []


def test_empty_strikes_returns_unavailable_row():
    result = compute_option_feature_row(
        "NIFTY", TS, "v1", current_chain={"oc": {}, "expiry": "2026-08-20", "last_price": SPOT}, previous_chain=None, atm_window_strikes=2
    )
    assert result.data_quality.option_data_unavailable is True


def test_summary_fields_match_summarize_option_chain_directly():
    chain = _chain(SPOT)
    result = compute_option_feature_row("NIFTY", TS, "v1", current_chain=chain, previous_chain=None, atm_window_strikes=2)
    expected = summarize_option_chain(chain, atm_window_strikes=2)

    assert result.spot == expected.spot
    assert result.atm_strike == expected.atm_strike == ATM_STRIKE
    assert result.pcr == expected.pcr
    assert result.atm_iv_call == expected.atm_iv_call
    assert result.atm_iv_put == expected.atm_iv_put
    assert result.call_oi_wall_strike == expected.max_call_oi_strike
    assert result.put_oi_wall_strike == expected.max_put_oi_strike
    assert result.expiry.isoformat() == "2026-08-20"


def test_atm_iv_skew_is_call_minus_put():
    chain = _chain(SPOT)
    result = compute_option_feature_row("NIFTY", TS, "v1", current_chain=chain, previous_chain=None, atm_window_strikes=2)
    assert result.atm_iv_skew == pytest.approx(15.0 - 12.0)


def test_intraday_oi_delta_none_without_previous_chain():
    result = compute_option_feature_row("NIFTY", TS, "v1", current_chain=_chain(SPOT), previous_chain=None, atm_window_strikes=2)
    assert result.call_oi_delta_intraday is None
    assert result.put_oi_delta_intraday is None
    assert "no prior option_chain_raw snapshot" in " ".join(result.data_quality.notes)


def test_intraday_oi_delta_sums_near_atm_window():
    current = _chain(SPOT, oi_offset=100)
    previous = _chain(SPOT, oi_offset=0)
    call_delta, put_delta = compute_intraday_oi_deltas(current, previous, atm_window_strikes=2)
    # atm_idx=3 (strike 115); window [1,5] -> strikes 105,110,115,120,125 -> 5 strikes, delta=100 each leg
    assert call_delta == pytest.approx(500.0)
    assert put_delta == pytest.approx(500.0)


def test_intraday_oi_delta_via_full_row():
    current = _chain(SPOT, oi_offset=100)
    previous = _chain(SPOT, oi_offset=0)
    result = compute_option_feature_row("NIFTY", TS, "v1", current_chain=current, previous_chain=previous, atm_window_strikes=2)
    assert result.call_oi_delta_intraday == pytest.approx(500.0)
    assert result.put_oi_delta_intraday == pytest.approx(500.0)
    assert result.data_quality.notes == []


def test_strike_ladder_width_and_moneyness():
    chain = _chain(SPOT)
    ladder = build_strike_ladder(chain, previous_chain=None, ladder_width=3)
    # atm_idx=3 (strike 115); lo=0, hi=7 -> strikes 100..130 (7 strikes) x 2 legs
    assert len(ladder) == 14

    by_key = {(e.strike, e.option_type): e for e in ladder}
    assert by_key[(115.0, "CE")].moneyness == "ATM"
    assert by_key[(115.0, "PE")].moneyness == "ATM"
    assert by_key[(100.0, "CE")].moneyness == "ITM"  # strike < spot -> call ITM
    assert by_key[(130.0, "CE")].moneyness == "OTM"
    assert by_key[(100.0, "PE")].moneyness == "OTM"  # strike < spot -> put OTM
    assert by_key[(130.0, "PE")].moneyness == "ITM"


def test_strike_ladder_carries_oi_volume_iv_ltp_delta():
    chain = _chain(SPOT)
    ladder = build_strike_ladder(chain, previous_chain=None, ladder_width=1)
    entry = next(e for e in ladder if e.strike == 115.0 and e.option_type == "CE")
    assert entry.oi == 115 * 10
    assert entry.volume == 115 * 10 * 2
    assert entry.iv == 15.0
    assert entry.ltp == 10.0
    assert entry.delta == 0.5
    assert entry.oi_delta_intraday is None  # no previous chain supplied


def test_strike_ladder_oi_delta_per_strike():
    current = _chain(SPOT, oi_offset=50)
    previous = _chain(SPOT, oi_offset=0)
    ladder = build_strike_ladder(current, previous, ladder_width=1)
    entry = next(e for e in ladder if e.strike == 115.0 and e.option_type == "CE")
    assert entry.oi_delta_intraday == pytest.approx(50.0)
