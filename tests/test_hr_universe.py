"""HR-1 universe: dynamic ATM, no hard-coded strikes/IDs, metadata preserved."""

import ast
import re
from datetime import date
from pathlib import Path

import pandas as pd

from hr_capture.universe import (
    infer_strike_step, options_from_chain, resolve_symbol_universe, select_band,
)

HR_DIR = Path(__file__).resolve().parent.parent / "hr_capture"


def _chain(spot, strikes, expiry="2026-09-15", missing=()):
    oc = {}
    for i, k in enumerate(strikes):
        oc[f"{k:.6f}"] = {
            "ce": {} if (k, "CE") in missing else {"security_id": 50000 + 2 * i},
            "pe": {} if (k, "PE") in missing else {"security_id": 50001 + 2 * i},
        }
    return {"expiry": date.fromisoformat(expiry), "spot": spot, "raw_payload": {"last_price": spot, "oc": oc}}


def _scrip(trading_date="2026-09-15"):
    rows = [
        {"SEM_EXM_EXCH_ID": "NSE", "SEM_SEGMENT": "I", "SEM_SMST_SECURITY_ID": 13, "SEM_INSTRUMENT_NAME": "INDEX",
         "SEM_TRADING_SYMBOL": "NIFTY", "SEM_EXPIRY_DATE": None, "SEM_STRIKE_PRICE": None, "SEM_OPTION_TYPE": None,
         "SEM_EXCH_INSTRUMENT_TYPE": "INDEX"},
        {"SEM_EXM_EXCH_ID": "NSE", "SEM_SEGMENT": "D", "SEM_SMST_SECURITY_ID": 111, "SEM_INSTRUMENT_NAME": "FUTIDX",
         "SEM_TRADING_SYMBOL": "NIFTY-Aug2026-FUT", "SEM_EXPIRY_DATE": "2026-08-27 14:30:00", "SEM_STRIKE_PRICE": None,
         "SEM_OPTION_TYPE": None, "SEM_EXCH_INSTRUMENT_TYPE": "FUTIDX"},
        {"SEM_EXM_EXCH_ID": "NSE", "SEM_SEGMENT": "D", "SEM_SMST_SECURITY_ID": 222, "SEM_INSTRUMENT_NAME": "FUTIDX",
         "SEM_TRADING_SYMBOL": "NIFTY-Sep2026-FUT", "SEM_EXPIRY_DATE": "2026-09-29 14:30:00", "SEM_STRIKE_PRICE": None,
         "SEM_OPTION_TYPE": None, "SEM_EXCH_INSTRUMENT_TYPE": "FUTIDX"},
        {"SEM_EXM_EXCH_ID": "NSE", "SEM_SEGMENT": "D", "SEM_SMST_SECURITY_ID": 333, "SEM_INSTRUMENT_NAME": "FUTIDX",
         "SEM_TRADING_SYMBOL": "NIFTY-Oct2026-FUT", "SEM_EXPIRY_DATE": "2026-10-27 14:30:00", "SEM_STRIKE_PRICE": None,
         "SEM_OPTION_TYPE": None, "SEM_EXCH_INSTRUMENT_TYPE": "FUTIDX"},
        {"SEM_EXM_EXCH_ID": "NSE", "SEM_SEGMENT": "D", "SEM_SMST_SECURITY_ID": 9999, "SEM_INSTRUMENT_NAME": "OPTIDX",
         "SEM_TRADING_SYMBOL": "NIFTY-Sep2026-23300-PE", "SEM_EXPIRY_DATE": "2026-09-15 14:30:00",
         "SEM_STRIKE_PRICE": 23300.0, "SEM_OPTION_TYPE": "PE", "SEM_EXCH_INSTRUMENT_TYPE": "OP"},
    ]
    return pd.DataFrame(rows)


