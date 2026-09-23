"""12C-position-simulation-v1 tests (synthetic only; no DB, no network, no orders).

Covers the 20 required behaviours: BUY CE / BUY PE create long simulations, WAIT creates none,
entry is the ASK (never the LTP), P&L is BID-based, values use the resolved quantity, the stop
is computed and breaches detected, repeated signals do not duplicate a position, a flip records a
transition, MFE/MAE start at entry, historical replay has no look-ahead, missing bid/ask/quantity
and stale data are handled explicitly, the existing 12C signal output is unchanged, and no order
API is reachable from the package.
"""

import ast
import re
from datetime import date, datetime, time, timedelta
from pathlib import Path

import pytest

from config.settings import IST
from option_risk_12b.engine import prepare
from position_sim_12c import VERSION
from position_sim_12c import metrics as M
from position_sim_12c.config import DEFAULT, SimConfig
from position_sim_12c.replay import leakage_audit, replay
from position_sim_12c.simulator import simulate, snapshot

ROOT = Path(__file__).resolve().parent.parent
D = date(2026, 9, 22)
ATM = 23400.0
STEP = 50.0


# ---------------------------------------------------------------- synthetic chain
def chain(minutes, ce_path, pe_path, spread=0.5, drop=(), one_sided=(), ltp_only=()):
    """One snapshot per minute; ce_path/pe_path give the ATM mid at each minute."""
    snaps = []
    for i, m in enumerate(minutes):
        if m in drop:
            continue
        oc = {}
        for off in range(-3, 4):
            k = ATM + off * STEP
            for typ, path in (("ce", ce_path), ("pe", pe_path)):
                mid = path[i] + abs(off) * 2
                half = spread / 2
                leg = dict(last_price=round(mid, 2), top_bid_price=round(mid - half, 2),
                           top_ask_price=round(mid + half, 2), top_bid_quantity=100, top_ask_quantity=100,
                           volume=1000 + i * 10, oi=5000, implied_volatility=12.0,
                           greeks=dict(delta=0.5, gamma=0.001, theta=-2.0, vega=1.0))
                if m in one_sided:
                    leg["top_ask_price"] = 0          # no usable ask
                if m in ltp_only:
                    leg["top_bid_price"] = 0
                    leg["top_ask_price"] = 0
                oc.setdefault(f"{k:.6f}", {})[typ] = leg
        h, mm = map(int, m.split(":"))
        ts = datetime.combine(D, time(h, mm), tzinfo=IST)
        snaps.append(dict(fetched_at=ts, spot=ATM, expiry=D, payload={"oc": oc, "last_price": ATM}))
    candles = [dict(timestamp=datetime.combine(D, time(*map(int, m.split(":"))), tzinfo=IST) - timedelta(minutes=1),
                    open=ATM, high=ATM + 2, low=ATM - 2, close=ATM, volume=1000.0) for m in minutes]
    return prepare(snaps, candles)


def mins(a, b):
    out, (h, m) = [], map(int, a.split(":"))
    eh, em = map(int, b.split(":"))
    while (h, m) <= (eh, em):
        out.append(f"{h:02d}:{m:02d}")
        m += 1
        if m == 60:
            h, m = h + 1, 0
    return out


def rows_for(minutes, decisions):
    return [dict(minute=m, decision=d, confirmation="MODERATE", atm=ATM, evidence=None)
            for m, d in zip(minutes, decisions)]


MINUTES = mins("09:20", "09:29")
FLAT = [100.0] * 10


def sim(decisions, ce=None, pe=None, cfg=DEFAULT, **kw):
    series, _ = chain(MINUTES, ce or FLAT, pe or FLAT, **kw)
    return simulate("NIFTY", series, rows_for(MINUTES, decisions), cfg), series


# ---------------------------------------------------------------- 1 / 2 / 3
def test_buy_ce_creates_a_long_ce_simulation():
    s, _ = sim(["WAIT", "BUY_CE"] + ["BUY_CE"] * 8)
    p = s["open_position"]
    assert p["side"] == "CE" and p["status"] == "OPEN" and p["signal_minute"] == "09:21"
    assert p["contract"].endswith("CE") and p["advisory_only"] is True and p["version"] == VERSION


