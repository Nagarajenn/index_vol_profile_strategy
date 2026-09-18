"""12A research runner: 1-minute chronological research + HR replay vs random,
then regenerate the validation report (milestone12a_research_report.html).

Read-only on every existing table; writes only scalp12a_* (REPLAY rows) and the
report/JSON files. Never trades, never touches 11D.

Usage:
  venv\\Scripts\\python.exe scripts\\run_scalp12a_research.py            # full refresh
  venv\\Scripts\\python.exe scripts\\run_scalp12a_research.py --hr-only  # skip the 1-minute part (reuse JSON)
"""

import argparse
import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scalp_12a import db, report, research_1min, research_hr  # noqa: E402
from scalp_12a.config import DEFAULT_CONFIG  # noqa: E402

OUT_DIR = ROOT / "data" / "cache" / "scalp12a"
REPORT = ROOT / "milestone12a_research_report.html"
log = logging.getLogger("scalp12a.research")


def load_hr_days(conn, symbols):
    out = {}
    for d, sid, status in db.hr_session_ids(conn):
        if status == "RUNNING":
            continue
        day = {}
        for sym in symbols:
            s = db.load_session(conn, sid, d, sym)
            if s is not None:
                day[sym] = s
        if day:
            out[d] = (sid, day)
    return out


def main(argv=None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hr-only", action="store_true")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    cfg = DEFAULT_CONFIG
    with db.connect(300000) as conn:
        db.apply_schema(conn)
        r1_path = OUT_DIR / "research_1min.json"
        if args.hr_only and r1_path.exists():
            r1 = json.loads(r1_path.read_text(encoding="utf-8"))
        else:
            log.info("1-minute research ...")
            r1 = json.loads(json.dumps(research_1min.run(conn), default=str))   # uniform string keys
            r1_path.write_text(json.dumps(r1, default=str, indent=1), encoding="utf-8")

        log.info("HR replay ...")
        hr = load_hr_days(conn, cfg.symbols)
        sessions_by_day = {d: v[1] for d, v in hr.items()}
        result, candidates = research_hr.run(sessions_by_day, cfg)
        summary = json.loads(json.dumps(research_hr.summarize(result, cfg), default=str))
        (OUT_DIR / "research_hr.json").write_text(json.dumps(dict(result=result, summary=summary), default=str,
                                                             indent=1), encoding="utf-8")
        h = cfg.config_hash()
        for d, sym, c, thr in candidates:
            s = sessions_by_day[d][sym]
            db.upsert_candidate(conn, db.candidate_row(c, "REPLAY", h, db.thresholds_json(thr), s.is_expiry_day, None))
        for d, (sid, day) in hr.items():
            meta = next(m for m in result["day_meta"] if m["day"] == str(d))
            db.upsert_session(conn, d, "REPLAY", h, sid, "COMPLETED", meta["sufficient"], None, None,
                              meta["candidates"], meta["would_trade"], [], "HR replay (descriptive)")

        shadow = conn.execute(
            "SELECT trading_date, status, candidates, would_trade FROM scalp12a_shadow_sessions WHERE source='LIVE_SHADOW' "
            "AND config_hash=%s ORDER BY trading_date", (h,)).fetchall()
        latency = conn.execute(
            "SELECT count(*), percentile_cont(0.5) WITHIN GROUP (ORDER BY detection_latency_s), max(detection_latency_s) "
            "FROM scalp12a_candidates WHERE source='LIVE_SHADOW' AND config_hash=%s AND detection_latency_s IS NOT NULL",
            (h,)).fetchone()
    html = report.build(r1, summary, result["day_meta"], cfg, shadow, latency)
    REPORT.write_text(html, encoding="utf-8")
    log.info("report written: %s", REPORT)


if __name__ == "__main__":
    main()