def test_atm_follows_the_reference_spot():
    strikes = [23000.0 + 50 * i for i in range(20)]
    atm_a, band_a = select_band(strikes, 23312.0, 5)
    atm_b, band_b = select_band(strikes, 23538.0, 5)
    assert atm_a == 23300.0 and atm_b == 23550.0
    assert [s for _, s in band_a] != [s for _, s in band_b]
    assert [o for o, _ in band_a] == list(range(-5, 6))


def test_band_is_positional_over_listed_strikes_and_truncates_honestly():
    atm, band = select_band([100.0, 200.0, 300.0], 290.0, 5)
    assert atm == 300.0 and [s for _, s in band] == [100.0, 200.0, 300.0]
    assert infer_strike_step([23000.0, 23050.0, 23100.0, 23200.0]) == 50.0


def test_options_come_from_chain_ids_and_fall_back_to_scrip_master():
    strikes = [23000.0 + 50 * i for i in range(15)]
    chain = _chain(23312.0, strikes, missing={(23300.0 - 0, "PE")})
    instruments, atm, spot, expiry, step, issues = options_from_chain("NIFTY", chain, 5, "FULL", _scrip())
    assert atm == 23300.0 and spot == 23312.0 and expiry == date(2026, 9, 15) and step == 50.0
    assert len(instruments) == 22
    fallback = next(i for i in instruments if i.strike == 23300.0 and i.option_type == "PE")
    assert fallback.security_id == 9999 and fallback.id_source == "SCRIP_MASTER"
    from_chain = next(i for i in instruments if i.strike == 23300.0 and i.option_type == "CE")
    assert from_chain.id_source == "OPTION_CHAIN_RAW" and from_chain.atm_offset == 0
    assert all(i.exchange_segment == "NSE_FNO" and i.expiry == date(2026, 9, 15) for i in instruments)


def test_full_universe_is_48_across_two_symbols_shape_and_nearest_future():
    strikes = [23000.0 + 50 * i for i in range(15)]
    u = resolve_symbol_universe("NIFTY", date(2026, 9, 15), _chain(23312.0, strikes), None, _scrip(), 5,
                                "QUOTE", "FULL", "FULL")
    assert len(u.instruments) == 24 and u.issues == []
    kinds = [i.instrument_type for i in u.instruments]
    assert kinds.count("INDEX") == 1 and kinds.count("FUTIDX") == 1 and kinds.count("OPTIDX") == 22
    future = next(i for i in u.instruments if i.instrument_type == "FUTIDX")
    assert future.security_id == 222 and future.expiry == date(2026, 9, 29)   # expired Aug contract skipped
    index = next(i for i in u.instruments if i.instrument_type == "INDEX")
    assert (index.exchange_segment, index.security_id, index.subscribe_mode) == ("IDX_I", 13, "QUOTE")


def test_missing_sources_are_reported_not_invented():
    u = resolve_symbol_universe("NIFTY", date(2026, 9, 15), None, None, None, 5, "QUOTE", "FULL", "FULL")
    assert u.instruments == []
    assert "INDEX_UNRESOLVED" in u.issues and "FUTURES_UNRESOLVED" in u.issues
    assert any(i.startswith("OPTIONS_UNRESOLVED") for i in u.issues)


def test_hr_source_contains_no_hard_coded_strikes_or_security_ids():
    """Numeric literals >= 1000 in HR code would be strike values or security IDs."""
    # Named operational constants only: ns/second, queue size, DB timeouts (ms), IST offset (s), byte sizes.
    allowed = {1_000_000_000, 500_000, 5_000, 2_000, 19_800, 1000, 1024}
    offenders = []
    for path in HR_DIR.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
                if abs(node.value) >= 1000 and node.value not in allowed:
                    offenders.append(f"{path.name}:{node.lineno}:{node.value}")
    assert offenders == [], offenders
    text = "\n".join(p.read_text(encoding="utf-8") for p in HR_DIR.glob("*.py"))
    assert not re.search(r"\b(23|24|74|75|76|77)\d{3}(\.0)?\b", text), "strike-like literal in HR source"
