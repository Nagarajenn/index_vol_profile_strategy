"""12B historical research runner (read-only). Writes versioned files only; creates no tables.

python -m option_risk_12b.run
"""

import csv
import json
import re
import statistics
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from scipy import stats

from option_risk_12b import loader
from option_risk_12b import research as R
from option_risk_12b.closing_state import LIVE, STALE, UNCERTAIN, MISSING, underlying_states
from option_risk_12b.config import DEFAULT, VERSION
from option_risk_12b.engine import _clean, build_session, minute_view, prepare, truncate
from option_risk_12b.option_snapshot import minute_range, resolve_atm, strike_window

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "milestone12b_option_risk"
HTML = ROOT / "milestone12b_option_risk_closing_state.html"
ORDER_TERMS = ["place" + "_order", "modify" + "_order", "cancel" + "_order", "dhan" + "_client", "/" + "orders"]
COHORTS = [("11D_SHAPED_1500_1519", "15:00", "15:19"), ("CLOSING_1515_1529", "15:15", "15:29")]


def write_csv(path, rows):
    if not rows:
        path.write_text("")
        return
    keys = list(dict.fromkeys(k for r in rows for k in r))
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        for r in rows:
            w.writerow({k: (json.dumps(v) if isinstance(v, (list, dict)) else v) for k, v in r.items()})


def leakage_truncation(series, cmap, symbol, d, cfg, minutes) -> tuple[int, list]:
    full_und = underlying_states(series, cmap, minute_range(cfg.lookback_start, cfg.window_end), cfg)
    checked, bad = 0, []
    for m in minutes:
        s_t, c_t = truncate(series, cmap, m)
        und_t = underlying_states(s_t, c_t, minute_range(cfg.lookback_start, m), cfg)
        a = _clean(minute_view(series, cmap, m, full_und, d, symbol, cfg))
        b = _clean(minute_view(s_t, c_t, m, und_t, d, symbol, cfg))
        checked += 1
        if a != b:
            bad.append(f"{symbol} {d} {m}")
    return checked, bad


def static_checks() -> dict:
    pkg = ROOT / "option_risk_12b"
    live_modules = ["option_snapshot.py", "option_state.py", "option_trajectory.py", "option_pressure.py", "option_risk.py",
                    "closing_state.py", "engine.py"]
    txt = {m: (pkg / m).read_text(encoding="utf-8") for m in live_modules}
    return dict(
        previous_oi_not_used=all("previous_oi" not in re.sub(r'""".*?"""', "", t, flags=re.S) for t in txt.values()),
        official_close_not_in_live_modules=all("daily_close" not in t and "raw_daily_candles" not in t for t in txt.values()),
        no_clock_in_live_modules=all("datetime.now" not in t and "time.time(" not in t for t in txt.values()),
        no_order_code=all(not re.search("|".join(ORDER_TERMS), (pkg / p.name).read_text(encoding="utf-8"))
                          for p in pkg.glob("*.py")),
    )


