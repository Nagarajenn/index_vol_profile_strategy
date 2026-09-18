"""12A LIVE SHADOW RECORDER -- observation only.

Evaluates 12A-scalp-v1 in real time on the HR 5-second data as the HR capture
writes it, and records every candidate event, its confirmation, the
hypothetical option, ASK entry, the BID path (MFE/MAE/times), the hypothetical
exit, the NO-TRADE reasons and whether risk rules were satisfied.

NO paper positions. NO Dhan order endpoints. NO interaction with 11d-paper-v1.
Reads hr_* / levels_snapshots / paper_decisions (context) read-only; writes
only scalp12a_* tables. Runs as its own process with its own DB connection.

Schedule: SensexNifty-Scalp12AShadow at 14:53 on weekdays (exits on holidays),
evaluates every 5 s from 14:55 to 15:36, then finalises and refreshes the
research report.

Usage:
  venv\\Scripts\\python.exe scripts\\run_scalp12a_shadow.py            # the live recorder
  venv\\Scripts\\python.exe scripts\\run_scalp12a_shadow.py --dry-run  # one pass on today's HR data, writes nothing
"""

import argparse
import logging
import sys
import time as _time
from datetime import datetime, time, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from config.settings import IST  # noqa: E402
from pipeline.trading_calendar import is_trading_day  # noqa: E402
from scalp_12a import db  # noqa: E402
from scalp_12a.config import DEFAULT_CONFIG, STRATEGY_VERSION  # noqa: E402
from scalp_12a.engine import evaluate_day  # noqa: E402
from scalp_12a.thresholds import build_thresholds  # noqa: E402

log = logging.getLogger("scalp12a.shadow")
START = time(14, 55, 20)
END = time(15, 36, 0)            # 15:30 + 300 s outcome horizon + margin
HARD_STOP = time(15, 40, 0)
HR_WAIT_UNTIL = time(15, 5, 0)
BAR_SAFETY_S = 12                # only bars whose start <= now - 12 s (HR rows land ~8-10 s after bar start)
POLL_S = 5


def now_ist() -> datetime:
    return datetime.now(IST)


def find_hr_session(conn, today, wait: bool):
    while True:
        rows = [r for r in db.hr_session_ids(conn, today) if r[0] == today]
        if rows:
            return rows[-1][1]
        if not wait or now_ist().time() >= HR_WAIT_UNTIL:
            return None
        _time.sleep(10)


def load_prior(conn, today, cfg):
    prior = {}
    for d, sid, status in db.hr_session_ids(conn, today - timedelta(days=1)):
        if status == "RUNNING":
            continue
        for sym in cfg.symbols:
            s = db.load_session(conn, sid, d, sym)
            if s is not None:
                prior.setdefault(sym, []).append(s)
    return prior


def evaluate_pass(conn, today, sid, prior, cfg, final: bool, write: bool = True):
    until = None if final else now_ist() - timedelta(seconds=BAR_SAFETY_S)
    sessions = [s for s in (db.load_session(conn, sid, today, sym, until) for sym in cfg.symbols) if s is not None]
    if not sessions:
        return 0, 0, {}
    thr = {s.symbol: build_thresholds(prior.get(s.symbol, []), cfg) for s in sessions}
    res = evaluate_day(sessions, thr, cfg, db.load_context_fn(conn, today), session_complete=final)
    h = cfg.config_hash()
    wall = now_ist()
    n = trade = 0
    for s in sessions:
        for c in res[s.symbol].candidates:
            if write:
                db.upsert_candidate(conn, db.candidate_row(c, "LIVE_SHADOW", h, db.thresholds_json(thr[s.symbol]),
                                                           s.is_expiry_day, wall))
            n += 1
            trade += int(c.would_trade)
    stats = dict(bars=sum(r.bars_evaluated for r in res.values()), stale=sum(r.stale_bars for r in res.values()),
                 reasons=sorted({x for r in res.values() for x in r.session_reasons}),
                 thresholds={k: db.thresholds_json(v) for k, v in thr.items()})
    return n, trade, stats


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="one pass on today's HR data, write nothing")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    cfg = DEFAULT_CONFIG
    h = cfg.config_hash()
    today = now_ist().date()
    if not is_trading_day(today):
        log.info("%s is not a trading day -- exiting", today)
        return 0
    log.info("%s shadow, config %s -- observation only: no orders, no paper positions", STRATEGY_VERSION, h)

    with db.connect() as conn:
        if args.dry_run:
            sid = find_hr_session(conn, today, wait=False)
            if sid is None:
                log.warning("no HR session today")
                return 1
            n, trade, stats = evaluate_pass(conn, today, sid, load_prior(conn, today, cfg), cfg, final=False, write=False)
            log.info("DRY RUN (nothing written): %d candidates, %d would-trade, bars %s, stale %s, thresholds %s",
                     n, trade, stats.get("bars"), stats.get("stale"), stats.get("thresholds"))
            return 0

        db.apply_schema(conn)
        while now_ist().time() < START:
            _time.sleep(5)
        sid = find_hr_session(conn, today, wait=True)
        if sid is None:
            db.upsert_session(conn, today, "LIVE_SHADOW", h, None, "HR_UNAVAILABLE", {}, 0, 0, 0, 0,
                              ["STALE_DATA"], "no HR session for today")
            log.warning("no HR session today -- nothing to shadow")
            return 1
        prior = load_prior(conn, today, cfg)
        log.info("HR session %s; prior HR days: %s", sid, {k: len(v) for k, v in prior.items()})

        n = trade = 0
        while True:
            t = now_ist().time()
            final = t >= END
            try:
                n, trade, stats = evaluate_pass(conn, today, sid, prior, cfg, final)
                db.upsert_session(conn, today, "LIVE_SHADOW", h, sid, "COMPLETED" if final else "RUNNING",
                                  stats.get("thresholds", {}), stats.get("bars"), stats.get("stale"), n, trade,
                                  stats.get("reasons", []))
            except Exception:  # contained: the shadow must never affect anything else
                log.exception("shadow evaluation pass failed (contained)")
            if final or t >= HARD_STOP:
                break
            _time.sleep(POLL_S)
        log.info("shadow finished: %d candidates, %d would-trade (hypothetical)", n, trade)

    try:
        import run_scalp12a_research
        run_scalp12a_research.main(["--hr-only"])
    except Exception:
        log.exception("post-session research refresh failed (contained)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
