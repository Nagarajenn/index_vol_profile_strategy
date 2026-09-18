"""12A chronological validation report (HTML), regenerated after each session."""

import html
from dataclasses import asdict
from datetime import datetime

from config.settings import IST
from scalp_12a.config import CONFIG_VERSION, ENGINE_VERSION, STRATEGY_VERSION

CSS = """body{font-family:Georgia,'Times New Roman',serif;max-width:1180px;margin:0 auto;padding:32px 24px 80px;color:#1c1c1c;background:#fbfaf7;line-height:1.55}
h1{font-size:1.7em;border-bottom:3px solid #2c3e50;padding-bottom:10px}h2{font-size:1.25em;color:#1a3a5c;margin-top:2em;border-left:5px solid #2c3e50;padding-left:10px}
h3{font-size:1.02em;color:#2c3e50}table{border-collapse:collapse;width:100%;margin:12px 0;font-size:0.84em}th,td{border:1px solid #ccc;padding:5px 8px;text-align:left;vertical-align:top}
th{background:#2c3e50;color:#fff}tr:nth-child(even){background:#f2f0ea}code{background:#eee;padding:1px 5px;border-radius:3px;font-family:Consolas,monospace;font-size:0.87em}
.num{text-align:right;font-family:Consolas,monospace}.tag{display:inline-block;padding:2px 8px;border-radius:10px;font-size:0.74em;font-weight:bold;color:#fff}
.MET{background:#2e7d32}.NOT_MET{background:#c62828}.INSUFFICIENT{background:#8d8d8d}.PENDING{background:#f9a825;color:#222}.DESIGN{background:#1a5c8a}
.callout{background:#fff8e1;border-left:4px solid #f9a825;padding:10px 14px;margin:14px 0}.finding{background:#e8f0fe;border-left:4px solid #1a3a5c;padding:10px 14px;margin:14px 0}
.risk{background:#ffebee;border-left:4px solid #c62828;padding:10px 14px;margin:14px 0}footer{margin-top:50px;border-top:1px solid #ccc;padding-top:12px;font-size:0.85em;color:#666}"""


def _f(v, nd=2, pct=False):
    if v is None:
        return "&ndash;"
    try:
        s = f"{float(v):+.{nd}f}" if pct else f"{float(v):.{nd}f}"
    except (TypeError, ValueError):
        return html.escape(str(v))
    return s + ("%" if pct else "")


def _tag(status):
    label = {"MET": "MET", "NOT_MET": "NOT MET", "INSUFFICIENT": "INSUFFICIENT DATA", "PENDING": "PENDING",
             "DESIGN": "MET BY DESIGN + TEST"}[status]
    return f'<span class="tag {status}">{label}</span>'


