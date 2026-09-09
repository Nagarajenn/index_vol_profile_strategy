"""Decision-layer tests: NO TRADE as a first-class outcome, gate ordering,
symbol independence, versioning and reproducibility.
"""

from datetime import date, datetime

import pytest

from paper_trading.config import DEFAULT_CONFIG, STRATEGY_VERSION, PaperConfig
from paper_trading.decision import decide
from paper_trading.models import PaperMarketState
from paper_trading.trend_assessment import assess_trend

SESSION = date(2026, 9, 8)
NOW = datetime(2026, 9, 8, 14, 59)
CFG = DEFAULT_CONFIG


def _state(symbol="NIFTY", **kw) -> PaperMarketState:
    s = PaperMarketState(
        symbol=symbol, session_date=SESSION, as_of=NOW,
        spot=24600.0, trend_label="Bullish", trend_score=2, vwap=24570.0,
        distance_from_vwap=30.0, vwap_slope=1.2, poc=24560.0, poc_migration=15.0,
        vah=24650.0, val=24500.0, support_low=24400.0, support_high=24450.0,
        resistance_low=24800.0, resistance_high=24850.0, atr_14=120.0,
        momentum_5min=20.0, momentum_15min=35.0, rvol_pct=160.0,
        dominant_side="buy", dominance_ratio=0.62, pcr=1.3,
        probability_up=0.62, probability_down=0.28, probability_no_move=0.10,
        expected_move_low=-40.0, expected_move_high=110.0,
        transition_risk_tier="MODERATE", n_analogs=14, data_quality="GOOD",
    )
    for k, v in kw.items():
        setattr(s, k, v)
    return s


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
        oc[str(strike)] = {
            # ATM premium ~150 with intrinsic on top -- realistic for an
            # index option with ATR 120, so the trade path is genuinely
            # exercised rather than always failing the premium budget.
            "ce": entry(max(spot - strike, 0.0) + 150, max(0.05, 0.55 - i * 0.05)),
            "pe": entry(max(strike - spot, 0.0) + 150, min(-0.05, -0.45 - i * 0.05)),
        }
    return {"expiry": date(2026, 9, 11), "last_price": spot, "oc": oc}


def _row(spot=24600.0):
    return {"fetched_at": None, "expiry": date(2026, 9, 11), "spot": spot, "raw_payload": _chain(spot)}


# --------------------------------------------------- NO TRADE is first class

def test_kill_switch_forces_no_trade():
    d = decide(_state(), CFG, option_at_1459=_row(), strike_step=50.0, kill_switch=True)
    assert d.decision == "NO_TRADE"
    assert d.no_trade_reason == "KILL_SWITCH_ACTIVE"


def test_risk_block_forces_no_trade():
    d = decide(_state(), CFG, option_at_1459=_row(), strike_step=50.0, account_block_reason="RISK_LIMIT")
    assert d.decision == "NO_TRADE"
    assert d.no_trade_reason == "RISK_LIMIT"


def test_insufficient_data_forces_no_trade():
    d = decide(_state(data_quality="INSUFFICIENT", missing_fields=["candles"]), CFG,
               option_at_1459=_row(), strike_step=50.0)
    assert d.decision == "NO_TRADE"
    assert d.no_trade_reason == "INSUFFICIENT_DATA"


def test_stale_option_snapshot_forces_no_trade():
    d = decide(_state(option_snapshot_age_sec=CFG.max_snapshot_age_sec + 1), CFG,
               option_at_1459=_row(), strike_step=50.0)
    assert d.decision == "NO_TRADE"
    assert d.no_trade_reason == "STALE_OPTION_DATA"


def test_neutral_market_forces_no_trade():
    flat = _state(trend_label="Neutral", distance_from_vwap=0.0, vwap_slope=0.0, poc_migration=0.0,
                  momentum_5min=0.0, dominance_ratio=0.5, pcr=1.0,
                  probability_up=0.5, probability_down=0.5)
    d = decide(flat, CFG, option_at_1459=_row(), strike_step=50.0)
    assert d.decision == "NO_TRADE"
    assert d.no_trade_reason in ("MARKET_TOO_FLAT", "NO_CLEAR_DIRECTION", "CONFLICTING_SIGNALS", "LOW_CONFIDENCE")


def test_missing_option_chain_forces_no_trade():
    d = decide(_state(), CFG, option_at_1459=None, strike_step=50.0)
    assert d.decision == "NO_TRADE"
    assert d.no_trade_reason in ("INSUFFICIENT_OPTION_DATA", "STALE_OPTION_DATA")


def test_no_trade_decision_still_records_the_full_market_state():
    """A NO TRADE day must still demonstrate the agent understood the
    market -- the state and the factor lists are populated regardless."""
    d = decide(_state(data_quality="INSUFFICIENT", missing_fields=["candles"]), CFG,
               option_at_1459=_row(), strike_step=50.0)
    assert d.state.spot is not None
    assert d.trend_assessment is not None
    assert d.explanation, "a NO TRADE must still explain itself"


