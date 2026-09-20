"""Writes all Opportunity Matrix v1 artifacts (HTML report, CSVs, JSON summary/config/leakage,
decision matrix). Cautious research language only; no BUY/SELL, no strategy claims."""

import csv
import json
from collections import Counter

ALLOWED_RECOMMENDATIONS = ("INSUFFICIENT EVIDENCE", "RESEARCH SIGNAL WORTH CONTINUING",
                           "RESEARCH SIGNAL REQUIRES MORE DATA", "NO STABLE RELATIONSHIP OBSERVED")
DATASET_FIELDS = ["symbol", "trade_date", "expiry", "expiry_flag", "event_id", "event_cluster_id", "role", "window",
                  "state_14_30", "state_14_50", "state_14_55", "state_14_59", "setup_state",
                  "event_time", "event_type", "direction", "detection_method", "detection_percentile", "onset_age_s",
                  "first_underlying_time", "first_option_time", "lead_lag_class", "lead_lag_seconds",
                  "selected_strike", "selected_option", "cf_entry_bid", "cf_entry_ask", "cf_entry_spread_pct", "option_response_class",
                  "option_acceleration", "persistence_bars",
                  "underlying_move_5s", "underlying_move_10s", "underlying_move_15s", "underlying_move_30s", "underlying_move_60s",
                  "underlying_move_120s", "underlying_move_300s", "option_move_5s", "option_move_10s", "option_move_15s",
                  "option_move_30s", "option_move_60s", "research_approved", "first_failed_stage", "primary_at_entry_label", "outcome_label",
                  "cf_mfe", "cf_mae", "cf_time_to_mfe", "cf_time_to_mae", "cf_time_to_1", "cf_giveback", "cf_net_return",
                  "cf_hit1_before_minus1", "news_state", "data_quality"]


def _csv(path, rows, fields=None):
    fields = fields or list(dict.fromkeys(k for r in rows for k in r))
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: (json.dumps(r.get(k), default=str) if isinstance(r.get(k), (list, dict)) else r.get(k)) for k in fields})


def _v(x, nd=3):
    if x is None:
        return "&ndash;"
    if isinstance(x, bool):
        return "yes" if x else "no"
    if isinstance(x, float):
        return f"{x:,.{nd}f}"
    return str(x)


def _t(h, rows):
    return "<table><tr>" + "".join(f"<th>{c}</th>" for c in h) + "</tr>" + "".join(
        "<tr>" + "".join(f"<td>{_v(c) if not isinstance(c, str) else c}</td>" for c in r) + "</tr>" for r in rows) + "</table>"


CF_H = ["group", "n", "clusters", "median net %", "mean net %", "win rate %", "+1% before &minus;1% %", "MFE %", "MAE %", "MAE p10 %",
        "t +1% s", "reach +1% %", "give-back %", "spread %", "move remaining"]


def _cfr(label, s):
    return [label] + [s.get(k) for k in ("n", "clusters", "median_net", "mean_net", "win_rate", "hit1_before_minus1", "mfe", "mae", "mae_p10",
                                          "time_to_1", "reach_1", "giveback", "spread", "move_remaining")]


def recommendation(R, summary) -> str:
    ok_status = [r["evidence_status"] for r in R["decision"]]
    if summary["evaluable_symbol_days"] < summary["targets"]["evaluable_symbol_days"] or all(s == "INSUFFICIENT" for s in ok_status):
        return "INSUFFICIENT EVIDENCE"
    if any(s == "PROMISING_RESEARCH_SIGNAL" for s in ok_status):
        return "RESEARCH SIGNAL WORTH CONTINUING"
    if all(s == "NO_RELATIONSHIP" for s in ok_status):
        return "NO STABLE RELATIONSHIP OBSERVED"
    return "RESEARCH SIGNAL REQUIRES MORE DATA"


