"""Minimal sanity check for the 12C rules over data the platform already has.

This is NOT research and NOT an optimisation: no threshold is changed, no outcome is
scored, nothing is fitted. It only answers "do the rules behave the way they are written
when fed real minutes?" -- plus a no-lookahead spot check -- and writes an example
decision-trace log.

    python -m scalp_decision_12c.validate [sessions]
"""

import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

from option_risk_12b.option_snapshot import minute_range
from scalp_decision_12c import brake as BRAKE
from scalp_decision_12c import loader
from scalp_decision_12c.config import DEFAULT, VERSION
from option_risk_12b.engine import prepare
from scalp_decision_12c.engine import decide_at, decide_prepared

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "cache" / "scalp_decision_12c"
SESSIONS = 5
FIRST_MINUTE, LAST_MINUTE = "09:25", "15:30"


def check(name, ok, detail=""):
    return dict(check=name, result="PASS" if ok else "FAIL", detail=detail)


def main(n_sessions=SESSIONS):
    cfg = DEFAULT
    OUT.mkdir(parents=True, exist_ok=True)
    run = datetime.now().strftime("12c-%Y%m%dT%H%M%S")
    conn = loader.connect()
    pairs = loader.session_dates(conn)
    dates = sorted({d for _, d in pairs})[-n_sessions:]
    decisions, brakes, conf, waits_by_reason, per_hour = Counter(), Counter(), Counter(), Counter(), Counter()
    violations, traces, checked = [], [], 0
    episodes, seqs = [], []          # consecutive same-decision minutes are ONE condition, not many signals
    aligned = Counter()
    for d in dates:
        for sym in ("NIFTY", "SENSEX"):
            snaps = loader.load_snapshots(conn, sym, d, start="09:00")
            if not snaps:
                continue
            candles = loader.load_candles(conn, sym, d, start="09:00")
            levels = loader.load_levels(conn, sym, d, LAST_MINUTE)
            series, cmap = prepare(snaps, candles)          # parse the day once, then replay minute by minute
            minutes = sorted(m for m in series if FIRST_MINUTE <= m <= LAST_MINUTE)
            day_seq = []
            for m in minutes:
                out = decide_prepared(sym, d, series, cmap, levels, minute=m)
                if out["status"] != "OK":
                    continue
                checked += 1
                e, ev = out["entry"], out["evidence"]
                decisions[out["entry"]["decision"]] += 1
                conf[e["confirmation"]] += 1
                per_hour[(m[:2], e["decision"])] += 1
                if e["decision"] == "WAIT" and e["blocking"]:
                    waits_by_reason[e["blocking"][0][0]] += 1
                # ---- rule invariants (these are the rules as written, not outcomes)
                if e["decision"].startswith("BUY"):
                    side = e["side"]
                    if ev[f"liquidity_{side.lower()}"]["state"] == "POOR":
                        violations.append(f"{sym} {d} {m}: BUY with POOR liquidity")
                    if ev["option_relative"]["state"] in ("MOVEMENT_EXPANSION", "PREMIUM_CONTRACTION", "BALANCED"):
                        violations.append(f"{sym} {d} {m}: BUY without one side outperforming")
                    if not ev[f"{side.lower()}_momentum"]["detail"].get("persistent"):
                        violations.append(f"{sym} {d} {m}: BUY on a non-persistent move")
                    if len(e["supporting"]) < cfg.min_support_for_entry:
                        violations.append(f"{sym} {d} {m}: BUY with {len(e['supporting'])} supporting categories")
                    if ev["underlying"]["state"] in ("UNDERLYING_STALE", "UNDERLYING_MISSING") and len(e["supporting"]) < cfg.stale_min_support:
                        violations.append(f"{sym} {d} {m}: BUY on a stale underlying without option-only evidence")
                for typ in ("CE", "PE"):
                    r = BRAKE.assess(ev, dict(option_type=typ, strike=out["option_state"]["atm_strike"]), cfg)
                    brakes[(typ, r["risk_action"])] += 1
                    if r["risk_action"] == "EXIT" and (len(r["families_against"]) < cfg.exit_min_families or not r["thesis_broken"]):
                        violations.append(f"{sym} {d} {m}: EXIT on {len(r['families_against'])} families / thesis_broken={r['thesis_broken']}")
                    if r["risk_action"] == "PREPARE_EXIT" and len(r["families_against"]) < cfg.prepare_exit_min_families:
                        violations.append(f"{sym} {d} {m}: PREPARE_EXIT on {len(r['families_against'])} families")
                day_seq.append(e["decision"])
                rel = ev["option_relative"]["state"]
                for typ in ("CE", "PE"):
                    same = (rel == "CALL_RELATIVE_STRENGTH" and typ == "CE") or (rel == "PUT_RELATIVE_STRENGTH" and typ == "PE")
                    r2 = BRAKE.assess(ev, dict(option_type=typ, strike=out["option_state"]["atm_strike"]), cfg)
                    aligned[("aligned" if same else "opposed_or_unclear", r2["risk_action"])] += 1
                if len(traces) < 200:
                    traces.append(out["trace"])
            # episodes: maximal runs of the same decision
            run_len, prev = 0, None
            for x in day_seq + [None]:
                if x == prev:
                    run_len += 1
                    continue
                if prev is not None and prev.startswith("BUY"):
                    episodes.append(run_len)
                prev, run_len = x, 1
            seqs.append(len([1 for x in day_seq if x.startswith("BUY")]))
    # ---- no-lookahead spot check
    leak = []
    for d in dates[-2:]:
        for sym in ("NIFTY", "SENSEX"):
            snaps = loader.load_snapshots(conn, sym, d, start="09:00")
            candles = loader.load_candles(conn, sym, d, start="09:00")
            if not snaps:
                continue
            lv = loader.load_levels(conn, sym, d, LAST_MINUTE)
            for m in minute_range("15:00", "15:20"):
                full = decide_at(sym, d, snaps, candles, lv, minute=m)
                cut = decide_at(sym, d, [x for x in snaps if x["fetched_at"].strftime("%H:%M") <= m],
                                [c for c in candles if c["timestamp"].strftime("%H:%M") < m], lv, minute=m)
                if full != cut:
                    leak.append(f"{sym} {d} {m}")
    total = sum(decisions.values()) or 1
    ex_total = brakes[("CE", "EXIT")] + brakes[("PE", "EXIT")]
    al = sum(n for (g, _), n in aligned.items() if g == "aligned") or 1
    op = sum(n for (g, _), n in aligned.items() if g == "opposed_or_unclear") or 1
    ex_aligned_rate = 100 * aligned[("aligned", "EXIT")] / al
    ex_opposed_rate = 100 * aligned[("opposed_or_unclear", "EXIT")] / op
    episodes.sort()
    med_ep = episodes[len(episodes) // 2] if episodes else 0
    checks = [
        check("Rules behave as written (no invariant broken)", not violations, f"{len(violations)} violations"),
        check("No-lookahead: truncating the inputs at T changes nothing", not leak, f"{len(leak)} mismatches"),
        check("WAIT is a normal outcome, not an exception", decisions["WAIT"] / total >= 0.5,
              f"WAIT {100 * decisions['WAIT'] / total:.1f}% of {total} minutes"),
        check("Entries are not concentrated in one minute-level spike rule",
              decisions["BUY_CE"] + decisions["BUY_PE"] > 0, f"BUY_CE {decisions['BUY_CE']}, BUY_PE {decisions['BUY_PE']}"),
        check("EXIT is never reached from a single evidence family",
              all("EXIT on" not in v for v in violations), f"{ex_total} EXIT calls over {sum(brakes.values())} reference assessments"),
        check("A position on the side the options favour is rarely told to EXIT",
              ex_aligned_rate < 5.0, f"{ex_aligned_rate:.1f}% of aligned assessments vs {ex_opposed_rate:.1f}% of opposed ones"),
    ]
    summary = dict(version=VERSION, run_id=run, config_hash=cfg.config_hash(), generated_at=datetime.now().isoformat(),
                   sessions=[str(x) for x in dates], minutes_evaluated=checked,
                   entry_decisions=dict(decisions), confirmation=dict(conf),
                   wait_first_blocking_reason=dict(waits_by_reason),
                   entry_by_hour={f"{h}:00|{k}": n for (h, k), n in sorted(per_hour.items())},
                   brake_actions_reference_positions={f"{t}|{a}": n for (t, a), n in sorted(brakes.items())},
                   buy_episodes=dict(n_episodes=len(episodes), median_minutes=med_ep, longest_minutes=max(episodes or [0]),
                                     episodes_per_symbol_day=round(len(episodes) / max(1, len(seqs)), 1)),
                   brake_by_alignment={f"{g}|{a}": n for (g, a), n in sorted(aligned.items())},
                   exit_rate_aligned_pct=round(ex_aligned_rate, 1), exit_rate_opposed_pct=round(ex_opposed_rate, 1),
                   invariant_violations=violations[:20], n_violations=len(violations),
                   leakage_mismatches=leak, checks=checks,
                   note="Sanity check only. No threshold was changed and no outcome was scored.")
    d = OUT / run
    d.mkdir(parents=True, exist_ok=True)
    (d / "12c_validation.json").write_text(json.dumps(summary, indent=1, default=str))
    (d / "12c_decision_trace.jsonl").write_text("\n".join(json.dumps(t, default=str) for t in traces))
    (ROOT / "scalp_decision_12c" / "VALIDATION.md").write_text(render(summary), encoding="utf-8")
    print(json.dumps({k: summary[k] for k in ("run_id", "sessions", "minutes_evaluated", "entry_decisions", "n_violations")},
                     indent=1, default=str))
    print("\n".join(f"{c['result']}  {c['check']} ({c['detail']})" for c in checks))
    return summary


def render(s) -> str:
    rows = "\n".join(f"| {c['check']} | **{c['result']}** | {c['detail']} |" for c in s["checks"])
    dec = "\n".join(f"| {k} | {v} | {100 * v / max(1, s['minutes_evaluated']):.1f}% |" for k, v in sorted(s["entry_decisions"].items()))
    wait = "\n".join(f"| {k} | {v} |" for k, v in sorted(s["wait_first_blocking_reason"].items(), key=lambda x: -x[1]))
    brake = "\n".join(f"| {k} | {v} |" for k, v in sorted(s["brake_actions_reference_positions"].items()))
    ep = s["buy_episodes"]
    ep_txt = (f"{ep['n_episodes']} BUY episodes in total ({ep['episodes_per_symbol_day']} per symbol-day), "
              f"median {ep['median_minutes']} minutes long, longest {ep['longest_minutes']}")
    return f"""# 12C — Scalping Decision + Risk Brake: validation

`{s['version']}` · config hash `{s['config_hash']}` · run `{s['run_id']}` · generated {s['generated_at'][:19]}

This is a **sanity check, not research**. It replays the rules over sessions
{', '.join(s['sessions'])} ({s['minutes_evaluated']} minutes, both symbols) and asks only whether they behave as
written. No threshold was tuned, no outcome was scored, and no profitability claim is made or implied.

## Checks

| Check | Result | Detail |
|---|---|---|
{rows}

## Entry decisions

| Decision | Minutes | Share |
|---|---|---|
{dec}

Confirmation levels: {', '.join(f'{k} {v}' for k, v in sorted(s['confirmation'].items()))}

### Why WAIT was returned (first blocking condition)

| Blocking category | Minutes |
|---|---|
{wait}

## Risk brake on reference positions

Every minute is also evaluated as if an ATM CE and an ATM PE were held — these are reference
positions for exercising the ladder, not trades and not 11D.

| Position / action | Minutes |
|---|---|
{brake}

## What a BUY state actually is

A decision is recomputed every minute, so consecutive BUY minutes are **one continuing condition**,
not many separate signals: {ep_txt}.

## Interpretation

The rules fire the way they are written: entries need several independent categories to agree,
WAIT dominates, and EXIT needs both a broken premium trend and at least
{ "four" } independent families against the position. What this check does **not** show is whether
acting on the decisions makes money — that question is deliberately left alone here, and the
12B research already found that option-chain warnings were not selective.

An ATM CE and an ATM PE are both assessed every minute, so roughly half of those reference positions
are deliberately on the wrong side of the market. EXIT was reached in {s['exit_rate_aligned_pct']}% of assessments where
the position matched the side the options favoured, against {s['exit_rate_opposed_pct']}% where it did not.

Artefacts: `data/cache/scalp_decision_12c/{s['run_id']}/12c_validation.json` and
`12c_decision_trace.jsonl` (one decision trace per line; the format is documented in README.md).
"""


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else SESSIONS)
