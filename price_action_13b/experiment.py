"""13B-EXP-1: does allowing PARTIAL preserve useful entries without losing the protection?

One isolated change: `block_on_partial = False`. Every other threshold, and all of 13A, is
identical to the committed baseline. The three paths are replayed from the same inputs in the
same pass so nothing can drift between them.

    venv/Scripts/python.exe -m price_action_13b.experiment [--sessions N]

Paper / advisory only. No broker API, no order, no change to the committed 13B default.
"""

import argparse
import csv
import json
from datetime import date
from pathlib import Path

from scalp_decision_12c import loader
from price_action_13b import analysis, replay
from price_action_13b.config import DEFAULT, EXPERIMENT_ALLOW_PARTIAL, EXPERIMENT_VERSION
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


def collect(conn, days, symbols=("NIFTY", "SENSEX")):
    acc = {k: {"positions": [], "blocked": [], "decisions": []} for k in ("a", "b", "c")}
    for d in days:
        for sym in symbols:
            r = replay.replay_session(conn, sym, d, DEFAULT)
            if not r:
                continue
            for k in ("a", "b", "c"):
                for x in r[k]["decisions"]:
                    x["market"], x["session_date"] = sym, str(d)
                acc[k]["positions"] += r[k]["positions"]
                acc[k]["blocked"] += r[k]["blocked"]
                acc[k]["decisions"] += r[k]["decisions"]
    return acc


def today_rows(acc) -> list[dict]:
    """Spec's live comparison table: every candidate, both paths, side by side."""
    today = str(date.today())
    by_key = {}
    for k in ("a", "c"):
        for dcn in acc[k]["decisions"]:
            if dcn["session_date"] != today:
                continue
            key = (dcn["market"], dcn["minute"])
            row = by_key.setdefault(key, dict(timestamp=dcn["minute"], symbol=dcn["market"]))
            if k == "a":
                row["path_a_13a_decision"] = dcn["thirteen_a"]
            else:
                row["price_action_verdict"] = dcn.get("price_action")
                row["path_b_final_decision"] = dcn["final"]
                row["price_action_reason"] = (dcn.get("pa_reason") or "")[:300]
    for p in acc["c"]["positions"]:
        if p["session_date"] != today:
            continue
        r = by_key.setdefault((p["market"], p["signal_minute"]),
                              dict(timestamp=p["signal_minute"], symbol=p["market"]))
        r.update(contract=p["contract"], entry_ask=p["entry_ask"], exit_bid=p.get("exit_bid"),
                 pnl=p.get("realised_pnl"), mfe=p.get("mfe_per_unit"), mae=p.get("mae_per_unit"),
                 exit_reason=p.get("exit_reason"), path=" EXPERIMENT (allow PARTIAL)")
    for p in acc["a"]["positions"]:
        if p["session_date"] != today:
            continue
        r = by_key.setdefault((p["market"], p["signal_minute"]),
                              dict(timestamp=p["signal_minute"], symbol=p["market"]))
        r.setdefault("path_a_contract", p["contract"])
        r.setdefault("path_a_entry_ask", p["entry_ask"])
        r.setdefault("path_a_pnl", p.get("realised_pnl"))
        r.setdefault("path_a_mfe", p.get("mfe_per_unit"))
        r.setdefault("path_a_mae", p.get("mae_per_unit"))
        r.setdefault("path_a_exit_reason", p.get("exit_reason"))
    return [by_key[k] for k in sorted(by_key, key=lambda x: (x[0], x[1]))
            if by_key[k].get("price_action_verdict") or by_key[k].get("path_a_contract")]


def main() -> int:
    ap = argparse.ArgumentParser(description="13B PARTIAL experiment")
    ap.add_argument("--sessions", type=int, default=None)
    args = ap.parse_args()
    conn = loader.connect()
    days = usable_sessions(conn, min_minutes=60)
    if args.sessions:
        days = days[-args.sessions:]
    print(f"{EXPERIMENT_VERSION}")
    print(f"  baseline   13B default    config {DEFAULT.config_hash()}  block_on_partial=True")
    print(f"  experiment 13B allow-PART config {EXPERIMENT_ALLOW_PARTIAL.config_hash()}  block_on_partial=False")
    print(f"  {len(days)} sessions\n")

    acc = collect(conn, days)
    cmp = analysis.three_way(acc["a"]["positions"], acc["b"]["positions"], acc["c"]["positions"],
                             acc["a"]["decisions"], acc["b"]["decisions"], acc["c"]["decisions"],
                             acc["b"]["blocked"], acc["c"]["blocked"])
    for k, lbl in (("baseline", "13A alone"), ("default", "13B default"),
                   ("experiment", "13B allow-PARTIAL")):
        s = cmp[k]
        print(f"  {lbl:20} {s['trades']:3} trades  total {str(s['total_pnl']):>10}  "
              f"win {str(s['win_rate']):>5}%  maxDD {str(s['max_drawdown']):>10}"
              + ("" if s["sufficient"] else "   << INSUFFICIENT SAMPLE"))
    print(f"\n  candidate minutes  {cmp['candidate_minutes']}")
    print(f"  filtering          default {cmp['filtering_default']}%  "
          f"experiment {cmp['filtering_experiment']}%")
    print(f"  PARTIAL allowed    {cmp['partial_allowed']}")

    audits = [replay.leakage_audit(conn, s, days[-1], EXPERIMENT_ALLOW_PARTIAL)
              for s in ("NIFTY", "SENSEX")]
    for a in audits:
        print(f"  leakage {a['symbol']}: {'PASS' if a['passed'] else 'FAIL'} "
              f"({a['checked']} candidates, {len(a['mismatches'])} mismatches, "
              f"future-bar uses {a['future_bar_used']})")

    live = today_rows(acc)
    payload = dict(experiment_version=EXPERIMENT_VERSION,
                   baseline_config=DEFAULT.to_json(),
                   experiment_config=EXPERIMENT_ALLOW_PARTIAL.to_json(),
                   only_difference="block_on_partial: True -> False",
                   sessions=len(days), comparison=cmp, leakage=audits,
                   today=live,
                   partial_allowed_examples=[p for p in acc["c"]["positions"]
                                             if p.get("price_action") == "PARTIAL"][:15])
    write_csv(live, ROOT / "13B_EXP_TODAY_COMPARISON.csv")
    write_csv(acc["c"]["blocked"], ROOT / "13B_EXP_BLOCKED.csv")
    write_csv(acc["c"]["positions"], ROOT / "13B_EXP_TRADES.csv")
    (ROOT / "13B_EXP_RESULTS.json").write_text(json.dumps(payload, indent=2, default=str),
                                               encoding="utf-8")
    from price_action_13b import exp_report
    exp_report.build(payload, ROOT / "13B_PARTIAL_EXPERIMENT_REPORT.html")
    print("\nwritten: 13B_PARTIAL_EXPERIMENT_REPORT.html · 13B_EXP_RESULTS.json · "
          "13B_EXP_TODAY_COMPARISON.csv · 13B_EXP_BLOCKED.csv · 13B_EXP_TRADES.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
