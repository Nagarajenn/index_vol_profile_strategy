"""13-live-trading-v1 -- the live trading process.

    venv/Scripts/python.exe scripts/run_live_trader.py            # DRY RUN (default)
    venv/Scripts/python.exe scripts/run_live_trader.py --live     # places REAL orders

DRY RUN is the default and must be turned off deliberately. In dry run everything happens
exactly as it would live -- 12C is replayed, the guards run, the order is built and journalled
-- except that nothing is sent to the broker.

This process is independent of pipeline/live_loop.py. It reads the minute data that process
has already captured and writes only live_* tables, so a fault here cannot stall data capture.

The session starts DISARMED. Arm it from the /live-trading page (or --arm) for the day; the
process disarms every session on start so a restart can never inherit an armed state.
"""

import argparse
import sys
import time
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from config.settings import IST                                        # noqa: E402
from live_trading import journal, runner, state                        # noqa: E402
from live_trading.config import DEFAULT as CFG                         # noqa: E402
from live_trading.config import (MAX_ENTRIES_PER_DAY, MAX_ENTRY_COST_RS,   # noqa: E402
                                 STARTING_CAPITAL_RS, SYMBOL_BY_WEEKDAY)
from pipeline.trading_calendar import is_trading_day                   # noqa: E402

LOOP_START, LOOP_END = "09:15", "15:12"        # a little past the 15:10 force-flat
POLL_SECONDS = 20


def symbols_for(d: date) -> tuple:
    return SYMBOL_BY_WEEKDAY.get(d.weekday(), ())


def banner(dry_run: bool, d: date, syms) -> None:
    mode = "DRY RUN -- nothing will be sent" if dry_run else "*** LIVE -- REAL ORDERS ***"
    print(f"13-live-trading-v1 | {d} {d.strftime('%A')} | {mode}")
    print(f"  symbols today   : {', '.join(syms) or 'none scheduled'}")
    print(f"  caps            : {MAX_ENTRIES_PER_DAY} entries, 1 lot, halt after first loss, "
          f"max Rs {MAX_ENTRY_COST_RS:,.0f}/entry, capital Rs {STARTING_CAPITAL_RS:,.0f}")
    print(f"  entry window    : {CFG.entry_window_start}-{CFG.entry_window_end} "
          f"({CFG.min_confirmation} only, episode >= {CFG.min_episode_minutes}m, one entry per episode)")
    print(f"  force flat      : {CFG.force_flat_at}")
    print(f"  config hash     : {CFG.config_hash()}")


def main() -> int:
    ap = argparse.ArgumentParser(description="12C-triggered live trader (DRY RUN unless --live)")
    ap.add_argument("--live", action="store_true", help="place REAL orders; without it nothing is sent")
    ap.add_argument("--arm", action="store_true", help="arm today's scheduled symbols at start")
    ap.add_argument("--once", action="store_true", help="evaluate one tick per symbol and exit")
    args = ap.parse_args()
    dry_run = not args.live

    now = datetime.now(IST)
    d = now.date()
    syms = symbols_for(d)
    banner(dry_run, d, syms)

    if not is_trading_day(d):
        print("not a trading day -- nothing to do")
        return 0
    if not syms:
        print("no symbol scheduled for today -- nothing to do")
        return 0

    write = state.connect()
    state.disarm_all(write, d)             # a restart never inherits an armed session
    journal.log(write, d, "PROCESS_START", f"dry_run={dry_run} symbols={','.join(syms)}")
    for s in syms:
        state.session(write, s, d)
        if args.arm:
            state.set_flags(write, s, d, armed=True)
            journal.log(write, d, "ARMED", "armed from the command line", symbol=s)
    if not args.arm:
        print("\nSessions are DISARMED. Arm from the /live-trading page before any order can be placed.\n")

    flattened = set()
    try:
        while True:
            now = datetime.now(IST)
            hhmm = now.strftime("%H:%M")
            if hhmm > LOOP_END or not args.once and hhmm < LOOP_START:
                if hhmm > LOOP_END:
                    break
                time.sleep(POLL_SECONDS)
                continue

            for sym in syms:
                try:
                    if hhmm >= CFG.force_flat_at and sym not in flattened:
                        out = runner.force_flat(sym, now=now, dry_run=dry_run)
                        flattened.add(sym)
                        print(f"[{hhmm}] {sym} FORCE FLAT -> {out}")
                        continue
                    out = runner.tick(sym, now=now, dry_run=dry_run)
                    if out.get("action") not in ("NO_SIGNAL",):
                        print(f"[{hhmm}] {sym} {out}")
                except Exception as exc:                     # a fault on one symbol must not stop the other
                    print(f"[{hhmm}] {sym} ERROR {type(exc).__name__}: {exc}")
                    journal.log(write, d, "ERROR", f"{type(exc).__name__}: {exc}", symbol=sym, minute=hhmm)
            if args.once:
                break
            time.sleep(POLL_SECONDS)
    except KeyboardInterrupt:
        print("\ninterrupted")
    finally:
        journal.log(write, d, "PROCESS_STOP", "")
        for s in syms:                                       # never leave a session armed behind us
            state.set_flags(write, s, d, armed=False)
        write.close()
    print("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
