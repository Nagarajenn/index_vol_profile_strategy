"""Descriptive analysis of the signal dataset. No models, no fitting, no ranking by tiny samples.

Every grouped statistic carries its N. A group below `cfg.min_sample` is reported as
INSUFFICIENT SAMPLE and its averages are shown but explicitly not interpreted -- the failure
mode this guards against is reading a mean of four trades as a property of the strategy.
"""

import statistics
from collections import Counter, defaultdict

from signal_learning_12d.config import DEFAULT


def _num(xs):
    return [x for x in xs if isinstance(x, (int, float))]


def describe(rows: list[dict], field: str = "final_pnl", cfg=DEFAULT) -> dict:
    """The standard block of statistics for one group of signals."""
    vals = _num([r.get(field) for r in rows])
    mfe = _num([r.get("mfe_per_unit") for r in rows])
    mae = _num([r.get("mae_per_unit") for r in rows])
    pos_mfe = [r for r in rows if isinstance(r.get("mfe_pct"), (int, float)) and r["mfe_pct"] >= cfg.small_pct]
    neg_mae = [r for r in rows if isinstance(r.get("mae_pct"), (int, float)) and r["mae_pct"] <= -cfg.small_pct]
    holds = _num([r.get("hold_minutes") for r in rows])
    return dict(
        n=len(rows), n_priced=len(vals),
        sufficient=len(rows) >= cfg.min_sample,
        note=None if len(rows) >= cfg.min_sample else "INSUFFICIENT SAMPLE",
        wins=sum(1 for v in vals if v > 0), losses=sum(1 for v in vals if v <= 0),
        win_rate=round(sum(1 for v in vals if v > 0) / len(vals) * 100, 1) if vals else None,
        avg_pnl=round(statistics.fmean(vals), 2) if vals else None,
        median_pnl=round(statistics.median(vals), 2) if vals else None,
        total_pnl=round(sum(vals), 2) if vals else None,
        avg_mfe=round(statistics.fmean(mfe), 2) if mfe else None,
        avg_mae=round(statistics.fmean(mae), 2) if mae else None,
        positive_mfe_rate=round(len(pos_mfe) / len(rows) * 100, 1) if rows else None,
        negative_mae_rate=round(len(neg_mae) / len(rows) * 100, 1) if rows else None,
        avg_hold_minutes=round(statistics.fmean(holds), 1) if holds else None,
    )


def by(rows: list[dict], key: str, cfg=DEFAULT) -> dict:
    groups = defaultdict(list)
    for r in rows:
        groups[r.get(key) if r.get(key) is not None else "UNKNOWN"].append(r)
    return {k: describe(v, cfg=cfg) for k, v in sorted(groups.items(), key=lambda x: -len(x[1]))}


def by_hour(rows: list[dict], cfg=DEFAULT) -> dict:
    groups = defaultdict(list)
    for r in rows:
        groups[(r.get("signal_minute") or "??:??")[:2] + ":00"].append(r)
    return {k: describe(v, cfg=cfg) for k, v in sorted(groups.items())}


def diagnostic_matrix(rows: list[dict]) -> dict:
    """Spec 21. Which part of the system is actually the problem?"""
    m, unknown = Counter(), 0
    for r in rows:
        e, x = r.get("entry_timing_ok"), r.get("exit_ok")
        if e is None or x is None:
            unknown += 1          # kept out of the Counter: its keys are (entry, exit) pairs
            continue
        m[("GOOD_ENTRY" if e else "BAD_ENTRY", "EXIT_GOOD" if x else "EXIT_BAD")] += 1
    dirm = Counter()
    for r in rows:
        d = r.get("direction_correct")
        dirm["DIRECTION_CORRECT" if d else "DIRECTION_WRONG" if d is False else "UNKNOWN"] += 1
    return dict(entry_exit={f"{a} / {b}": n for (a, b), n in m.items()},
                unknown=unknown, direction=dict(dirm))


def mfe_before_loss(rows: list[dict], cfg=DEFAULT) -> dict:
    """How many losing episodes were in profit at some point, and by how much.

    This is the single most diagnostic number in the milestone: a loss that was never in profit
    is a direction problem; a loss that gave back a real gain is an exit problem."""
    losers = [r for r in rows if isinstance(r.get("final_pnl"), (int, float)) and r["final_pnl"] <= 0]
    had = [r for r in losers if isinstance(r.get("mfe_pct"), (int, float)) and r["mfe_pct"] >= cfg.small_pct]
    big = [r for r in had if r["mfe_pct"] >= cfg.win_pct]
    return dict(losing_episodes=len(losers), had_positive_mfe=len(had),
                pct_of_losers=round(len(had) / len(losers) * 100, 1) if losers else None,
                had_mfe_above_win_threshold=len(big),
                avg_mfe_of_those=round(statistics.fmean([r["mfe_per_unit"] for r in had]), 2) if had else None)


def wait_survival(rows: list[dict]) -> dict:
    """How often the entry decision went WAIT while the position was still worth holding.

    Under the previous coupling every one of these would have been closed on the spot."""
    with_waits = [r for r in rows if (r.get("entry_waits_survived") or 0) > 0]
    profitable = [r for r in with_waits if isinstance(r.get("final_pnl"), (int, float)) and r["final_pnl"] > 0]
    waits = _num([r.get("entry_waits_survived") for r in with_waits])
    return dict(episodes_with_a_wait=len(with_waits),
                pct_of_all=round(len(with_waits) / len(rows) * 100, 1) if rows else None,
                of_those_profitable=len(profitable),
                pct_profitable=round(len(profitable) / len(with_waits) * 100, 1) if with_waits else None,
                avg_waits_survived=round(statistics.fmean(waits), 1) if waits else None,
                max_waits_survived=max(waits) if waits else None)


