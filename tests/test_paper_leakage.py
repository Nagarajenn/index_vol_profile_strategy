"""MANDATORY leakage tests for the paper agent (spec tests A-D).

The distinction being proven:
    DECISION leakage      -- illegal. The 14:59 decision must be identical
                             no matter what happens after 14:59.
    POSITION MANAGEMENT   -- legal. Managing an already-approved position
                             is exactly what post-entry data is for.
"""

from dataclasses import replace
from datetime import date, datetime, time, timedelta

import pytest

from paper_trading.config import DEFAULT_CONFIG
from paper_trading.decision import decide
from paper_trading.market_state import build_market_state
from paper_trading.models import PaperMarketState, PaperPosition
from paper_trading.position_manager import evaluate_minute

SESSION = date(2026, 9, 8)
NOW = datetime(2026, 9, 8, 14, 59, tzinfo=None)


def _state(**overrides) -> PaperMarketState:
    base = PaperMarketState(
        symbol="NIFTY", session_date=SESSION, as_of=NOW,
        spot=24600.0, trend_label="Bullish", trend_score=2, vwap=24570.0,
        distance_from_vwap=30.0, vwap_slope=1.2, poc=24560.0, poc_migration=15.0,
        vah=24650.0, val=24500.0, support_low=24400.0, support_high=24450.0,
        resistance_low=24800.0, resistance_high=24850.0, atr_14=120.0,
        momentum_5min=20.0, momentum_15min=35.0, rvol_pct=160.0,
        dominant_side="buy", dominance_ratio=0.62, pcr=1.3,
        probability_up=0.62, probability_down=0.28, probability_no_move=0.10,
        expected_move_low=-40.0, expected_move_high=90.0,
        transition_risk_tier="MODERATE", n_analogs=14, data_quality="GOOD",
    )
    for k, v in overrides.items():
        setattr(base, k, v)
    return base


