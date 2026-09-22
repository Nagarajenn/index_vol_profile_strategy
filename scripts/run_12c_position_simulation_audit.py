"""Historical replay of the 12C position simulation + its leakage audit (READ-ONLY).

    venv/Scripts/python.exe scripts/run_12c_position_simulation_audit.py [YYYY-MM-DD]

Replays the EXISTING 12C decisions for a session, hands them to the position simulator, and writes
12C_POSITION_SIMULATION_LEAKAGE_AUDIT.json plus a sample BUY CE and BUY PE position card.
Places no order, writes nothing to the database, changes no decision.
"""

import json
import sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from option_risk_12b.engine import prepare                       # noqa: E402
from position_sim_12c.config import DEFAULT as SIM_CFG           # noqa: E402
from position_sim_12c.replay import leakage_audit, replay        # noqa: E402
from scalp_decision_12c import loader                            # noqa: E402
from scalp_decision_12c.config import DEFAULT as DEC_CFG         # noqa: E402
from scalp_decision_12c.engine import decide_prepared            # noqa: E402

WINDOWS = (("09:17", "10:00"), ("09:17", "15:30"))
OUT = ROOT / "12C_POSITION_SIMULATION_LEAKAGE_AUDIT.json"


def decision_rows(conn, symbol, d):
    """The existing 12C decisions, minute by minute, each with the levels row published by then."""
    snaps = loader.load_snapshots(conn, symbol, d, start="09:00")
    if not snaps:
        return None, []
    candles = loader.load_candles(conn, symbol, d, start="09:00")
    series, cmap = prepare(snaps, candles)
    lv = conn.execute(
        """select to_char(as_of at time zone 'Asia/Kolkata','HH24:MI') m, close, vwap_now, today_poc, today_vah,
                  today_val, support_low, support_high, resistance_low, resistance_high, trend_label
           from levels_snapshots where symbol=%s and (as_of at time zone 'Asia/Kolkata')::date=%s order by as_of""",
        (symbol, d)).fetchall()
    cols = ("as_of", "close", "vwap_now", "today_poc", "today_vah", "today_val", "support_low", "support_high",
            "resistance_low", "resistance_high", "trend_label")
    by_minute = {r[0]: dict(zip(cols, r)) for r in lv}
    rows, cur = [], None
    for m in sorted(x for x in series if "09:15" <= x <= "15:39"):
        cur = by_minute.get(m, cur)
        out = decide_prepared(symbol, d, series, cmap, cur, minute=m)
        if out["status"] == "OK":
            rows.append(dict(minute=m, decision=out["entry"]["decision"], confirmation=out["entry"]["confirmation"],
                             atm=out["option_state"]["atm_strike"], evidence=out["evidence"]))
    return series, rows


def card(p):
    """The fields the panel shows, for the sample outputs."""
    keys = ("contract", "side", "strike", "expiry", "signal_minute", "entry_minute", "entry_price", "entry_price_type",
            "entry_ltp_at_signal", "quantity", "quantity_source", "entry_value", "current_value", "pnl",
            "pnl_per_unit", "pnl_pct", "pnl_status", "stop_loss_price", "stop_loss_pct", "distance_to_stop",
            "stop_breached", "stop_breach_minute", "hold_text", "exit_minute", "exit_bid", "exit_reason",
            "realised_pnl", "realised_pnl_pct", "status")
    return dict({k: p.get(k) for k in keys}, current=p["current"], since_signal=p["since_signal"],
                excursions=p["excursions"], risk=dict(state=p["risk"]["risk_state"], reasons=p["risk"]["reasons"][:3]))


def main(d: date):
    conn = loader.connect()
    report = dict(report="12C_POSITION_SIMULATION_LEAKAGE_AUDIT", session=str(d),
                  simulation_version=SIM_CFG.to_json()["version"], simulation_config=SIM_CFG.config_hash(),
                  decision_config=DEC_CFG.config_hash(), generated_at=datetime.now().isoformat(), symbols={})
    samples = {}
    for symbol in ("NIFTY", "SENSEX"):
        series, rows = decision_rows(conn, symbol, d)
        if not rows:
            report["symbols"][symbol] = dict(status="NO_DATA")
            continue
        sym = dict(status="OK", decisions=len(rows), windows={})
        for lo, hi in WINDOWS:
            r = replay(symbol, series, rows, (lo, hi), SIM_CFG)
            a = leakage_audit(symbol, series, rows, (lo, hi), SIM_CFG)
            sym["windows"][f"{lo}-{hi}"] = dict(summary=r["summary"], leakage=a)
            for p in r["positions"]:
                if p["entry_price_status"] == "OK" and p["side"] not in samples:
                    samples[p["side"]] = card(p)
        report["symbols"][symbol] = sym
    report["samples"] = samples
    report["result"] = "PASS" if all(
        w["leakage"]["result"] == "PASS" for s in report["symbols"].values() if s.get("status") == "OK"
        for w in s["windows"].values()) else "FAIL"
    OUT.write_text(json.dumps(report, indent=1, default=str))
    print("written:", OUT)
    print(json.dumps({k: report[k] for k in ("session", "simulation_version", "result")}, indent=1))
    for symbol, s in report["symbols"].items():
        if s.get("status") != "OK":
            print(f"  {symbol}: {s['status']}")
            continue
        for w, d2 in s["windows"].items():
            print(f"  {symbol} [{w}] {d2['summary']} leakage={d2['leakage']['result']}")


if __name__ == "__main__":
    main(date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else date.today())