def test_agent_is_never_obliged_to_trade():
    """Sanity: with a deliberately hostile config the agent declines rather
    than forcing a trade."""
    strict = PaperConfig(min_confidence=99)
    d = decide(_state(), strict, option_at_1459=_row(), strike_step=50.0)
    assert d.decision == "NO_TRADE"


# ------------------------------------------- trade path, versions, symbols

def test_a_clean_bullish_state_can_produce_a_trade_call():
    """The agent must be capable of trading, not merely of declining --
    otherwise the NO TRADE tests above would be vacuous."""
    d = decide(_state(), CFG, option_at_1459=_row(), strike_step=50.0)
    assert d.decision == "TRADE_CALL", f"expected a trade, got {d.no_trade_reason}"
    assert d.candidate.option_type == "CE"
    assert d.risk_plan.feasible
    assert d.risk_plan.stop_price < d.candidate.ask < d.risk_plan.target_price
    assert d.risk_plan.reward_risk >= CFG.min_reward_risk
    assert d.candidate.selection_rationale, "the chosen strike must record WHY"
    assert d.explanation, "a trade must explain itself"


def test_a_clean_bearish_state_selects_a_put_not_a_call():
    bearish = _state(trend_label="Strong Bearish", distance_from_vwap=-45.0, vwap_slope=-1.5,
                     poc_migration=-20.0, momentum_5min=-35.0, dominance_ratio=0.35, pcr=0.7,
                     probability_up=0.25, probability_down=0.65,
                     expected_move_low=-140.0, expected_move_high=30.0,
                     support_high=24300.0, support_low=24250.0,
                     resistance_low=24700.0, resistance_high=24750.0)
    d = decide(bearish, CFG, option_at_1459=_row(), strike_step=50.0)
    assert d.decision == "TRADE_PUT", f"expected a put, got {d.no_trade_reason}"
    assert d.candidate.option_type == "PE", "a bearish read must never buy a call"


def test_every_decision_records_strategy_and_configuration_versions():
    d = decide(_state(), CFG, option_at_1459=_row(), strike_step=50.0)
    assert d.strategy_version == STRATEGY_VERSION
    assert d.configuration_hash == CFG.config_hash()
    assert d.decision_version and d.configuration_version


def test_configuration_hash_changes_when_a_threshold_changes():
    """Results computed under different settings can never be pooled
    silently: any config edit changes the hash stamped on every decision."""
    other = PaperConfig(min_confidence=CFG.min_confidence + 1)
    assert other.config_hash() != CFG.config_hash()


def test_nifty_and_sensex_are_decided_independently():
    bullish_nifty = _state(symbol="NIFTY")
    flat_sensex = _state(symbol="SENSEX", trend_label="Neutral", distance_from_vwap=0.0,
                         vwap_slope=0.0, poc_migration=0.0, momentum_5min=0.0,
                         dominance_ratio=0.5, pcr=1.0, probability_up=0.5, probability_down=0.5)
    d1 = decide(bullish_nifty, CFG, option_at_1459=_row(), strike_step=50.0)
    d2 = decide(flat_sensex, CFG, option_at_1459=_row(), strike_step=100.0)
    assert d1.symbol == "NIFTY" and d2.symbol == "SENSEX"
    assert d2.decision == "NO_TRADE"  # one symbol declining never forces the other


def test_decision_is_reproducible_for_identical_inputs():
    """Same market data + same config + same strategy version => same
    decision, every time."""
    a = decide(_state(), CFG, option_at_1459=_row(), strike_step=50.0)
    b = decide(_state(), CFG, option_at_1459=_row(), strike_step=50.0)
    assert (a.decision, a.no_trade_reason, a.confidence, a.trend_assessment) == \
           (b.decision, b.no_trade_reason, b.confidence, b.trend_assessment)
    if a.candidate:
        assert (a.candidate.strike, a.candidate.option_type) == (b.candidate.strike, b.candidate.option_type)
        assert (a.risk_plan.stop_price, a.risk_plan.target_price) == (b.risk_plan.stop_price, b.risk_plan.target_price)


def test_trend_assessment_is_symmetric_between_long_and_short():
    """The agent must not be structurally more willing to go long."""
    bull = assess_trend(_state())
    bear = assess_trend(_state(trend_label="Strong Bearish", distance_from_vwap=-30.0, vwap_slope=-1.2,
                               poc_migration=-15.0, momentum_5min=-20.0, dominance_ratio=0.38,
                               pcr=0.7, probability_up=0.28, probability_down=0.62))
    assert bull.assessment.endswith("UP") and bear.assessment.endswith("DOWN")
    assert bull.score > 0 > bear.score


def test_conflicting_evidence_is_detected_and_listed():
    conflicted = _state(trend_label="Bullish", distance_from_vwap=25.0, vwap_slope=1.0,
                        momentum_5min=15.0, poc_migration=-18.0, dominance_ratio=0.38,
                        pcr=0.7, probability_up=0.30, probability_down=0.60,
                        resistance_low=24610.0)
    verdict = assess_trend(conflicted)
    assert verdict.conflicting_factors, "opposing evidence must be recorded, not averaged away"