def report(rows: list[dict], cfg=DEFAULT) -> dict:
    """The complete descriptive picture. Nothing here recommends a change."""
    return dict(
        signals=len(rows),
        markets=dict(Counter(r["market"] for r in rows)),
        sessions=len({r["session_date"] for r in rows}),
        overall=describe(rows, cfg=cfg),
        by_direction=by(rows, "direction", cfg),
        by_confidence=by(rows, "confidence", cfg),
        by_entry_timing=by(rows, "entry_timing", cfg),
        by_momentum=by(rows, "momentum_state", cfg),
        by_exhaustion=by(rows, "exhaustion_state", cfg),
        by_exit_reason=by(rows, "exit_reason", cfg),
        by_lifecycle=by(rows, "lifecycle_label", cfg),
        by_outcome_label=by(rows, "outcome_label", cfg),
        by_hour=by_hour(rows, cfg),
        diagnostic_matrix=diagnostic_matrix(rows),
        mfe_before_loss=mfe_before_loss(rows, cfg),
        wait_survival=wait_survival(rows),
        position_paths=dict(Counter(r.get("position_path") for r in rows).most_common(12)),
        min_sample=cfg.min_sample,
        caveat=("Descriptive only. These are observations of an existing signal on a limited sample, "
                "not evidence of an edge and not a basis for changing a threshold."),
    )


def format_text(rep: dict, cfg=DEFAULT) -> str:
    """The daily learning report (spec 25), as plain text."""
    L = []
    a = rep["overall"]
    L.append("12D SIGNAL LEARNING REPORT")
    L.append("=" * 74)
    L.append(f"Signals: {rep['signals']}   Sessions: {rep['sessions']}   Markets: {rep['markets']}")
    L.append(f"Average P&L: Rs {a['avg_pnl']}   Median: Rs {a['median_pnl']}   Total: Rs {a['total_pnl']}")
    L.append(f"Win rate: {a['win_rate']}%   Avg MFE/unit: {a['avg_mfe']}   Avg MAE/unit: {a['avg_mae']}")
    L.append(f"Positive MFE rate: {a['positive_mfe_rate']}%   Negative MAE rate: {a['negative_mae_rate']}%")
    L.append(f"Average hold: {a['avg_hold_minutes']} min")

    def block(title, d):
        L.append("")
        L.append(title)
        L.append("-" * len(title))
        for k, v in d.items():
            flag = "" if v["sufficient"] else "   << INSUFFICIENT SAMPLE"
            L.append(f"  {str(k):34} N={v['n']:<5} avg Rs {str(v['avg_pnl']):>9}  "
                     f"med Rs {str(v['median_pnl']):>9}  win {str(v['win_rate']):>5}%  "
                     f"posMFE {str(v['positive_mfe_rate']):>5}%{flag}")

    for title, key in (("BY ENTRY TIMING", "by_entry_timing"), ("BY MOMENTUM AT ENTRY", "by_momentum"),
                       ("BY MOVE EXHAUSTION", "by_exhaustion"), ("BY CONFIDENCE", "by_confidence"),
                       ("BY DIRECTION", "by_direction"), ("BY EXIT REASON", "by_exit_reason"),
                       ("BY LIFECYCLE", "by_lifecycle"), ("BY HOUR", "by_hour")):
        block(title, rep[key])

    m = rep["mfe_before_loss"]
    L.append("")
    L.append("LOSSES THAT WERE ONCE IN PROFIT")
    L.append("-" * 31)
    L.append(f"  Losing episodes           : {m['losing_episodes']}")
    L.append(f"  Of those, had positive MFE: {m['had_positive_mfe']} ({m['pct_of_losers']}%)")
    L.append(f"  MFE above the win band    : {m['had_mfe_above_win_threshold']}")
    L.append(f"  Average MFE of those      : {m['avg_mfe_of_those']} per unit")

    w = rep["wait_survival"]
    L.append("")
    L.append("ENTRY WAIT vs POSITION MANAGEMENT")
    L.append("-" * 33)
    L.append(f"  Episodes where the entry engine said WAIT while holding: {w['episodes_with_a_wait']} "
             f"({w['pct_of_all']}%)")
    L.append(f"  Of those, ended profitable: {w['of_those_profitable']} ({w['pct_profitable']}%)")
    L.append(f"  Average WAIT minutes survived: {w['avg_waits_survived']}   max: {w['max_waits_survived']}")
    L.append("  Under the previous coupling every one of these would have been closed immediately.")

    d = rep["diagnostic_matrix"]
    L.append("")
    L.append("DIAGNOSTIC MATRIX")
    L.append("-" * 17)
    for k, v in d["entry_exit"].items():
        L.append(f"  {k:28} {v}")
    L.append(f"  unknown: {d['unknown']}")
    L.append(f"  direction: {d['direction']}")
    L.append("")
    L.append(f"Groups below N={cfg.min_sample} are marked INSUFFICIENT SAMPLE and must not be interpreted.")
    L.append(rep["caveat"])
    return "\n".join(L)