def test_buy_pe_creates_a_long_pe_simulation():
    s, _ = sim(["BUY_PE"] * 10)
    assert s["open_position"]["side"] == "PE" and s["open_position"]["signal_minute"] == "09:20"


def test_wait_creates_no_position():
    s, _ = sim(["WAIT"] * 10)
    assert s["open_position"] is None and s["closed_positions"] == [] and s["counts"]["opened"] == 0


# ---------------------------------------------------------------- 4 / 5 / 6 / 7 / 8
def test_entry_uses_ask_not_ltp():
    s, _ = sim(["BUY_CE"] * 10)                       # mid 100, spread 0.5 -> bid 99.75 ask 100.25
    p = s["open_position"]
    assert p["entry_price"] == 100.25 and p["entry_price_type"] == "ASK"
    assert p["entry_ltp_at_signal"] == 100.0 and p["entry_price"] != p["entry_ltp_at_signal"]


def test_missing_ask_never_falls_back_to_ltp():
    s, _ = sim(["BUY_CE"] * 10, one_sided=("09:20",))
    rec = s["closed_positions"][0]
    assert rec["entry_price"] is None and rec["entry_price_status"] == "UNAVAILABLE"
    assert rec["status"] == "UNAVAILABLE" and rec["pnl"] is None and rec["entry_ltp_at_signal"] is not None
    # the signal continues, so the next minute with a real two-sided quote opens the position
    assert s["open_position"]["entry_minute"] == "09:21" and s["open_position"]["entry_price"] == 100.25


def test_pnl_uses_bid_and_percentage_is_correct():
    ce = [100.0] * 5 + [110.0] * 5                     # bid becomes 109.75 from 09:25
    s, _ = sim(["BUY_CE"] * 10, ce=ce)
    p = s["open_position"]
    assert p["entry_price"] == 100.25 and p["current"]["bid"] == 109.75 and p["current"]["ltp"] == 110.0
    assert p["pnl_per_unit"] == pytest.approx(9.5)                      # bid - ask, never ltp - ltp
    assert p["pnl_pct"] == pytest.approx(9.5 / 100.25 * 100, rel=1e-3)
    assert p["since_signal"]["entry_ask"] == 100.25 and p["since_signal"]["current_bid"] == 109.75


def test_position_value_uses_quantity():
    s, _ = sim(["BUY_CE"] * 10)
    p = s["open_position"]
    if p["quantity"]:
        assert p["entry_value"] == pytest.approx(p["entry_price"] * p["quantity"])
        assert p["current_value"] == pytest.approx(p["current"]["bid"] * p["quantity"])
        assert p["pnl"] == pytest.approx(p["pnl_per_unit"] * p["quantity"])
    else:
        assert p["quantity_status"] == "UNKNOWN" and p["pnl"] is None


# ---------------------------------------------------------------- 9 / 10
def test_stop_loss_price_and_acceptance_example():
    assert M.stop_loss(82.40, SimConfig(stop_loss_pct=10.0)) == 74.16      # the worked example
    s, _ = sim(["BUY_CE"] * 10)
    p = s["open_position"]
    assert p["stop_loss_price"] == pytest.approx(round(p["entry_price"] * 0.9, 2))
    assert p["distance_to_stop"] == pytest.approx(round(p["current"]["bid"] - p["stop_loss_price"], 2))
    assert SimConfig(stop_loss_pct=25.0).config_hash() != DEFAULT.config_hash()   # configurable, not hard-coded