def criteria(r1, hr, shadow_days):
    hist = hr.get("history", {})
    enough = hist.get("status") == "VALIDATION_POSSIBLE"
    conf_a = hr.get("CONFIRMED|MODE_A", {})
    rand_a = hr.get("RANDOM|MODE_A", {})
    best = r1.get("grid_best_on_train") or {}
    rows = []
    rows.append(("1. Out-of-sample better than random", "NOT_MET" if not enough else "PENDING",
                 f"1-min: best train cell {_f(best.get('train_event'), pct=True)} vs random {_f(best.get('train_random'), pct=True)} "
                 f"(train); test {_f(best.get('test_event'), pct=True)} vs {_f(best.get('test_random'), pct=True)}. "
                 f"5-s: {hist.get('evaluable_days', 0)} evaluable HR day(s) of {hist.get('target_days')} needed."))
    rows.append(("2. Controlled MAE / drawdown", "INSUFFICIENT" if not enough else "PENDING",
                 f"5-s confirmed Mode A median MAE {_f(conf_a.get('mae_median'), pct=True)} vs random {_f(rand_a.get('mae_median'), pct=True)} "
                 f"(n={conf_a.get('n', 0)} / {rand_a.get('n', 0)})."))
    rows.append(("3. Favourable movement quick enough", "INSUFFICIENT" if not enough else "PENDING",
                 f"5-s confirmed median time-to-MFE {_f(conf_a.get('t_mfe_median'), 0)} s; 1-min events median {_f((r1.get('t_mfe_min') or {}).get('EVENT', {}).get('median'), 1)} min."))
    rows.append(("4. Momentum-failure exit limits give-back", "INSUFFICIENT" if not enough else "PENDING",
                 f"Median give-back (peak &minus; realised) confirmed {_f(conf_a.get('giveback_median'), pct=True)}, random {_f(rand_a.get('giveback_median'), pct=True)}; "
                 f"share of momentum-failure exits {_f(conf_a.get('momentum_failure_exit_share'))}."))
    rows.append(("5. Not driven by one symbol/day", "INSUFFICIENT" if not enough else "PENDING",
                 f"1-min leave-one-day-out max shift {_f((r1.get('lodo_test_influence') or {}).get('max_abs'), pct=True)}; 5-s by day: {conf_a.get('days', {})}."))
    rows.append(("6. Expiry-day tail risk controlled", "DESIGN",
                 "Hard veto >= 15:15 on expiry days; no entries and forced flat from 15:10 (zone widened on 1-min evidence). Tested."))
    rows.append(("7. No look-ahead leakage", "DESIGN",
                 "Thresholds from prior HR days only; decisions read bars 0..i; truncation-invariance test; 1-min fits on train days only."))
    rows.append(("8. ASK entry / BID exit", "DESIGN", "Entry = ASK of bar i+2 (live-realistic delay); every exit on the BID. Tested."))
    rows.append(("9. Acceptable after spread costs", "NOT_MET" if (best.get('test_event') or 0) <= 0 else "PENDING",
                 "All figures are already net of spread (ASK in, BID out). No configuration is positive yet."))
    rows.append(("10. Real-time detectability (shadow)", "PENDING" if shadow_days < 5 else "PENDING",
                 f"{shadow_days} live shadow session(s) recorded; detection latency tracked per candidate."))
    return rows