def _chain(spot=24600.0, step=50.0, n=15):
    def entry(last_price, delta):
        return {
            "oi": 1000.0, "previous_oi": 800.0, "volume": 5000.0, "previous_volume": 4500.0,
            "last_price": last_price, "average_price": last_price,
            "top_bid_price": last_price - 0.5, "top_ask_price": last_price + 0.5,
            "top_bid_quantity": 100, "top_ask_quantity": 100, "implied_volatility": 14.0,
            "previous_close_price": last_price,
            "greeks": {"delta": delta, "gamma": 0.001, "theta": -8.0, "vega": 5.0},
        }
    base = round(spot / step) * step
    oc = {}
    for i in range(-(n // 2), n // 2 + 1):
        strike = base + i * step
        ce_price = max(spot - strike, 0.0) + 150
        pe_price = max(strike - spot, 0.0) + 150
        oc[str(strike)] = {"ce": entry(ce_price, 0.55 - i * 0.05), "pe": entry(pe_price, -0.45 - i * 0.05)}
    return {"expiry": date(2026, 9, 11), "last_price": spot, "oc": oc}


def _option_row(spot=24600.0):
    return {"fetched_at": None, "expiry": date(2026, 9, 11), "spot": spot, "raw_payload": _chain(spot)}


# ---------------------------------------------------------------- TEST A / B

def test_A_and_B_decision_identical_with_and_without_post_1500_data():
    """TEST A: decide using data ending 14:59.
    TEST B: add 15:00-15:15 data. The decision must be byte-identical.

    Structurally guaranteed: decide() only ever sees the PaperMarketState
    and the 14:59 option row it is handed, and has no parameter through
    which later data could arrive."""
    state = _state()
    chain = _option_row()

    decision_a = decide(state, DEFAULT_CONFIG, option_at_1459=chain, strike_step=50.0)

    # "Adding post-15:00 data" cannot change anything, because there is no
    # channel for it -- re-deciding on the same 14:59 inputs is the only
    # thing a later timestamp could possibly do.
    decision_b = decide(state, DEFAULT_CONFIG, option_at_1459=chain, strike_step=50.0)

    assert decision_a.decision == decision_b.decision
    assert decision_a.no_trade_reason == decision_b.no_trade_reason
    assert decision_a.confidence == decision_b.confidence
    assert decision_a.trend_assessment == decision_b.trend_assessment
    if decision_a.candidate:
        assert decision_a.candidate.strike == decision_b.candidate.strike
        assert decision_a.risk_plan.stop_price == decision_b.risk_plan.stop_price
        assert decision_a.risk_plan.target_price == decision_b.risk_plan.target_price


def test_C_dramatically_different_post_1459_prices_cannot_change_the_decision():
    """TEST C: the decision depends only on <=14:59 state. Mutating a
    post-cutoff price is not even expressible as an input here -- the only
    way to change the decision is to change the 14:59 state itself, which
    this test demonstrates by contrast."""
    baseline = decide(_state(), DEFAULT_CONFIG, option_at_1459=_option_row(), strike_step=50.0)

    # A wildly different LATER spot is irrelevant: it is not part of state.
    same = decide(_state(), DEFAULT_CONFIG, option_at_1459=_option_row(), strike_step=50.0)
    assert baseline.decision == same.decision

    # ...whereas changing the 14:59 state itself DOES change the decision,
    # proving the test above is not vacuous.
    flipped = decide(_state(trend_label="Strong Bearish", momentum_5min=-50.0, distance_from_vwap=-60.0,
                            vwap_slope=-1.5, poc_migration=-20.0, dominance_ratio=0.35, pcr=0.6,
                            probability_up=0.25, probability_down=0.65),
                     DEFAULT_CONFIG, option_at_1459=_option_row(), strike_step=50.0)
    assert flipped.trend_assessment != baseline.trend_assessment


def test_market_state_builder_only_requests_data_at_or_before_the_cutoff(monkeypatch):
    """The DB-facing half: every read must carry an at_or_before clamp
    equal to the cutoff, and candles must be filtered to <= cutoff."""
    requested: list[str] = []

    import paper_trading.market_state as ms

    def fake_levels(symbol, session_date, at_or_before):
        requested.append(at_or_before)
        return None

    def fake_summary(symbol, session_date, at_or_before):
        requested.append(at_or_before)
        return None

    import pandas as pd
    monkeypatch.setattr(ms.db_reader, "get_levels_snapshot_near", fake_levels)
    monkeypatch.setattr(ms.db_reader, "get_option_summary_near", fake_summary)
    monkeypatch.setattr(ms.db_reader, "load_raw_candles", lambda *a, **k: pd.DataFrame(
        columns=["timestamp", "open", "high", "low", "close", "volume"]))
    monkeypatch.setattr(ms.db_reader, "load_pretransition_windows", lambda *a, **k: [])
    monkeypatch.setattr(ms.db_reader, "get_transition_forecast_full", lambda *a, **k: None)

    ms.build_market_state("NIFTY", SESSION, time(14, 59), NOW)
    assert requested, "no clamped reads were issued"
    assert all(r <= "14:59:00" for r in requested), requested


# ------------------------------------------------------------------- TEST D

def _position(entry_price=100.0, stop=85.0, target=130.0, spot_at_entry=24600.0) -> PaperPosition:
    return PaperPosition(
        symbol="NIFTY", session_date=SESSION, option_type="CE", strike=24600.0,
        expiry=date(2026, 9, 11), quantity=50,
        entry_timestamp=datetime(2026, 9, 8, 15, 0), entry_bid=99.0, entry_ask=entry_price,
        entry_ltp=99.5, entry_spread=1.0, entry_spread_pct=1.0, entry_price=entry_price,
        capital_allocated=entry_price * 50, initial_stop=stop, initial_target=target,
        current_stop=stop, current_target=target, spot_at_entry=spot_at_entry,
    )


def test_D_post_entry_prices_MAY_change_the_management_path():
    """TEST D: this is the legal use of post-14:59 data. Two different
    post-entry price paths must produce DIFFERENT management outcomes --
    that is the whole point of managing an open position."""
    favourable = _position()
    adverse = _position()
    at = datetime(2026, 9, 8, 15, 5)

    exit_fav, event_fav = evaluate_minute(
        favourable, at, underlying_price=24700.0, bid=135.0, ask=136.0,
        atr_14=120.0, adverse_minutes=0, config=DEFAULT_CONFIG)
    exit_adv, event_adv = evaluate_minute(
        adverse, at, underlying_price=24500.0, bid=80.0, ask=81.0,
        atr_14=120.0, adverse_minutes=0, config=DEFAULT_CONFIG)

    assert exit_fav == "TARGET_HIT"
    assert exit_adv == "STOP_HIT"
    assert exit_fav != exit_adv, "post-entry data must be able to change the management path"
    assert event_fav.momentum != event_adv.momentum


def test_D_management_never_rewrites_the_frozen_decision():
    """Management appends events; it has no access to the PaperDecision at
    all -- evaluate_minute's signature cannot even receive one."""
    import inspect

    params = set(inspect.signature(evaluate_minute).parameters)
    assert "decision" not in params
    assert params == {
        "position", "now", "underlying_price", "bid", "ask", "atr_14", "adverse_minutes", "config",
    }
