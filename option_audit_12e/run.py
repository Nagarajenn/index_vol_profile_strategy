"""Run the 12E audit: today first, then historical validation, then the report.

    venv/Scripts/python.exe -m option_audit_12e.run [--date YYYY-MM-DD] [--history N]

Diagnosis only: reads data the pipeline already captured, writes report files, changes nothing.
"""

import argparse
from datetime import date
from pathlib import Path

from option_audit_12e import audit, leakage, report
from option_audit_12e.answers import build_answers
from option_audit_12e.config import DEFAULT
from scalp_decision_12c import loader
from signal_learning_12d.run import usable_sessions

ROOT = Path(__file__).resolve().parent.parent


def collect(conn, days, symbols=("NIFTY", "SENSEX"), cfg=DEFAULT, verbose=True) -> list[dict]:
    rows = []
    for d in days:
        for sym in symbols:
            r = audit.diagnose_session(conn, sym, d, cfg)
            rows.extend(r)
            if verbose and r:
                print(f"  {d} {sym}: {len(r)} signals")
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description="12E option response & trade economics audit")
    ap.add_argument("--date", default=None, help="the session to treat as TODAY (default: latest with data)")
    ap.add_argument("--history", type=int, default=None, help="how many prior sessions to validate against")
    args = ap.parse_args()

    conn = loader.connect()
    days = usable_sessions(conn, min_minutes=60)
    today = date.fromisoformat(args.date) if args.date else days[-1]
    print(f"12E audit | config {DEFAULT.config_hash()} | today = {today}")

    print("\nTODAY")
    today_rows = collect(conn, [today])
    if not today_rows:
        print("no signals for today")
        return 1
    today_rep = audit.report(today_rows, f"TODAY {today}")

    hist_rows, hist_rep = [], None
    prior = [d for d in days if d < today]
    if args.history:
        prior = prior[-args.history:]
    if prior:
        print(f"\nHISTORICAL ({len(prior)} sessions, kept separate from today)")
        hist_rows = collect(conn, prior, verbose=False)
        if hist_rows:
            hist_rep = audit.report(hist_rows, "HISTORICAL")
            print(f"  {len(hist_rows)} signals across {hist_rep['sessions']} symbol-days")

    # formal leakage audit on today's sessions
    from option_risk_12b.engine import prepare as _prepare
    from signal_learning_12d.historical_replay import replay_session as _replay
    audits = []
    for sym in ("NIFTY", "SENSEX"):
        snaps = loader.load_snapshots(conn, sym, today, start="09:00")
        if not snaps:
            continue
        ser, cm = _prepare(snaps, loader.load_candles(conn, sym, today, start="09:00"))
        sigs = _replay(sym, today, ser, cm, audit._levels(conn, sym, today))
        rws = [r for r in today_rows if r["market"] == sym]
        a = leakage.audit_rows(ser, sigs, rws, cfg=DEFAULT)
        a["symbol"] = sym
        audits.append(a)
        print(f"  leakage {sym}: {'PASS' if a['passed'] else 'FAIL'} "
              f"({a['checked']} signals, {a['derived_future_fields_leaked']} derived-future leaks)")

    answers = build_answers(today_rep, today_rows, hist_rep)
    report.write_csv(today_rows, ROOT / "12E_AUDIT_TODAY.csv")
    if hist_rows:
        report.write_csv(hist_rows, ROOT / "12E_AUDIT_HISTORICAL.csv")
    report.write_json(dict(config=DEFAULT.to_json(), today=today_rep, historical=hist_rep,
                           leakage_audit=audits,
                           answers=[dict(question=q, answer=a) for q, a in answers]),
                      ROOT / "12E_OPTION_AUDIT.json")
    report.build_html(today_rep, today_rows, hist_rep, answers, ROOT / "milestone12e_option_audit.html")
    print("\nwritten: milestone12e_option_audit.html · 12E_OPTION_AUDIT.json · "
          "12E_AUDIT_TODAY.csv" + (" · 12E_AUDIT_HISTORICAL.csv" if hist_rows else ""))
    for q, a in answers:
        import re
        print(f"\nQ: {q}\nA: {re.sub('<[^>]+>', '', a)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
