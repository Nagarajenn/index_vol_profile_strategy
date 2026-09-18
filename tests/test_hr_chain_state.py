"""HR-1 option-chain transition state: observations only."""

import re

from hr_capture import db as hr_db
from hr_capture.chain_state import build_chain_row, implied_spot, parity_atm_strike
from hr_capture.config import IMPLIED_SPOT_METHOD
from hr_capture.schema_guard import load_schema_sql


def _opt(strike, option_type, bid, ask, offset=0, oi=100, vol=10, age=1.0, updated=True):
    mid = (bid + ask) / 2 if bid is not None and ask is not None else None
    return {"strike": strike, "option_type": option_type, "bid": bid, "ask": ask, "mid": mid, "quote_age_s": age,
            "atm_offset": offset, "oi": oi, "oi_delta": None, "volume_delta": vol, "updated_in_bucket": updated,
            "bid_qty_l1": 10, "ask_qty_l1": 5, "bid_qty_total5": 50, "ask_qty_total5": 25}


def _parity_chain(spot, strikes, noise=None):
    rows = []
    for i, k in enumerate(strikes):
        intrinsic_gap = spot - k + (noise[i] if noise else 0.0)
        ce_mid, pe_mid = 100.0 + max(intrinsic_gap, 0), 100.0 + max(-intrinsic_gap, 0)
        rows.append(_opt(k, "CE", ce_mid - 0.5, ce_mid + 0.5, offset=i - len(strikes) // 2))
        rows.append(_opt(k, "PE", pe_mid - 0.5, pe_mid + 0.5, offset=i - len(strikes) // 2))
    return rows


def test_implied_spot_is_parity_median_with_iqr_and_quality():
    strikes = [74600.0, 74700.0, 74800.0, 74900.0, 75000.0]
    result = implied_spot(_parity_chain(74812.0, strikes), stale_after_s=30.0, min_strikes=5)
    assert result["value"] == 74812.0 and result["n"] == 5 and result["iqr"] == 0.0
    assert result["quality"] == "OK" and result["strikes"] == strikes
    low = implied_spot(_parity_chain(74812.0, strikes[:2]), 30.0, 5)
    assert low["quality"] == "LOW_COVERAGE" and low["n"] == 2
    assert implied_spot([], 30.0, 5)["quality"] == "UNAVAILABLE"


def test_implied_spot_ignores_stale_or_one_sided_quotes():
    rows = _parity_chain(23410.0, [23350.0, 23400.0, 23450.0])
    rows[0]["quote_age_s"] = 120.0
    rows[3]["bid"] = None
    result = implied_spot(rows, 30.0, 1)
    assert result["n"] == 1 and result["strikes"] == [23450.0]


def test_parity_atm_is_where_ce_and_pe_mids_meet():
    rows = _parity_chain(74812.0, [74600.0, 74700.0, 74800.0, 74900.0, 75000.0])
    assert parity_atm_strike(rows, 30.0) == 74800.0


def _chain(**overrides):
    rows = _parity_chain(23410.0, [23350.0, 23400.0, 23450.0])
    args = dict(option_rows=rows, band_atm_strike=23400.0,
                underlying={"last_price": 23410.0, "status": "VALID", "seconds_since_packet": 1.0,
                            "seconds_since_change": 1.0, "last_reliable_price": 23410.0, "last_reliable_ts": None},
                futures={"last_price": 23450.0, "status": "VALID", "bid": 23449.0, "ask": 23451.0, "volume_delta": 75},
                prev=None, symbol_packets=12, is_gap=False, closing_phase_reached=False, after_window_end=False,
                bucket_end_ts=None, stale_after_s=30.0, min_strikes=3)
    args.update(overrides)
    return build_chain_row(**args)


def test_chain_aggregates_straddle_pcr_and_labels_research_only():
    row = _chain()
    assert row["straddle_mid"] == 200.0 + (23410.0 - 23400.0)
    assert row["pcr_oi"] == 1.0 and row["pcr_volume"] == 1.0
    assert row["ce_volume_delta_sum"] == 30 and row["pe_volume_delta_sum"] == 30
    assert row["ce_l1_imbalance"] == round(15 / 45, 6)
    assert row["option_implied_spot_research_only"] == 23410.0
    assert row["implied_spot_method"] == IMPLIED_SPOT_METHOD
    assert row["market_state"] == "CONTINUOUS" and row["data_quality"] == "OK"
    follow = _chain(prev=row, option_rows=_parity_chain(23420.0, [23350.0, 23400.0, 23450.0]))
    assert follow["straddle_change"] == 10.0


FORBIDDEN_DECISION_WORDS = ("buy", "sell", "enter", "entry", "exit", "signal", "score", "order", "trade_decision",
                            "recommend", "action")


def test_transition_state_has_no_trading_decision_fields():
    row_keys = set(_chain())
    table_cols = set(hr_db.TABLE_COLUMNS["hr_option_transition_state"])
    ddl = re.search(r"CREATE TABLE IF NOT EXISTS hr_option_transition_state \((.*?)\n\);", load_schema_sql(), re.S).group(1)
    ddl_cols = {line.split()[0] for line in ddl.splitlines() if line.strip() and not line.strip().startswith(("--", "UNIQUE"))}
    for name in row_keys | table_cols | ddl_cols:
        parts = name.lower().split("_")
        assert not any(word in parts for word in FORBIDDEN_DECISION_WORDS), f"decision-like field: {name}"