def write_all(out, ds, R, audit, meta, days, cfg):
    ev = ds["events"]
    roles = ds["roles"]
    sym_days = [(d, s) for d in days for s in days[d]]
    evaluable = [(str(d), s) for (d, s) in sym_days if ds["_hth"].get((d, s)) is not None]
    exp_days = sorted({f"{d} {s}" for d, s in sym_days if days[d][s].is_expiry})
    summary = dict(**meta, date_range=[min(str(d) for d in days), max(str(d) for d in days)], symbols=list(cfg.symbols),
                   hr_days=len(days), symbol_days=len(sym_days), evaluable_symbol_days=len(evaluable),
                   evaluable=[f"{d} {s}" for d, s in evaluable], roles=roles,
                   targets=dict(hr_days=cfg.target_hr_days, evaluable_symbol_days=cfg.target_evaluable_symbol_days),
                   progress=dict(hr_days=f"{len(days)}/{cfg.target_hr_days}", evaluable_symbol_days=f"{len(evaluable)}/{cfg.target_evaluable_symbol_days}"),
                   events=len(ev), event_clusters=len({e["event_cluster_id"] for e in ev}),
                   track_a_events=R["track_a_events"], track_a_clusters=R["track_a_clusters"],
                   counterfactuals=sum(1 for c in ds["counterfactuals"] if c.get("status") == "OK"),
                   counterfactuals_executable=sum(1 for c in ds["counterfactuals"] if c.get("status") == "OK" and c.get("executable")),
                   research_approved_events=sum(1 for e in ev if e["research_approved"]),
                   by_symbol={s: sum(1 for e in ev if e["symbol"] == s) for s in cfg.symbols},
                   expiry_days=exp_days, expiry_events=sum(1 for e in ev if e["expiry_flag"]), normal_events=sum(1 for e in ev if not e["expiry_flag"]),
                   normal_days=sorted({f"{d} {s}" for d, s in sym_days if not days[d][s].is_expiry}),
                   leakage_tests={k: v["result"] for k, v in audit["tests"].items()}, leakage_overall=audit["overall"],
                   random_baseline=R["baseline"], research_results=dict(rejections=R["rejections"], labels_at_entry=R["labels_at_entry"],
                                                                         labels_outcome=R["labels_outcome"], chrono=R["chrono"]),
                   data_quality=data_quality(ds, days), limitations=LIMITATIONS, skipped=ds["skipped"])
    summary["recommendation"] = recommendation(R, summary)
    assert summary["recommendation"] in ALLOWED_RECOMMENDATIONS
    (out / "opportunity_matrix_v1_summary.json").write_text(json.dumps(summary, indent=1, default=str), encoding="utf-8")
    (out / "opportunity_matrix_v1_config.json").write_text(json.dumps(cfg.to_json(), indent=1, default=str), encoding="utf-8")
    (out / "opportunity_matrix_v1_leakage_audit.json").write_text(json.dumps(audit, indent=1, default=str), encoding="utf-8")
    _csv(out / "opportunity_matrix_events.csv", ev, DATASET_FIELDS + [k for k in ev[0] if k not in DATASET_FIELDS] if ev else DATASET_FIELDS)
    _csv(out / "opportunity_matrix_market_states.csv", ds["market_states"] + [dict(s, snapshot="SETUP_STATE") for s in ds["setup"]])
    _csv(out / "opportunity_matrix_option_response.csv", ds["option_response"])
    _csv(out / "opportunity_matrix_counterfactuals.csv", ds["counterfactuals"] + ds["baseline"])
    _csv(out / "opportunity_matrix_closing_state.csv", ds["closing_state"])
    _csv(out / "opportunity_matrix_strike_universe.csv", ds["strike_universe"])
    _csv(out / "opportunity_matrix_closing_persistence.csv", ds["persistence"])
    _csv(out / "opportunity_matrix_decision_matrix.csv", R["decision"])
    (out / "opportunity_matrix_v1_report.html").write_text(html(ds, R, audit, summary, cfg), encoding="utf-8")
    return summary


