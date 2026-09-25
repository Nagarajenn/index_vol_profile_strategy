"""Run the 13A vs 13B comparison and write the report.

    venv/Scripts/python.exe -m price_action_13b.run [--sessions N]

Paper / advisory only. No broker API is touched and 13A is used unmodified.
"""

import argparse
import csv
import json
from pathlib import Path

from scalp_decision_12c import loader
from price_action_13b import analysis, replay, report
from price_action_13b.config import DEFAULT
from signal_learning_12d.run import usable_sessions

ROOT = Path(__file__).resolve().parent.parent


def write_csv(rows, path):
    if not rows:
        return
    cols = sorted({k for r in rows for k in r})
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def main() -> int:
    ap = argparse.ArgumentParser(description="13B price-action confirmation layer")
    ap.add_argument("--sessions", type=int, default=None)
    ap.add_argument("--case-study", default="2026-09-24")
    args = ap.parse_args()
    conn = loader.connect()
    days = usable_sessions(conn, min_minutes=60)
    if args.sessions:
        days = days[-args.sessions:]
    print(f"13B | config {DEFAULT.config_hash()} | {len(days)} sessions")

    a_pos, b_pos, blocked, a_dec, b_dec = [], [], [], [], []
    for d in days:
        for sym in ("NIFTY", "SENSEX"):
            r = replay.replay_session(conn, sym, d, DEFAULT)
            if not r:
                continue
            a_pos.extend(r["a"]["positions"])
            b_pos.extend(r["b"]["positions"])
            blocked.extend(r["b"]["blocked"])
            a_dec.extend(r["a"]["decisions"])
            b_dec.extend(r["b"]["decisions"])
    print(f"  13A {len(a_pos)} trades | 13B {len(b_pos)} trades | {len(blocked)} blocked")

    cmp = analysis.compare(a_pos, b_pos, blocked, a_dec, b_dec)
    verdict = analysis.verdict(cmp)

    audits = [replay.leakage_audit(conn, s, days[-1], DEFAULT) for s in ("NIFTY", "SENSEX")]
    for a in audits:
        print(f"  leakage {a['symbol']}: {'PASS' if a['passed'] else 'FAIL'} "
              f"({a['checked']} candidates, {len(a['mismatches'])} mismatches, "
              f"future-bar uses {a['future_bar_used']})")

    rejected = sorted(blocked, key=lambda x: -(x.get("mae") or 0))[:12]
    accepted = [p for p in b_pos][:12]
    payload = dict(config=DEFAULT.to_json(), sessions=len(days), comparison=cmp, verdict=verdict,
                   leakage=audits,
                   rejected_examples=sorted(blocked, key=lambda x: (x.get("end") or 0))[:10],
                   accepted_examples=accepted,
                   data_quality=dict(
                       blocked_without_forward_data=sum(1 for b in blocked if b.get("end") is None),
                       decisions_without_price_action=sum(1 for d in b_dec if d["thirteen_a"] in
                                                          ("BUY_CE", "BUY_PE") and not d["price_action"]),
                       unknown_verdicts=cmp["price_action_verdicts"].get("UNKNOWN", 0)))
    write_csv(blocked, ROOT / "13B_BLOCKED_CANDIDATES.csv")
    write_csv([d for d in b_dec if d.get("price_action")], ROOT / "13B_DECISION_LOG.csv")
    (ROOT / "13B_RESULTS.json").write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    report.build(payload, ROOT / "13B_PRICE_ACTION_REPORT.html")
    print("\nwritten: 13B_PRICE_ACTION_REPORT.html · 13B_RESULTS.json · "
          "13B_BLOCKED_CANDIDATES.csv · 13B_DECISION_LOG.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
