"""Store the day's closed SIMULATED 12C positions in sim12c_positions.

    venv/Scripts/python.exe scripts/run_12c_position_history.py [YYYY-MM-DD]

Replays the EXISTING 12C decisions for the session, hands them to the position simulator, and
upserts every closed hypothetical position -- including which decision closed it. Idempotent:
re-running a session updates its rows instead of duplicating them.

SIMULATION ONLY. It places no order, touches no paper account, changes no decision, and writes
to sim12c_* tables and nothing else.
"""

import sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from option_risk_12b.engine import prepare                        # noqa: E402
from position_sim_12c import history as H                         # noqa: E402
from position_sim_12c.config import DEFAULT as SIM_CFG            # noqa: E402
from position_sim_12c.simulator import close_out, simulate        # noqa: E402
from scalp_decision_12c import loader                             # noqa: E402
from scalp_decision_12c.config import DEFAULT as DEC_CFG          # noqa: E402
from scalp_decision_12c.engine import decide_prepared             # noqa: E402

SESSION_END = "15:30"


def decisions_for(conn, symbol, d):
    snaps = loader.load_snapshots(conn, symbol, d, start="09:00")
    if not snaps:
        return None, []
    candles = loader.load_candles(conn, symbol, d, start="09:00")
    series, cmap = prepare(snaps, candles)
    cols = ("as_of", "close", "vwap_now", "today_poc", "today_vah", "today_val", "support_low", "support_high",
            "resistance_low", "resistance_high", "trend_label")
    lv = conn.execute(
        f"""select to_char(as_of at time zone 'Asia/Kolkata','HH24:MI'), {', '.join(cols[1:])}
            from levels_snapshots where symbol=%s and (as_of at time zone 'Asia/Kolkata')::date=%s order by as_of""",
        (symbol, d)).fetchall()
    by_minute = {r[0]: dict(zip(cols, r)) for r in lv}
    rows, cur = [], None
    for m in sorted(x for x in series if "09:15" <= x <= SESSION_END):
        cur = by_minute.get(m, cur)
        out = decide_prepared(symbol, d, series, cmap, cur, minute=m)
        if out["status"] == "OK":
            rows.append(dict(minute=m, decision=out["entry"]["decision"], confirmation=out["entry"]["confirmation"],
                             reason=out["entry"]["reason"], atm=out["option_state"]["atm_strike"],
                             evidence=out["evidence"]))
    return series, rows


def main(d: date):
    read = loader.connect()                      # read-only connection for the market data
    write = H.connect()                          # sim12c_* only
    H.apply_schema(write)
    total = 0
    for symbol in ("NIFTY", "SENSEX"):
        series, rows = decisions_for(read, symbol, d)
        if not rows:
            print(f"{symbol}: no decisions for {d}")
            continue
        finished = d < date.today()
        as_of = SESSION_END if finished else datetime.now().strftime("%H:%M")
        sim = simulate(symbol, series, rows, SIM_CFG, as_of=as_of)
        if finished:
            sim = close_out(sim, series, SESSION_END, SIM_CFG)   # nothing is carried overnight
        # mid-session the still-open position is simply not stored yet: it has no exit to record
        stored = [H.to_row(p, d, DEC_CFG.config_hash(), SIM_CFG) for p in sim["closed_positions"]
                  if p.get("exit_minute")]
        n = H.store(write, stored)
        total += n
        pnl = [p["realised_pnl"] for p in sim["closed_positions"] if p.get("realised_pnl") is not None]
        print(f"{symbol}: {n} simulated positions stored | gross Rs {sum(pnl):,.2f} | "
              f"wins {sum(1 for x in pnl if x > 0)} losses {sum(1 for x in pnl if x <= 0)}")
    print(f"total rows written: {total} (sim12c_positions, session {d}, "
          f"sim {SIM_CFG.config_hash()}, decisions {DEC_CFG.config_hash()})")


if __name__ == "__main__":
    main(date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else date.today())