def build(r1, hr, day_meta, cfg, shadow_rows, latency) -> str:
    now = datetime.now(IST).strftime("%Y-%m-%d %H:%M IST")
    h = cfg.config_hash()
    shadow_days = len([r for r in shadow_rows if r[1] == "COMPLETED"])
    out = [f"<!DOCTYPE html><html lang='en'><head><meta charset='UTF-8'><title>12A Research Report</title><style>{CSS}</style></head><body>"]
    out.append(f"<h1>12A-scalp-v1 &mdash; Research &amp; Chronological Validation Report<br><span style='font-size:0.6em;font-weight:normal;color:#555'>"
               f"Experiment beside the frozen <code>11d-paper-v1</code> control &middot; updated {now}</span></h1>")
    out.append(f"<p><b>Strategy:</b> <code>{STRATEGY_VERSION}</code> &middot; <b>engine</b> <code>{ENGINE_VERSION}</code> &middot; "
               f"<b>config</b> <code>{CONFIG_VERSION}</code> &middot; <b>hash</b> <code>{h}</code> &middot; <b>paper trading:</b> NOT CONNECTED "
               f"&middot; <b>orders:</b> none (no order code exists in 12A)</p>")
    hist = hr.get("history", {})
    out.append("<div class='risk'><b>Status: RESEARCH / SHADOW ONLY.</b> The paper-trading gate (10 criteria) is not passed. "
               f"5-second history: <b>{hist.get('evaluable_days', 0)}</b> evaluable HR day(s) of the ~{hist.get('target_days')} needed "
               f"for a chronological validation split ({hist.get('hr_days', 0)} HR days captured; the first two only seed thresholds). "
               "The 1-minute research found <b>no positive configuration</b>: at 1-minute latency, entering after a large move is worse than random.</div>")

    out.append("<h2>1. Paper-trading gate &mdash; the 10 criteria</h2><table><tr><th>Criterion</th><th>Status</th><th>Evidence</th></tr>")
    for name, status, ev in criteria(r1, hr, shadow_days):
        out.append(f"<tr><td>{name}</td><td>{_tag(status)}</td><td>{ev}</td></tr>")
    out.append("</table>")

    # ---- 1-minute research
    out.append(f"<h2>2. 1-minute research ({len(r1.get('days', []))} complete days, chronological split)</h2>")
    out.append(f"<p>Complete CAS-era days: <b>{len(r1.get('days', []))}</b>. TRAIN {r1['train_days'][0]} &rarr; {r1['train_days'][-1]} "
               f"({len(r1['train_days'])} days); TEST {r1['test_days'][0]} &rarr; {r1['test_days'][-1]} ({len(r1['test_days'])} days). "
               f"Trigger: ATM synthetic (CE&minus;PE mid) 1-minute move above the TRAIN p{r1.get('trigger_percentile'):.0f} "
               f"(NIFTY {_f(r1['trigger_threshold'].get('NIFTY'), 3)}, SENSEX {_f(r1['trigger_threshold'].get('SENSEX'), 3)} of straddle). "
               f"Entry = ASK of the next snapshot, exits on BID; 3-snapshot cooldown; day-grouped statistics. "
               f"ATM events {r1['n_trades']['EVENT']}, random {r1['n_trades']['RANDOM']}.</p>")
    out.append("<div class='callout'><b>Scope:</b> these are candidate RANGES at 1-minute resolution. They do not validate any "
               "5-second threshold, 15&ndash;60 s behaviour or the momentum-failure exit.</div>")
    out.append("<h3>Holding duration: day-mean exit on BID after k minutes (median across day groups)</h3><table><tr><th>Split | group | mode</th>"
               + "".join(f"<th>{k} min exit</th><th>{k} min MAE</th>" for k in ("1", "2", "3", "5")) + "</tr>")
    for key, v in r1["holding"].items():
        cells = "".join(f"<td class='num'>{_f((v[k]['exit'] or {}).get('median'), pct=True)}</td>"
                        f"<td class='num'>{_f((v[k]['mae'] or {}).get('median'), pct=True)}</td>" for k in ("1", "2", "3", "5"))
        out.append(f"<tr><td>{key}</td>{cells}</tr>")
    out.append("</table>")
    best = r1.get("grid_best_on_train") or {}
    out.append("<h3>Target / stop / max-hold grid (fitted on TRAIN, read on TEST; ATM, PRE + Mode A)</h3>")
    out.append(f"<div class='finding'>Best TRAIN cell: target {best.get('target')}%, stop {best.get('stop')}%, hold {best.get('max_hold')} min &rarr; "
               f"TRAIN event {_f(best.get('train_event'), pct=True)} vs random {_f(best.get('train_random'), pct=True)}; "
               f"TEST event {_f(best.get('test_event'), pct=True)} (95% CI {best.get('test_event_ci')}) vs random {_f(best.get('test_random'), pct=True)} "
               f"(CI {best.get('test_random_ci')}), {best.get('test_event_days')} test day-groups. "
               "<b>No cell is positive on TRAIN.</b> The 12A stop/target/hold values are therefore risk ranges, not a tuned edge.</div>")
    out.append("<h3>Option selection by moneyness (events; + = OTM, &minus; = ITM)</h3><table><tr><th>Split</th><th>Moneyness</th><th>3-min exit</th><th>3-min MFE</th><th>3-min MAE</th><th>Spread</th><th>Premium</th><th>|Delta|</th></tr>")
    for split in ("train", "test"):
        for m, v in r1["moneyness"][split].items():
            g = lambda k: (v.get(k) or {}).get("median")
            out.append(f"<tr><td>{split}</td><td>{m}</td><td class='num'>{_f(g('exit3'), pct=True)}</td><td class='num'>{_f(g('mfe3'), pct=True)}</td>"
                       f"<td class='num'>{_f(g('mae3'), pct=True)}</td><td class='num'>{_f(g('spread'))}%</td><td class='num'>{_f(g('premium'), 1)}</td><td class='num'>{_f(g('delta'))}</td></tr>")
    out.append("</table>")
    out.append("<h3>Premium response in the trigger minute vs the next 2 minutes (tercile cut-offs from TRAIN)</h3><table><tr><th>Split</th><th>Response tercile</th><th>n</th><th>2-min exit</th><th>2-min MAE</th></tr>")
    for split, groups in r1["response"]["by_split"].items():
        for g, v in groups.items():
            out.append(f"<tr><td>{split}</td><td>{g}</td><td class='num'>{v['n']}</td><td class='num'>{_f((v['exit2'] or {}).get('median'), pct=True)}</td>"
                       f"<td class='num'>{_f((v['mae2'] or {}).get('median'), pct=True)}</td></tr>")
    out.append("</table><p>At 1-minute latency a strong premium response does <b>not</b> predict continuation (the premium is already inflated when the snapshot shows it).</p>")
    out.append("<h3>Spread cost (entry spread %, ATM &plusmn; 2)</h3><table><tr><th>Mode</th><th>median</th><th>p90</th><th>mean</th></tr>")
    for mode, v in r1["spread"].items():
        out.append(f"<tr><td>{mode}</td><td class='num'>{_f(v['median'])}</td><td class='num'>{_f(v['p90'])}</td><td class='num'>{_f(v['mean'])}</td></tr>")
    out.append("</table>")
    out.append("<h3>Expiry-day behaviour (ATM, 3-minute MAE on BID)</h3><table><tr><th>Day type | window</th><th>symbol-days</th><th>MAE median</th><th>MAE p10</th><th>3-min exit</th></tr>")
    for key, v in r1["expiry"].items():
        out.append(f"<tr><td>{key}</td><td class='num'>{v['days']}</td><td class='num'>{_f((v['mae3'] or {}).get('median'), pct=True)}</td>"
                   f"<td class='num'>{_f((v['mae3'] or {}).get('p10'), pct=True)}</td><td class='num'>{_f((v['exit3'] or {}).get('median'), pct=True)}</td></tr>")
    out.append("</table><div class='risk'>Expiry days are riskier throughout, and the tail widens from <b>15:10</b>, not 15:14. "
               "12A-v1 therefore keeps the hard veto at 15:15 and starts the no-entry / forced-flat zone at 15:10.</div>")

    # ---- HR research
    out.append("<h2>3. 5-second HR research vs random (descriptive)</h2>")
    out.append("<table><tr><th>Day</th><th>Prior HR days</th><th>Thresholds available</th><th>Candidates</th><th>Would-trade (hypothetical)</th></tr>")
    for m in day_meta:
        out.append(f"<tr><td>{m['day']}</td><td class='num'>{m['prior_days']}</td><td>{m['sufficient']}</td>"
                   f"<td class='num'>{m['candidates']}</td><td class='num'>{m['would_trade']}</td></tr>")
    out.append("</table><table><tr><th>Group | mode</th><th>n</th><th>day groups</th><th>active-exit day-mean</th><th>active-exit median</th>"
               "<th>MFE med</th><th>MAE med</th><th>t-MFE med (s)</th><th>give-back med</th><th>momentum-failure exits</th><th>60 s fixed</th><th>120 s fixed</th></tr>")
    for key in ("CONFIRMED|MODE_A", "ALL_STRONG|MODE_A", "RANDOM|MODE_A", "CONFIRMED|MODE_B", "ALL_STRONG|MODE_B", "RANDOM|MODE_B"):
        v = hr.get(key, {})
        fx = v.get("fixed_exit_median", {})
        out.append(f"<tr><td>{key}</td><td class='num'>{v.get('n', 0)}</td><td class='num'>{v.get('day_groups', 0)}</td>"
                   f"<td class='num'>{_f(v.get('active_exit_day_mean'), pct=True)}</td><td class='num'>{_f(v.get('active_exit_median'), pct=True)}</td>"
                   f"<td class='num'>{_f(v.get('mfe_median'), pct=True)}</td><td class='num'>{_f(v.get('mae_median'), pct=True)}</td>"
                   f"<td class='num'>{_f(v.get('t_mfe_median'), 0)}</td><td class='num'>{_f(v.get('giveback_median'), pct=True)}</td>"
                   f"<td class='num'>{_f(v.get('momentum_failure_exit_share'))}</td><td class='num'>{_f(fx.get(60) or fx.get('60'), pct=True)}</td>"
                   f"<td class='num'>{_f(fx.get(120) or fx.get('120'), pct=True)}</td></tr>")
    out.append("</table><p>Mode B rows ignore the Mode B / expiry vetoes on purpose so research keeps accumulating; they are never tradeable in v1.</p>")

    # ---- opportunity remaining at detection
    ot = hr.get("opportunity_timing", {})
    out.append("<h2>4. Opportunity remaining at detection</h2>")
    out.append("<p>For every candidate: event start (futures origin), detection (end of the event bar; live rows also record the "
               "wall-clock detection time and latency), detection price, realistic entry (ASK two bars later), and what was still "
               "available afterwards. <b>DETECTED_EARLY</b> = at the realistic entry &ge;50% of the event's total favourable futures "
               "move was still ahead; <b>DETECTED_LATE</b> = most of it had already happened; <b>NO_FOLLOW_THROUGH</b> = nothing "
               "favourable was left after the entry. These are descriptive research labels, not trading rules.</p>")
    out.append("<table><tr><th>Group</th><th>n</th><th>EARLY</th><th>LATE</th><th>NO FOLLOW-THROUGH</th><th>UNKNOWN</th>"
               "<th>remaining at detection (median share)</th><th>remaining at entry (median share)</th>"
               "<th>realised before detection (pts)</th><th>MFE after detection (pts)</th><th>MAE after detection (pts)</th></tr>")
    for kind in ("CONFIRMED", "REJECTED", "ALL_STRONG"):
        v = ot.get(kind, {})
        c = v.get("counts", {})
        out.append(f"<tr><td>{kind}</td><td class='num'>{v.get('n', 0)}</td><td class='num'>{c.get('DETECTED_EARLY', 0)}</td>"
                   f"<td class='num'>{c.get('DETECTED_LATE', 0)}</td><td class='num'>{c.get('NO_FOLLOW_THROUGH', 0)}</td>"
                   f"<td class='num'>{c.get('UNKNOWN', 0) + c.get('None', 0)}</td><td class='num'>{_f(v.get('frac_det_median'))}</td>"
                   f"<td class='num'>{_f(v.get('frac_entry_median'))}</td><td class='num'>{_f(v.get('realized_det_median'), 1)}</td>"
                   f"<td class='num'>{_f(v.get('fut_mfe_after_det_median'), 1)}</td><td class='num'>{_f(v.get('fut_mae_after_det_median'), 1)}</td></tr>")
    out.append("</table>")
    mo, fp = hr.get("missed_opportunities", {}), hr.get("false_positives", {})
    out.append(f"<p><b>Missed opportunities</b> (rejected by a non-veto gate, yet detected early and positive after the active exit): "
               f"{mo.get('n', 0)} of {mo.get('of_rejected', 0)} rejected; by reason {mo.get('by_reason', {})}. "
               f"<b>False positives</b> (confirmed, but the active exit lost): {fp.get('n', 0)} of {fp.get('of_confirmed', 0)}; "
               f"of the confirmed, {fp.get('late_or_no_follow', 0)} were detected late or had no follow-through.</p>")

    # ---- shadow
    out.append("<h2>5. Live shadow recorder</h2>")
    if shadow_rows:
        out.append("<table><tr><th>Date</th><th>Status</th><th>Candidates</th><th>Would-trade (hypothetical)</th></tr>")
        for d, status, n, t in shadow_rows:
            out.append(f"<tr><td>{d}</td><td>{status}</td><td class='num'>{n}</td><td class='num'>{t}</td></tr>")
        out.append("</table>")
        if latency and latency[0]:
            out.append(f"<p>Detection latency (wall clock minus event-bar end): median {_f(latency[1], 1)} s, max {_f(latency[2], 1)} s "
                       f"over {latency[0]} candidates. Entry is modelled at the close of bar i+2 (&asymp;10 s after bar i ends).</p>")
    else:
        out.append("<p>No live shadow sessions yet. The recorder runs daily 14:55&ndash;15:36 (task <code>SensexNifty-Scalp12AShadow</code>).</p>")

    # ---- config
    out.append("<h2>6. Configuration (<code>" + h + "</code>)</h2><table><tr><th>Parameter</th><th>Value</th></tr>")
    for k, v in asdict(cfg).items():
        out.append(f"<tr><td><code>{k}</code></td><td>{html.escape(str(v))}</td></tr>")
    out.append("</table><p>Evidence labels for each parameter (RESEARCH_1MIN / PROVISIONAL_5S / POLICY / EVIDENCE_VETO) are documented in "
               "<code>scalp_12a/config.py</code>.</p>")
    out.append(f"<footer>12A-scalp-v1 research report &middot; hash {h} &middot; regenerated by scripts/run_scalp12a_research.py &middot; "
               "11d-paper-v1 unchanged (pinned by tests/test_scalp12a_isolation.py)</footer></body></html>")
    return "\n".join(out)