def test_stop_breach_is_detected_and_flagged():
    ce = [100.0] * 4 + [80.0] * 6                      # bid 79.75 vs stop 90.22
    s, _ = sim(["BUY_CE"] * 10, ce=ce)
    p = s["open_position"]
    assert p["stop_breached"] is True and p["risk"]["risk_state"] == "STOP_BREACH"
    assert p["stop_breach_minute"] == "09:24" and p["status"] == "OPEN"   # flagged, not auto-closed
    s2, _ = sim(["BUY_CE"] * 10, ce=ce, cfg=SimConfig(close_on_stop_breach=True))
    assert s2["open_position"] is None and s2["closed_positions"][0]["exit_reason"] == "STOP_BREACH"


# ---------------------------------------------------------------- 11 / 12
def test_repeated_signal_does_not_duplicate_the_position():
    s, _ = sim(["BUY_PE"] * 10)
    assert s["counts"]["opened"] == 1 and s["counts"]["closed"] == 0
    assert s["open_position"]["entry_minute"] == "09:20" and s["open_position"]["hold_minutes"] == 9


def test_flip_closes_the_first_and_records_the_transition():
    s, _ = sim(["BUY_PE"] * 5 + ["BUY_CE"] * 5)
    assert len(s["closed_positions"]) == 1
    first = s["closed_positions"][0]
    assert first["side"] == "PE" and first["exit_reason"] == "SIGNAL_FLIP" and first["exit_minute"] == "09:25"
    assert first["exit_bid"] is not None and first["realised_pnl_per_unit"] is not None
    assert s["open_position"]["side"] == "CE" and s["open_position"]["entry_minute"] == "09:25"


def test_wait_closes_the_position():
    s, _ = sim(["BUY_CE"] * 4 + ["WAIT"] * 6)
    assert s["open_position"] is None and s["closed_positions"][0]["exit_reason"] == "WAIT"


def test_history_records_which_decision_closed_the_position():
    s, _ = sim(["BUY_PE"] * 5 + ["BUY_CE"] * 5)
    closed = s["closed_positions"][0]
    assert closed["exit_reason"] == "SIGNAL_FLIP" and closed["closing_decision"] == "BUY_CE"
    assert closed["closing_confirmation"] == "MODERATE"
    from position_sim_12c.history import COLUMNS, to_row
    row = to_row(closed, D, "decision-hash")
    assert set(row) == set(COLUMNS)
    assert row["closing_decision"] == "BUY_CE" and row["exit_reason"] == "SIGNAL_FLIP"
    assert row["entry_price_type"] == "ASK" and row["sim_version"] == VERSION
    assert row["decision_config_hash"] == "decision-hash" and row["risk_state_at_exit"] is not None


# ---------------------------------------------------------------- 13 / 14
def test_mfe_and_mae_only_use_observations_from_entry_onward():
    ce = [200.0, 200.0, 100.0, 100.0, 130.0, 90.0, 100.0, 100.0, 100.0, 100.0]
    s, _ = sim(["WAIT", "WAIT", "BUY_CE"] + ["BUY_CE"] * 7, ce=ce)
    p = s["open_position"]
    assert p["entry_price"] == 100.25                                  # entered at 09:22, not at 200
    ex = p["excursions"]
    assert ex["mfe_per_unit"] == pytest.approx(129.75 - 100.25)        # best bid after entry
    assert ex["mae_per_unit"] == pytest.approx(89.75 - 100.25)         # worst bid after entry
    assert ex["mfe_per_unit"] < 200                                     # the pre-signal 200 never enters


# ---------------------------------------------------------------- 15 (no look-ahead)
def test_historical_replay_has_no_lookahead():
    ce = [100.0] * 5 + [150.0] * 5
    series, _ = chain(MINUTES, ce, FLAT)
    rows = rows_for(MINUTES, ["WAIT"] + ["BUY_CE"] * 7 + ["WAIT"] * 2)
    audit = leakage_audit("NIFTY", series, rows, ("09:20", "09:29"))
    assert audit["result"] == "PASS" and not audit["entry_mismatches"]
    r = replay("NIFTY", series, rows, ("09:20", "09:29"))
    p = r["positions"][0]
    assert p["entry_price"] == 100.25          # the later 150 never moved the entry
    assert p["excursions"]["mfe_per_unit"] > 0  # later prices are outcome only


