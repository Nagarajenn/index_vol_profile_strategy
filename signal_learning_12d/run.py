"""Replay 12C signals across sessions, store the learning dataset, print the report.

    venv/Scripts/python.exe -m signal_learning_12d.run [--sessions N] [--symbol SYM] [--no-store]

Observation only. Reads market data the pipeline already captured, writes sl12d_* and nothing
else, places no order and changes no 12C rule.
"""

import argparse
import json
from datetime import date
from pathlib import Path

from option_risk_12b.engine import prepare
from scalp_decision_12c import loader
from signal_learning_12d import learning_dataset as DS
from signal_learning_12d import lifecycle_report as LR
from signal_learning_12d.config import DEFAULT
from signal_learning_12d.historical_replay import leakage_audit, replay_session

LEVELS_COLS = ("as_of", "close", "vwap_now", "today_poc", "today_vah", "today_val", "support_low",
               "support_high", "resistance_low", "resistance_high", "trend_label")
ROOT = Path(__file__).resolve().parent.parent


def levels_for(conn, symbol: str, d: date) -> dict:
    rows = conn.execute(
        f"""select to_char(as_of at time zone 'Asia/Kolkata','HH24:MI'), {', '.join(LEVELS_COLS[1:])}
            from levels_snapshots where symbol=%s and (as_of at time zone 'Asia/Kolkata')::date=%s
            order by as_of""", (symbol, d)).fetchall()
    return {r[0]: dict(zip(LEVELS_COLS, r)) for r in rows}


def usable_sessions(conn, min_minutes: int = 200) -> list[date]:
    rows = conn.execute("""select (fetched_at at time zone 'Asia/Kolkata')::date d, symbol, count(*)
                           from option_chain_raw group by 1,2""").fetchall()
    by_d: dict = {}
    for d, s, n in rows:
        by_d.setdefault(d, {})[s] = n
    return sorted(d for d, v in by_d.items() if min(v.values(), default=0) >= min_minutes)


def run(sessions: int | None = None, symbols=("NIFTY", "SENSEX"), store: bool = True, cfg=DEFAULT) -> dict:
    read = loader.connect()
    days = usable_sessions(read)
    if sessions:
        days = days[-sessions:]
    all_rows, audits = [], []
    write = DS.connect() if store else None
    if write:
        DS.apply_schema(write)
    for d in days:
        for sym in symbols:
            snaps = loader.load_snapshots(read, sym, d, start="09:00")
            if not snaps:
                continue
            series, cmap = prepare(snaps, loader.load_candles(read, sym, d, start="09:00"))
            levels = levels_for(read, sym, d)
            rows = replay_session(sym, d, series, cmap, levels, cfg)
            all_rows.extend(rows)
            if write and rows:
                DS.store(write, rows)
            if d == days[-1]:                       # audit the most recent session of each symbol
                audits.append(leakage_audit(sym, d, series, cmap, levels, cfg))
            print(f"  {d} {sym}: {len(rows)} signal episodes")
    return dict(rows=all_rows, sessions=len(days), audits=audits)


def main() -> int:
    ap = argparse.ArgumentParser(description="12D signal learning replay")
    ap.add_argument("--sessions", type=int, default=None, help="most recent N sessions (default: all)")
    ap.add_argument("--symbol", default=None)
    ap.add_argument("--no-store", action="store_true")
    args = ap.parse_args()
    syms = (args.symbol.upper(),) if args.symbol else ("NIFTY", "SENSEX")
    print(f"12D replay | config {DEFAULT.config_hash()} | symbols {', '.join(syms)}")
    out = run(args.sessions, syms, store=not args.no_store)
    rows = out["rows"]
    if not rows:
        print("no signals found")
        return 1
    rep = LR.report(rows, DEFAULT)
    text = LR.format_text(rep, DEFAULT)
    print("\n" + text)
    (ROOT / "12D_SIGNAL_LEARNING_REPORT.txt").write_text(text, encoding="utf-8")
    (ROOT / "12D_SIGNAL_LEARNING_REPORT.json").write_text(
        json.dumps(dict(report=rep, leakage_audits=out["audits"], config=DEFAULT.to_json()),
                   indent=2, default=str), encoding="utf-8")
    print("\nleakage audits:", [(a["symbol"], "PASS" if a["passed"] else f"FAIL {a['mismatches'][:2]}")
                                for a in out["audits"]])
    print("written: 12D_SIGNAL_LEARNING_REPORT.txt / .json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