LIMITATIONS = [
    "Only 4 HR days exist; the first 2 only seed thresholds, leaving 2 evaluable days (4 symbol-days). No trading-rule conclusion is permitted.",
    "No UNSEEN test day exists yet: the chronological split has TRAIN (2026-09-17) and VALIDATION (2026-09-18) only.",
    "5-second data exists only from 14:55; 14:30-14:54 pre-state uses 1-minute index candles and 1-minute option-chain snapshots.",
    "SENSEX futures last-trade is stale at 5 s; all research uses the futures bid/ask MID. 12A itself is unchanged.",
    "The news feed has no entries on HR days (it ends 2026-08-19): every event is NEWS_UNKNOWN.",
    "Only 2 expiry symbol-days (NIFTY 09-15 seed, SENSEX 09-17 evaluable): expiry results are shown separately and are anecdotal.",
    "The 2026-09-18 official daily close was not yet ingested; closing-state outcomes for that day use the last 1-minute candle (flagged).",
    "Events in a cluster overlap; cluster-level figures (one row per cluster) are the honest sample size.",
    "Counterfactual trades ignore brokerage, taxes and fees; they are net of bid/ask spread only.",
]


def data_quality(ds, days):
    q = Counter(e["data_quality"] for e in ds["events"])
    cs = Counter(r["data_quality"] for r in ds["closing_state"])
    fut_missing = sum(1 for d in days for s in days[d] for m in days[d][s].fut_mid if m is None)
    return dict(event_data_quality=dict(q), closing_state_reference=dict(cs), futures_mid_missing_bars=fut_missing,
                sensex_last_trade="STALE at 5 s -- not used as a movement signal; futures MID used instead",
                news="NEWS_UNKNOWN on all HR days (feed inactive)")