def main():
    cfg = DEFAULT
    OUT.mkdir(exist_ok=True)
    run_id = datetime.now().strftime("12b-%Y%m%dT%H%M%S")
    conn = loader.connect()
    pairs = loader.session_dates(conn)
    paper = loader.load_paper_positions(conn)
    audit, traj, np_rows, sig_rows, events, refs = [], [], [], [], [], []
    greek = Counter()
    spread = Counter()
    dq = Counter()
    stale_days = Counter()
    minute_state = Counter()
    active_while_stale = Counter()
    leak_checked, leak_bad = 0, []
    for sym, d in pairs:
        snaps = loader.load_snapshots(conn, sym, d)
        if not any(s["fetched_at"].strftime("%H:%M") >= cfg.window_start for s in snaps):
            audit.append(dict(symbol=sym, date=str(d), first_snapshot_after_1515=None, snapshots_1515_1530=0,
                              note="no option snapshot at or after 15:15 on this date"))
            continue
        cands = loader.load_candles(conn, sym, d)
        audit.append(R.data_audit(sym, d, snaps, cfg))
        out = build_session(sym, d, snaps, cands, cfg=cfg)
        series, cmap = prepare(snaps, cands)
        traj += R.trajectory_rows(out, cfg)
        win = [r for r in out["minutes"] if r["minute"] >= cfg.window_start]
        for r in win:
            for f in r["data_quality"]:
                dq[f] += 1
            dq["_minutes"] += 1
            if r["snapshot_present"]:
                st = r["underlying"]["state"]
                minute_state[(sym, st)] += 1
                if st in (STALE, UNCERTAIN, MISSING):
                    active_while_stale[(sym, r["option_activity"]["status"])] += 1
        has_stale = any(r["underlying"]["state"] == STALE for r in win if "15:16" <= r["minute"] <= "15:29")
        stale_days[(sym, has_stale)] += 1
        # greeks validity / spread expansion
        s1515 = out["minutes"][[r["minute"] for r in out["minutes"]].index(cfg.window_start)] if cfg.window_start in [r["minute"] for r in out["minutes"]] else None
        for r in win:
            s = series.get(r["minute"])
            if not s or r["atm_strike"] is None:
                continue
            for k in strike_window(s, r["atm_strike"], cfg.strikes_each_side):
                for t in ("CE", "PE"):
                    q = s["legs"].get((t, k))
                    if not q:
                        continue
                    itm = (t == "CE" and k < r["atm_strike"]) or (t == "PE" and k > r["atm_strike"])
                    key = f"{t}_{'ITM' if itm else ('ATM' if k == r['atm_strike'] else 'OTM')}"
                    greek[(key, q["greeks_status"])] += 1
            if s1515 and s1515["snapshot_present"]:
                for side in ("ce", "pe"):
                    sp, sp0 = r[side].get("spread_pct"), s1515[side].get("spread_pct")
                    if sp is None:
                        continue
                    spread["n"] += 1
                    spread["wide"] += sp >= cfg.wide_spread_pct
                    if sp0:
                        spread["n_ratio"] += 1
                        spread["expanded"] += sp >= cfg.spread_expansion_ratio * sp0
        np_row = R.next_print(out, cmap, loader.load_daily_close(conn, sym, d), cfg)
        if np_row:
            und15 = next((r["underlying"]["value"] for r in out["minutes"] if r["minute"] == cfg.context_start), None)
            np_row.update(symbol=sym, date=str(d), expiry_day=str(d) == (audit[-1].get("expiry")),
                          pre_stale_momentum=(np_row["frozen_value"] - und15) if und15 is not None else None)
            np_rows.append(np_row)
            for sg in R.next_print_signals(out, series, np_row, cfg):
                sg.update(symbol=sym, date=str(d), print_move=np_row["print_move"], print_known_at=np_row["print_known_at"],
                          stale_start=np_row["stale_start"], month=str(d)[:7], expiry_day=np_row["expiry_day"])
                sig_rows.append(sg)
        events += R.event_study(out, cfg, sym)
        refs += R.reference_positions(series, cmap, sym, d, cfg, COHORTS)
        c, b = leakage_truncation(series, cmap, sym, d, cfg, [r["minute"] for r in out["minutes"]])
        leak_checked += c
        leak_bad += b

    # ---------------- next-print hit tables
    eps = lambda s: cfg.underlying_move_pts[s]
    hit = {}
    for h in (5, 10, 15):
        for scope in ("ALL", "NIFTY", "SENSEX"):
            recs = [x for x in sig_rows if x["horizon_min"] == h and (scope == "ALL" or x["symbol"] == scope)]
            for key in ("implied_change", "implied_gap", "odp", "ce_minus_pe_pct"):
                # flat-print threshold per symbol
                rr = [dict(x, print_move=(0.0 if abs(x["print_move"]) < eps(x["symbol"]) else x["print_move"])) for x in recs]
                hit[f"{h}m|{scope}|{key}"] = R.hit_table(rr, key, 0.0)
    for scope in ("ALL", "NIFTY", "SENSEX"):
        recs = [dict(x, print_move=(0.0 if abs(x["print_move"]) < eps(x["symbol"]) else x["print_move"]))
                for x in np_rows if scope == "ALL" or x["symbol"] == scope]
        hit[f"baseline|{scope}|pre_stale_momentum"] = R.hit_table(recs, "pre_stale_momentum", 0.0)
    by_month = {}
    for mth in sorted({x["month"] for x in sig_rows}):
        rr = [dict(x, print_move=(0.0 if abs(x["print_move"]) < eps(x["symbol"]) else x["print_move"]))
              for x in sig_rows if x["horizon_min"] == 15 and x["month"] == mth]
        by_month[mth] = {k: R.hit_table(rr, k, 0.0) for k in ("implied_gap", "ce_minus_pe_pct")}
    up_share = (100 * sum(1 for x in np_rows if x["print_move"] > 0) / len(np_rows)) if np_rows else None
    last = [x for x in sig_rows if x["horizon_min"] == 15 and x["implied_gap"] is not None]
    rho = stats.spearmanr([x["implied_gap"] for x in last], [x["print_move"] for x in last]) if len(last) > 3 else None
    magnitude = dict(n=len(last), spearman_rho=float(rho.statistic) if rho else None, spearman_p=float(rho.pvalue) if rho else None,
                     median_abs_implied_gap=R.med([abs(x["implied_gap"]) for x in last]),
                     median_abs_print_move=R.med([abs(x["print_move"]) for x in np_rows]),
                     median_abs_print_move_by_symbol={s: R.med([abs(x["print_move"]) for x in np_rows if x["symbol"] == s]) for s in cfg.symbols},
                     median_abs_close_minus_print=R.med([abs(x["close_minus_print"]) for x in np_rows if x["close_minus_print"] is not None]),
                     print_sources=dict(Counter(x["print_source"] for x in np_rows)))

    # ---------------- event study summary
    ev_counts = Counter((e["symbol"], e["event_class"]) for e in events)
    ev_prec = {}
    for cls in ("B_OPTIONS_MOVED_FIRST", "D_UNDERLYING_STALE_OPTIONS_MOVED"):
        xs = [e for e in events if e["event_class"] == cls and e["preceded_same_direction"] is not None]
        n = len(xs)
        h_ = sum(e["preceded_same_direction"] for e in xs)
        ev_prec[cls] = dict(n_with_next_reliable_move=n, same_direction=h_, rate=(100 * h_ / n) if n else None,
                            binomial_p_vs_50=stats.binomtest(h_, n, 0.5).pvalue if n else None,
                            n_without_next_reliable_move=sum(1 for e in events if e["event_class"] == cls and e["preceded_same_direction"] is None))

    # ---------------- warning study
    ws_all = R.warning_study(refs)
    ws_by = {c[0]: R.warning_study([r for r in refs if r["cohort"] == c[0]]) for c in COHORTS}
    risk_dist = Counter(p["risk"] for r in refs for p in r["path"] if p["risk"])
    action_dist = Counter(p["action"] for r in refs for p in r["path"] if p["action"])

    # ---------------- greeks / spread
    greek_tab = defaultdict(dict)
    for (key, st), n in greek.items():
        greek_tab[key][st] = n
    greek_summary = {k: dict(v, invalid_pct=100 * (v.get("INVALID", 0) + v.get("UNAVAILABLE", 0)) / sum(v.values())) for k, v in greek_tab.items()}
    tot_g = sum(greek.values())
    inv_g = sum(n for (k, st), n in greek.items() if st != "VALID")

    evaluable = [a for a in audit if a.get("snapshots_1515_1530")]
    summary = dict(
        version=VERSION, run_id=run_id, config_hash=cfg.config_hash(), generated_at=datetime.now().isoformat(),
        date_range=[str(pairs[0][1]), str(pairs[-1][1])] if pairs else None,
        symbol_days_with_option_data=len(audit), symbol_days_with_window_data=len(evaluable),
        window_minutes_expected=sum(a["expected_minutes_1515_1530"] for a in evaluable),
        window_minutes_available=sum(a["snapshots_1515_1530"] for a in evaluable),
        missing_minute_histogram=dict(Counter(m for a in evaluable for m in a["missing_minutes_1515_1530"])),
        symbol_days_without_window_data=[f"{a['symbol']} {a['date']}" for a in audit if not a.get("snapshots_1515_1530")],
        underlying_stale_symbol_days={f"{s}|{'STALE' if st else 'NOT_STALE'}": n for (s, st), n in stale_days.items()},
        underlying_minute_states={f"{s}|{st}": n for (s, st), n in minute_state.items()},
        options_activity_while_underlying_not_live={f"{s}|{st}": n for (s, st), n in active_while_stale.items()},
        next_print=dict(n_symbol_days=len(np_rows), up_print_share_pct=up_share, hit_tables=hit, by_month_15m=by_month,
                        magnitude=magnitude),
        event_study=dict(counts={f"{s}|{c}": n for (s, c), n in ev_counts.items()}, preceded=ev_prec),
        paper_positions_found=len(paper),
        reference_positions=dict(n=len(refs), cohorts=[c[0] for c in COHORTS], risk_distribution=dict(risk_dist),
                                 action_distribution=dict(action_dist),
                                 warning_study_all={k: v for k, v in ws_all.items() if k not in ("warnings", "lead_rows")},
                                 risk_distribution_by_cohort={c[0]: dict(Counter(p["risk"] for r in refs if r["cohort"] == c[0] for p in r["path"] if p["risk"])) for c in COHORTS},
                                 warning_study_by_cohort={c: {k: v for k, v in w.items() if k not in ("warnings", "lead_rows")} for c, w in ws_by.items()}),
        greeks=dict(total_leg_minutes=tot_g, invalid_or_unavailable=inv_g, invalid_pct=100 * inv_g / tot_g if tot_g else None, by_moneyness=greek_summary),
        spreads=dict(leg_minutes=spread["n"], wide_pct=100 * spread["wide"] / spread["n"] if spread["n"] else None,
                     expanded_vs_1515_pct=100 * spread["expanded"] / spread["n_ratio"] if spread["n_ratio"] else None),
        data_quality_flags=dict(dq),
    )
    leakage = dict(
        truncation_invariance=dict(minutes_checked=leak_checked, mismatches=len(leak_bad), examples=leak_bad[:10],
                                   result="PASS" if not leak_bad else "FAIL"),
        signals_strictly_before_print=dict(n=len(sig_rows), violations=sum(1 for x in sig_rows if x["print_known_at"] != "EOD" and x["signal_minute"] >= x["print_known_at"]),
                                           result="PASS" if all(x["print_known_at"] == "EOD" or x["signal_minute"] < x["print_known_at"] for x in sig_rows) else "FAIL"),
        static=static_checks(),
        thresholds="all thresholds are constants in option_risk_12b/config.py (RESEARCH DEFAULTS); none is estimated from outcomes",
        outcomes_isolated="next print / official close / forward option paths are computed only in research.py after the per-minute states",
    )
    leakage["result"] = "PASS" if (leakage["truncation_invariance"]["result"] == "PASS" and leakage["signals_strictly_before_print"]["result"] == "PASS"
                                   and all(leakage["static"].values())) else "FAIL"
    summary["leakage_result"] = leakage["result"]

    write_csv(OUT / "12b_option_trajectory.csv", traj)
    write_csv(OUT / "12b_data_audit.csv", audit)
    write_csv(OUT / "12b_next_print.csv", np_rows)
    write_csv(OUT / "12b_next_print_signals.csv", sig_rows)
    write_csv(OUT / "12b_event_study.csv", events)
    write_csv(OUT / "12b_reference_position_warnings.csv", ws_all["warnings"])
    write_csv(OUT / "12b_reference_positions.csv", [dict({k: v for k, v in r.items() if k != "path"}, path=r["path"]) for r in refs])
    (OUT / "12b_summary.json").write_text(json.dumps(_clean(summary), indent=1, default=str))
    (OUT / "12b_leakage_audit.json").write_text(json.dumps(_clean(leakage), indent=1, default=str))
    (OUT / "12b_data_quality.json").write_text(json.dumps(_clean(dict(flags=dict(dq), audit=audit, greeks=summary["greeks"],
                                                                     spreads=summary["spreads"])), indent=1, default=str))
    (OUT / "12b_config.json").write_text(json.dumps(cfg.to_json(), indent=1, default=str))
    from option_risk_12b.report import render
    HTML.write_text(render(_clean(summary), _clean(leakage), audit, np_rows, sig_rows, events, ws_all, ws_by, cfg), encoding="utf-8")
    print(json.dumps(dict(run_id=run_id, symbol_days=len(evaluable), next_print=len(np_rows), events=len(events),
                          refs=len(refs), leakage=leakage["result"]), indent=1))


if __name__ == "__main__":
    main()
