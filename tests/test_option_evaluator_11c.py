"""Milestone 11C tests: aggregation/statistics (evaluate_engine,
evaluate_baseline), deterministic output, and small-segment handling."""

from market_transition.option_evaluator_11c import MIN_N_FOR_SEGMENT, evaluate_baseline, evaluate_engine


def _traded_record(symbol="NIFTY", direction_state="up", underlying_direction="up", pnl=5.0, mfe=8.0, mae=-3.0, opt_type="CE", bucket="ATM", spread_pct=1.0, expiry_type="weekly", confidence="3-0"):
    return {
        "symbol": symbol, "session_date": "2026-08-10", "direction_state": direction_state,
        "underlying_direction": underlying_direction, "selection_reason": "SELECTED",
        "selected_option_type": opt_type, "selected_moneyness_bucket": bucket, "selected_spread_pct": spread_pct,
        "expiry_type": expiry_type, "confidence_tier": confidence,
        "outcome": {"final_pct_return": pnl, "mfe_pct": mfe, "mae_pct": mae},
    }


def _no_trade_record(reason="NO_TRADE_NO_CLEAR_EDGE", direction_state=None, underlying_direction="up"):
    return {
        "symbol": "NIFTY", "session_date": "2026-08-11", "direction_state": direction_state,
        "underlying_direction": underlying_direction, "selection_reason": reason,
        "selected_option_type": None, "selected_moneyness_bucket": None, "selected_spread_pct": None,
        "expiry_type": "weekly", "confidence_tier": None,
    }


def test_evaluate_engine_basic_counts_and_pnl_stats():
    records = [
        _traded_record(pnl=5.0),
        _traded_record(pnl=-2.0, underlying_direction="down"),  # direction wrong for this trade
        _no_trade_record(),
    ]
    result = evaluate_engine(records)
    assert result["n_days"] == 3
    assert result["n_trades"] == 2
    assert result["n_no_trade"] == 1
    assert result["no_trade_reasons"] == {"NO_TRADE_NO_CLEAR_EDGE": 1}
    assert result["pnl"]["n"] == 2
    assert result["win_rate"] == 0.5
    assert result["avg_winner"] == 5.0
    assert result["avg_loser"] == -2.0
    assert result["max_loss"] == -2.0


def test_evaluate_engine_direction_accuracy_traded_vs_all():
    records = [
        _traded_record(direction_state="up", underlying_direction="up"),   # correct
        _traded_record(direction_state="up", underlying_direction="down"),  # wrong
        _no_trade_record(direction_state=None, underlying_direction="up"),  # not scoreable (no direction_state)
    ]
    result = evaluate_engine(records)
    assert result["direction_accuracy_traded_days"] == 0.5
    assert result["direction_accuracy_all_days"] == 0.5  # the no-direction_state row is excluded from both


def test_evaluate_engine_segment_breakdown_flags_insufficient_n():
    records = [_traded_record(opt_type="CE") for _ in range(2)]  # below MIN_N_FOR_SEGMENT
    result = evaluate_engine(records)
    assert result["by_option_type"]["CE"]["n"] == 2
    assert result["by_option_type"]["CE"]["insufficient_n"] is True
    assert MIN_N_FOR_SEGMENT == 3


def test_evaluate_engine_deterministic():
    records = [_traded_record(pnl=1.0), _traded_record(pnl=-1.0), _no_trade_record()]
    r1 = evaluate_engine(records)
    r2 = evaluate_engine(records)
    assert r1 == r2


def test_evaluate_baseline_only_counts_days_with_a_candidate():
    records = [
        {"baseline_atm": {"final_pct_return": 3.0}},
        {"baseline_atm": None},  # no ATM candidate existed that day -- excluded, not zero-filled
        {"baseline_atm": {"final_pct_return": -1.0}},
    ]
    result = evaluate_baseline(records, "baseline_atm")
    assert result["n"] == 2
    assert result["win_rate"] == 0.5