def html(ds, R, audit, S, cfg):
    css = ("body{font-family:Georgia,serif;max-width:1260px;margin:0 auto;padding:30px 22px 70px;background:#fbfaf7;color:#1c1c1c;line-height:1.5}"
           "h1{border-bottom:3px solid #2c3e50;padding-bottom:8px;font-size:1.6em}h2{color:#1a3a5c;border-left:5px solid #2c3e50;padding-left:10px;"
           "font-size:1.15em;margin-top:2em}h3{font-size:1em;color:#2c3e50}table{border-collapse:collapse;width:100%;font-size:0.78em;margin:8px 0}"
           "th,td{border:1px solid #ccc;padding:3px 6px;text-align:left;vertical-align:top}th{background:#2c3e50;color:#fff}"
           "tr:nth-child(even){background:#f2f0ea}.box{background:#e8f0fe;border-left:4px solid #1a3a5c;padding:10px 14px;margin:12px 0}"
           ".warn{background:#ffebee;border-left:4px solid #c62828;padding:10px 14px;margin:12px 0}code{background:#eee;padding:1px 4px}")
    o = [f"<!DOCTYPE html><html lang='en'><head><meta charset='UTF-8'><title>Opportunity Matrix v1</title><style>{css}</style></head><body>"]
    o.append(f"<h1>Opportunity Matrix v1 &mdash; Research Report<br><span style='font-size:0.6em;font-weight:normal;color:#555'>Research only &middot; "
             f"run <code>{S['run_id']}</code> &middot; config <code>{S['config_hash']}</code> &middot; commit <code>{(S['git_commit'] or '')[:10]}</code> &middot; "
             "not a strategy &middot; no orders &middot; 11D / 12A / shadow recorder / HR capture unchanged</span></h1>")
    # 1 executive summary
    o.append("<h2>1. Executive Summary</h2>")
    o.append(f"<div class='warn'><b>Recommendation: {S['recommendation']}.</b> {S['hr_days']} HR days, {S['evaluable_symbol_days']} evaluable symbol-days "
             f"(target {S['targets']['evaluable_symbol_days']}); {S['events']} events in {S['event_clusters']} clusters ({S['track_a_events']} Track A events in "
             f"{S['track_a_clusters']} clusters); {S['counterfactuals']} counterfactual trades. Leakage audit: <b>{S['leakage_overall']}</b>. "
             "Every relationship below is descriptive, observed on two days, and none is presented as predictive.</div>")
    # 2 coverage
    o.append("<h2>2. Data Coverage</h2>")
    o.append(_t(["item", "value"], [["date range", " &rarr; ".join(S["date_range"])], ["roles (chronological)", S["roles"]],
                                    ["evaluable symbol-days", ", ".join(S["evaluable"])], ["skipped", "; ".join(f"{x['date']} {x['symbol']}: {x['reason']}" for x in S["skipped"])],
                                    ["expiry symbol-days", ", ".join(S["expiry_days"])], ["progress to target", S["progress"]],
                                    ["events by symbol", S["by_symbol"]], ["events normal / expiry", f"{S['normal_events']} / {S['expiry_events']}"]]))
    # 3 market state distribution
    ms = ds["market_states"]
    o.append("<h2>3. Market-State Distribution (descriptive, not a signal)</h2>")
    o.append(_t(["snapshot"] + ["TREND_UP", "TREND_DOWN", "BALANCED", "COMPRESSED", "EXPANSION_SETUP", "REVERSAL_SETUP", "CONFLICTED"],
                [[t] + [sum(1 for s in ms if s["snapshot"] == t and s["market_state"] == x) for x in
                        ("TREND_UP", "TREND_DOWN", "BALANCED", "COMPRESSED", "EXPANSION_SETUP", "REVERSAL_SETUP", "CONFLICTED")] for t in cfg.snapshot_times]))
    o.append(_t(["date", "symbol", "snapshot", "state", "reasons", "option state", "data quality"],
                [[s["trade_date"], s["symbol"], s["snapshot"], s["market_state"], ", ".join(s["state_reasons"]), s["option_state"], s["data_quality"]]
                 for s in ms if s["snapshot"] in ("14:30", "14:50", "14:59")]))
    # 4 setup
    o.append("<h2>4. Pre-3PM Setup States</h2>")
    o.append(_t(["date", "symbol", "role", "expiry", "setup state", "direction", "reasons"],
                [[s["trade_date"], s["symbol"], s["role"], s["expiry_flag"], s["setup_state"], s["setup_direction"], ", ".join(s["setup_reasons"])] for s in ds["setup"]]))
    o.append("<h3>Experiment A &mdash; pre-state (14:59) &rarr; Track A event type</h3>")
    for g, tab in R["A"].items():
        if tab:
            o.append(f"<p><b>{g}</b></p>" + _t(["state_14_59", "UP_IMPULSE", "DOWN_IMPULSE", "UP_REVERSAL", "DOWN_REVERSAL", "CONTINUATION"],
                                                [[k] + list(v.values()) for k, v in tab.items()]))
    o.append("<h3>Experiment B &mdash; setup state &rarr; option response</h3>")
    o.append(_t(["group", "setup state", "n", "STRONG/MODERATE %", "median 10 s response %"],
                [[g, s, v["n"], v["strong_or_moderate"], v["median_response_10s"]] for g, tab in R["B"].items() for s, v in tab.items()]))
    # 5 events
    o.append("<h2>5. Event Distribution</h2>")
    evs = ds["events"]
    o.append(_t(["window", "events", "clusters", "UP", "DOWN"] + ["UP_IMPULSE", "DOWN_IMPULSE", "UP_REVERSAL", "DOWN_REVERSAL", "CONTINUATION"],
                [[w, sum(1 for e in evs if e["window"] == w), len({e["event_cluster_id"] for e in evs if e["window"] == w}),
                  sum(1 for e in evs if e["window"] == w and e["dir"] > 0), sum(1 for e in evs if e["window"] == w and e["dir"] < 0)] +
                 [sum(1 for e in evs if e["window"] == w and e["event_type"] == t) for t in ("UP_IMPULSE", "DOWN_IMPULSE", "UP_REVERSAL", "DOWN_REVERSAL", "CONTINUATION")]
                 for w in ("SETUP", "MODE_A_EARLY", "MODE_A_MIDDLE", "MODE_A_LATE", "OPTION_ONLY")]))
    o.append(f"<p>Research-gate funnel for Track A events (first failing stage): {R['rejections']}. At-entry labels (causal): {R['labels_at_entry']}. "
             f"Outcome labels (hindsight, never inputs): {R['labels_outcome']}.</p>")
    # 6 lead/lag
    o.append("<h2>6. Lead/Lag Analysis (Experiment D) &mdash; &ldquo;option moved first&rdquo; is timing, not causality</h2>")
    for g, tab in R["D"].items():
        if tab:
            o.append(f"<h3>{g}</h3>" + _t(CF_H, [_cfr(f"{cls} (event)", v["event"]) for cls, v in tab.items()] +
                                          [_cfr(f"{cls} (cluster)", v["cluster"]) for cls, v in tab.items()]))
    # 7 option response
    o.append("<h2>7. Option Response (Experiment C)</h2>")
    o.append(_t(["group", "event type", "n", "response classes", "median option/underlying relative response (10 s)"],
                [[g, t, v["n"], v["classes"], v["median_relative_response_10s"]] for g, tab in R["C"].items() for t, v in tab.items()]))
    # 8 entry timing
    o.append("<h2>8. Entry Timing (Experiment E) &mdash; the event-bar fill is NOT executable</h2>")
    for g, tab in R["E"].items():
        if any(v["event"]["n"] for v in tab.values()):
            o.append(f"<h3>{g}</h3>" + _t(CF_H, [_cfr(f"{lbl}{'' if v['executable'] else ' (NOT executable, reference only)'}", v["event"]) for lbl, v in tab.items()]))
    # 9 opportunity quality
    o.append("<h2>9. Opportunity Quality (approved vs all Track A events, entry i+2)</h2>")
    for g, v in R["approved"].items():
        if v["all"]["n"]:
            o.append(f"<h3>{g}</h3>" + _t(CF_H, [_cfr("research-approved (event)", v["approved"]), _cfr("research-approved (cluster)", v["approved_cluster"]),
                                                 _cfr("all Track A events", v["all"])]))
    # 10 MAE/MFE
    o.append("<h2>10. MAE / MFE (Experiment G)</h2>")
    for dim, tabs in R["G"].items():
        o.append(f"<h3>by {dim}</h3>" + _t(["group", dim, "n", "MAE median %", "MAE p10 %"],
                                           [[g, k, v["n"], v["mae_median"], v["mae_p10"]] for g, tab in tabs.items() for k, v in tab.items()]))
    # 11 time to profit
    o.append("<h2>11. Time-to-Profit (Experiment F)</h2>")
    o.append(_t(["group", "entry", "level", "reach %", "median seconds"],
                [[g, lbl, lvl, v["reach"], v["median_s"]] for g, tab in R["F"].items() for lbl, lv in tab.items() for lvl, v in lv.items()]))
    # 12 decay
    o.append("<h2>12. Opportunity Decay (Experiment H) &mdash; selected option mid change, %</h2>")
    o.append(_t(["group", "n", "event &rarr; entry", "entry &rarr; 10 s", "entry &rarr; 20 s", "entry &rarr; 30 s", "entry &rarr; 60 s"],
                [[g, v["n"], v["event_to_entry"], v["entry_to_10s"], v["entry_to_20s"], v["entry_to_30s"], v["entry_to_60s"]] for g, v in R["H"].items()]))
    o.append("<h3>Experiment I &mdash; pre-state vs event direction</h3>")
    o.append(_t(CF_H, [_cfr(f"{g} | {a}", v) for g, tab in R["I"].items() for a, v in tab.items()]))
    # 13 closing state
    o.append("<h2>13. 15:15&ndash;15:30 CLOSING_STATE_RESEARCH (Track B, Experiment J)</h2>")
    o.append(_t(["group"] + ["STABLE", "MOVING_UP", "MOVING_DOWN", "DIVERGING", "CONVERGING", "UNRELIABLE"],
                [[g] + list(v.values()) for g, v in R["closing_states"].items()]))
    o.append(f"<p>Implied-spot movement persistence rates (share still holding &ge;50% of the move): {R['J_persistence_rates']}.</p>")
    o.append(_t(["group", "movement class", "n", "futures-mid move after 30 s confirmation (mean, pts, in direction)", "futures same direction %",
                 "official close vs last reliable underlying (mean, pts, in direction)", "close same direction %"],
                [[g, k, v["n"], v["fut_move_after_confirm_mean"], v["fut_same_direction"], v["close_vs_last_reliable_mean"], v["close_same_direction"]]
                 for g, tab in R["J"].items() for k, v in tab.items() if v["n"]]))
    o.append("<p>The underlying reference is labelled UNDERLYING_RELIABLE only while the index is VALID; after that it is UNDERLYING_STALE and the "
             "last reliable value is kept with its timestamp, never forward-filled as live. No auction state is inferred.</p>")
    # 14/15 symbols
    for s in cfg.symbols:
        o.append(f"<h2>{14 if s == 'NIFTY' else 15}. {s} Results</h2>")
        rows = []
        for g in (f"{s} | NORMAL", f"{s} | EXPIRY"):
            if R["approved"][g]["all"]["n"]:
                rows += [_cfr(f"{g} approved", R["approved"][g]["approved"]), _cfr(f"{g} all Track A", R["approved"][g]["all"]),
                         _cfr(f"{g} random baseline (i+2)", R["baseline"][g]["i+2"])]
        o.append(_t(CF_H, rows) if rows else "<p>No Track A events.</p>")
    # 16 expiry
    o.append("<h2>16. Expiry vs Normal (Experiment L)</h2>")
    o.append(_t(CF_H, [_cfr(g, R["approved"][g]["all"]) for g in R["approved"]]))
    o.append("<div class='warn'>Expiry results rest on one evaluable expiry symbol-day. Existing expiry restrictions are unchanged and no expiry "
             "recommendation is made.</div>")
    # 17 baseline
    o.append("<h2>17. Random Baseline (same window, symbol, day type, liquidity, option universe and mechanics)</h2>")
    o.append(_t(CF_H, [_cfr(f"{g} | {lbl}", v) for g, tab in R["baseline"].items() for lbl, v in tab.items() if v["n"]]))
    # 18 chronological
    o.append("<h2>18. Chronological Validation</h2>")
    o.append(_t(["role | symbol", "days"] + CF_H[1:] + ["baseline +1% before &minus;1% %", "baseline median net %"],
                [[k, ", ".join(v["days"])] + _cfr("", v["approved"])[1:] + [v["baseline"]["hit1_before_minus1"], v["baseline"]["median_net"]]
                 for k, v in R["chrono"].items()]))
    o.append(_t(["dimension", "sample", "TRAIN", "VALIDATION", "UNSEEN", "random baseline", "stable days", "stable symbols", "evidence"],
                [[r["research_dimension"], r["sample_size"], r["training_result"], r["validation_result"], r["unseen_result"], r["random_baseline"],
                  r["stable_across_days"], r["stable_across_symbols"], r["evidence_status"]] for r in R["decision"]]))
    # 19 leakage
    o.append("<h2>19. Leakage Audit</h2>")
    o.append(_t(["test", "result", "explanation"], [[k, v["result"], v["explanation"]] for k, v in audit["tests"].items()]))
    # 20 data quality
    o.append("<h2>20. Data Quality</h2>")
    o.append(_t(["item", "value"], [[k, v] for k, v in S["data_quality"].items()]))
    # 21 sample size
    o.append("<h2>21. Sample Size</h2>")
    o.append(_t(["measure", "now", "target"], [["HR days", S["hr_days"], S["targets"]["hr_days"]],
                                              ["evaluable symbol-days", S["evaluable_symbol_days"], S["targets"]["evaluable_symbol_days"]],
                                              ["Track A event clusters (honest n)", S["track_a_clusters"], "&ge;30 per dimension per role"],
                                              ["expiry symbol-days", len(S["expiry_days"]), "&ge;6 per symbol"]]))
    # 22 limitations
    o.append("<h2>22. Research Limitations</h2><ul>" + "".join(f"<li>{x}</li>" for x in S["limitations"]) + "</ul>")
    # 23 recommendation
    o.append("<h2>23. Recommendation</h2>")
    o.append(f"<div class='box'><b>{S['recommendation']}.</b> The framework is in place and leakage-audited ({S['leakage_overall']}); the data is not. "
             "No dimension can be evaluated on an unseen day, and every decision-matrix row is INSUFFICIENT. The Opportunity Matrix should be "
             "re-run, unchanged, as HR days accumulate. A separate opportunity engine would be justified only by the evidence listed in the "
             "summary's &ldquo;justification criteria&rdquo;: a dimension that beats the matched random baseline on TRAIN, VALIDATION and UNSEEN days, "
             "for both symbols, at cluster level, with &ge;30 clusters per role and the leakage audit passing.</div>")
    o.append("</body></html>")
    return "\n".join(o)
