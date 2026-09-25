"""Run 13A end to end: reconcile, replay, split, audit, report.

    venv/Scripts/python.exe -m live_scalping_13a.run [--sessions N] [--case-study YYYY-MM-DD]

Decision support only. No order is placed and no broker is contacted.
"""

import argparse
import csv
import json
from datetime import date
from pathlib import Path

from scalp_decision_12c import loader
from live_scalping_13a import analysis, reconcile, replay, report
from live_scalping_13a.config import DEFAULT
from signal_learning_12d.run import usable_sessions

ROOT = Path(__file__).resolve().parent.parent


def write_csv(rows, path, columns=None):
    if not rows:
        return
    columns = columns or list(rows[0].keys())
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def main() -> int:
    ap = argparse.ArgumentParser(description="13A live scalping engine")
    ap.add_argument("--sessions", type=int, default=None)
    ap.add_argument("--case-study", default="2026-09-24")
    args = ap.parse_args()
    cfg = DEFAULT
    conn = loader.connect()
    print(f"13A | config {cfg.config_hash()} | gates {cfg.gates.config_hash()} | risk {cfg.risk.config_hash()}")

    # ---- 1. reconciliation gate (spec 2) --------------------------------------------------
    print("\n[1] P&L reconciliation")
    rec = reconcile.run(conn)
    print(f"    research identity : {'EXACT' if rec['research_identity']['exact'] else 'FAIL'} "
          f"({rec['research_identity']['checked']} rows)")
    print(f"    command centre    : {'EXACT' if rec['command_center_identity']['exact'] else 'FAIL'} "
          f"({rec['command_center_identity']['checked']} rows)")
    x = rec["cross_source"]
    print(f"    cross-source      : {'EXACT' if x['exact'] else 'FAIL'} "
          f"({x['matched_same_exit_minute']} same-minute matches, "
          f"{x['matched_different_exit_minute']} explained by differing exit rules)")
    print(f"    GATE: {'PASS' if rec['passed'] else 'FAIL'}")
    write_csv(reconcile.csv_rows(rec, rec["research_rows"]), ROOT / "13A_RECONCILIATION.csv")

    # ---- 2. replay -------------------------------------------------------------------------
    days = usable_sessions(conn, min_minutes=60)
    if args.sessions:
        days = days[-args.sessions:]
    print(f"\n[2] Replay over {len(days)} sessions")
    all_dec, all_pos, all_rej, by_day = [], [], {}, {}
    for d in days:
        for sym in ("NIFTY", "SENSEX"):
            r = replay.replay_session(conn, sym, d, cfg)
            if not r["decisions"]:
                continue
            for x2 in r["decisions"]:
                x2["market"], x2["session_date"] = sym, str(d)
            all_dec.extend(r["decisions"])
            for p in r["positions"]:
                p["market"] = sym
            all_pos.extend(r["positions"])
            for k, v in r["rejections"].items():
                all_rej[k] = all_rej.get(k, 0) + v
            by_day.setdefault(d, {"positions": [], "rejections": {}, "decisions": []})
            by_day[d]["positions"].extend(r["positions"])
            by_day[d]["decisions"].extend(r["decisions"])
            for k, v in r["rejections"].items():
                by_day[d]["rejections"][k] = by_day[d]["rejections"].get(k, 0) + v
    print(f"    {len(all_dec)} decisions -> {len(all_pos)} simulated trades")
    write_csv(all_dec, ROOT / "13A_DECISION_LOG.csv")

    # ---- 3. dev / validation / unseen (spec 25) -----------------------------------------------
    split = replay.split_dates(days)
    periods = {}
    for name, ds in split.items():
        pos = [p for p in all_pos if date.fromisoformat(p["session_date"]) in ds]
        rej = {}
        for d in ds:
            for k, v in by_day.get(d, {}).get("rejections", {}).items():
                rej[k] = rej.get(k, 0) + v
        base = analysis.baseline_from_12d(conn, ds)
        periods[name] = analysis.compare(name, pos, base, rej)
        periods[name]["sessions"] = len(ds)
        periods[name]["dates"] = [str(x) for x in ds]
    print("\n[3] Period split")
    for name, p in periods.items():
        a, b = p["thirteen_a"], p["twelve_d"]
        print(f"    {name:12} {p['sessions']:2} sessions | 12D {b['trades']:4} trades "
              f"Rs {b['total_pnl']} -> 13A {a['trades']:3} trades Rs {a['total_pnl']}"
              + ("" if a["sufficient"] else "   << INSUFFICIENT SAMPLE"))

    overall = analysis.compare("ALL", all_pos, analysis.baseline_from_12d(conn, days), all_rej)

    # ---- 4. case study (spec 32) ------------------------------------------------------------------
    cs_date = date.fromisoformat(args.case_study)
    cs = {"date": str(cs_date), "symbols": {}}
    for sym in ("NIFTY", "SENSEX"):
        r = replay.replay_session(conn, sym, cs_date, cfg)
        cs["symbols"][sym] = dict(base_signals=r["base_signals"], rejections=r["rejections"],
                                  positions=r["positions"],
                                  buys=[d2 for d2 in r["decisions"] if d2["decision"] != "WAIT"],
                                  review=analysis.daily_review(r["decisions"], r["positions"],
                                                               r["rejections"]))

    # ---- 5. leakage audit ----------------------------------------------------------------------------
    print("\n[4] Leakage audit")
    audits = [replay.leakage_audit(conn, sym, cs_date, cfg) for sym in ("NIFTY", "SENSEX")]
    for a in audits:
        print(f"    {a['symbol']}: {'PASS' if a['passed'] else 'FAIL'} "
              f"({a['checked']} candidates x {a['fields_compared']} fields, "
              f"{len(a['mismatches'])} mismatches)")

    payload = dict(config=cfg.to_json(), reconciliation={k: v for k, v in rec.items()
                                                         if k not in ("research_rows", "command_rows")},
                   overall=overall, periods=periods, case_study=cs, leakage=audits,
                   sessions=len(days))
    (ROOT / "13A_CONFIG.json").write_text(json.dumps(cfg.to_json(), indent=2), encoding="utf-8")
    (ROOT / "13A_RESULTS.json").write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    report.build_implementation_report(payload, ROOT / "13A_IMPLEMENTATION_REPORT.html")
    report.build_replay_report(payload, ROOT / "13A_REPLAY_REPORT.html")
    print("\nwritten: 13A_IMPLEMENTATION_REPORT.html · 13A_REPLAY_REPORT.html · "
          "13A_DECISION_LOG.csv · 13A_RECONCILIATION.csv · 13A_CONFIG.json · 13A_RESULTS.json")
    return 0 if rec["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