# ---------------------------------------------------------------- 16 / 17 / 18
def test_missing_bid_ask_is_explicit():
    s, series = sim(["BUY_CE"] * 5 + ["BUY_CE"] * 5, ltp_only=("09:25",))
    q = M.quote(series, "09:25", "CE", ATM)
    assert q["status"] == "UNAVAILABLE" and q["ltp"] is not None
    card = snapshot({**s["open_position"], "entry_price": 100.25}, series, None, "09:25")
    assert card["pnl_status"] == "UNAVAILABLE" and card["pnl"] is None
    assert card["risk"]["risk_state"] == "UNKNOWN"


def test_missing_quantity_is_explicit():
    series, _ = chain(MINUTES, FLAT, FLAT)
    s = simulate("UNKNOWNSYM", series, rows_for(MINUTES, ["BUY_CE"] * 10), DEFAULT)
    p = s["open_position"]
    assert p["quantity"] is None and p["quantity_status"] == "UNKNOWN"
    assert p["pnl"] is None and p["entry_value"] is None          # monetary values withheld
    assert p["pnl_per_unit"] is not None                          # price movement still shown


def test_stale_option_data_is_detected():
    s, series = sim(["BUY_CE"] * 10, drop=("09:27", "09:28", "09:29"))
    card = snapshot(dict(side="CE", strike=ATM, entry_price=100.25, entry_minute="09:20", quantity=65,
                         signal_minute="09:20", exit_minute=None, symbol="NIFTY", expiry=str(D), contract="x",
                         confirmation="MODERATE", entry_price_type="ASK", entry_price_status="OK",
                         quantity_status="OK", quantity_source="test", status="OPEN", stop_loss_pct=10.0,
                         exit_bid=None, exit_reason=None, realised_pnl=None, realised_pnl_per_unit=None,
                         realised_pnl_pct=None, stop_breach_minute=None, version=VERSION,
                         entry_bid_at_signal=99.75, entry_ltp_at_signal=100.0, closing_decision=None,
                         closing_confirmation=None, closing_reason=None),
                    series, None, "09:29")
    assert card["current"]["data_status"] == "STALE"
    assert any("stale" in r.lower() for r in card["risk"]["reasons"])


# ---------------------------------------------------------------- 19 / 20 (isolation)
def test_existing_12c_signal_output_is_unchanged():
    """The simulator consumes decisions; it must not import or re-run the decision engine."""
    src = "".join((ROOT / "position_sim_12c" / f).read_text(encoding="utf-8")
                  for f in ("simulator.py", "metrics.py", "replay.py", "config.py", "lots.py"))
    assert "decide_at" not in src and "decide_prepared" not in src and "ENTRY.decide" not in src
    from scalp_decision_12c.config import DEFAULT as C12C
    from option_risk_12b.config import DEFAULT as C12B
    from paper_trading.config import DEFAULT_CONFIG as C11D
    from scalp_12a.config import DEFAULT_CONFIG as C12A
    assert C12C.config_hash() == "d0b1847f5180d11b" and C12B.config_hash() == "1eadd228220900aa"
    assert C11D.config_hash() == "9c7c362d7e0c6a14" and C12A.config_hash() == "994667c6d552111e"


def test_no_order_api_is_reachable_from_the_package():
    forbidden = ("dhan_client", "dhanhq", "paper_trading", "db.writer", "backend")
    terms = ["place" + "_order", "modify" + "_order", "cancel" + "_order", "/" + "orders", "super_order"]
    for p in (ROOT / "position_sim_12c").glob("*.py"):
        text = p.read_text(encoding="utf-8")
        assert not re.search("|".join(terms), text), p.name
        for node in ast.walk(ast.parse(text)):
            names = ([a.name for a in node.names] if isinstance(node, ast.Import)
                     else [node.module] if isinstance(node, ast.ImportFrom) and node.module and node.level == 0 else [])
            for n in names:
                assert not any(n == f or n.startswith(f + ".") for f in forbidden), (p.name, n)
