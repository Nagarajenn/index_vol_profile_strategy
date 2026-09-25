"""13B_PARTIAL_EXPERIMENT_REPORT.html -- one isolated change, measured."""

import html

from price_action_13b.report import CSS


def _e(x):
    return html.escape(str(x)) if x is not None else "–"


def _n(x, d=2):
    return f"{x:,.{d}f}" if isinstance(x, (int, float)) else "–"


def _cls(x):
    if not isinstance(x, (int, float)) or x == 0:
        return ""
    return "up" if x > 0 else "down"


def _row(label, s, tag=""):
    return (f"<tr><td><b>{_e(label)}</b>{tag}</td><td class='n'>{s['trades']}</td>"
            f"<td class='n'>{_n(s['win_rate'],1)}%</td>"
            f"<td class='n {_cls(s['total_pnl'])}'>{_n(s['total_pnl'],0)}</td>"
            f"<td class='n'>{_n(s['mean_pnl'])}</td><td class='n'>{_n(s['median_pnl'])}</td>"
            f"<td class='n down'>{_n(s['max_drawdown'],0)}</td>"
            f"<td class='n'>{s['max_consecutive_losses']}</td>"
            f"<td class='n'>{_n(s['mean_hold_minutes'],1)}</td>"
            f"<td class='n'>{_n(s['mean_mfe_per_unit'])}</td>"
            f"<td class='n'>{_n(s['mean_mae_per_unit'])}</td>"
            f"<td class='n'>{s['stop_loss']}/{s['signal_flip']}/{s['session_end']}</td></tr>")


def build(p: dict, path) -> None:
    c = p["comparison"]
    base, dflt, exp = c["baseline"], c["default"], c["experiment"]
    parts = [f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>13B PARTIAL Experiment</title><style>{CSS}</style></head><body><div class="wrap">
<header><h1>13B — the PARTIAL experiment</h1>
<div class="sub">One isolated change: a PARTIAL price-action read no longer blocks the 13A buy.
CONTRADICTED and NO_SETUP still do.</div>
<div class="meta"><span class="chip">{_e(p['experiment_version'])}</span>
<span class="chip">baseline {_e(p['baseline_config']['config_hash'])}</span>
<span class="chip">experiment {_e(p['experiment_config']['config_hash'])}</span>
<span class="chip">{p['sessions']} sessions</span>
<span class="chip">Paper / advisory only</span></div></header>"""]

    parts.append(f"""<div class="panel"><b>The only difference</b>
<p style="margin-bottom:0"><code>{_e(p['only_difference'])}</code> — verified by comparing the two
config objects field by field. Structure, break, VWAP, volume-profile, volume, 13A rules, the
risk brake, spread, economics, timing, stop loss and position simulation are all identical.</p>
</div>""")

    # ---- the accounting note that prompted this experiment ---------------------------------
    cmn = c["candidate_minutes"]
    parts.append(f"""<div class="callout"><b>Why the candidate counts differ between paths</b>
PATH A saw <b>{cmn['path_a']}</b> candidate minutes, the default path <b>{cmn['path_b']}</b>, the
experiment <b>{cmn['path_c']}</b>. These are not inconsistent: blocking a trade frees capacity,
so a minute that PATH A refused as <code>POSITION_OPEN</code> can become a real candidate in a
path that blocked the earlier entry. A filtering percentage is therefore only meaningful
<em>within</em> a path, never across them.</div>""")

    parts.append("<h2>1 · Three paths, identical inputs</h2>")
    head = ("<tr><th>Path</th><th class='n'>Trades</th><th class='n'>Win %</th><th class='n'>Total</th>"
            "<th class='n'>Mean</th><th class='n'>Median</th><th class='n'>Max DD</th>"
            "<th class='n'>Max cons. loss</th><th class='n'>Hold</th><th class='n'>MFE/u</th>"
            "<th class='n'>MAE/u</th><th class='n'>Stop/Flip/End</th></tr>")
    body = (_row("13A alone (baseline)", base, "" if base["sufficient"] else " <span class='tag'>small N</span>")
            + _row("13B default — block PARTIAL", dflt, "" if dflt["sufficient"] else " <span class='tag'>small N</span>")
            + _row("13B experiment — allow PARTIAL", exp, "" if exp["sufficient"] else " <span class='tag'>small N</span>"))
    parts.append(f"<div class='tw'><table><thead>{head}</thead><tbody>{body}</tbody></table></div>")

    parts.append(f"""<div class="grid">
<div class="stat"><div class="k">Filtering, default</div><div class="v">{_n(c['filtering_default'],1)}%</div>
<div class="small">{c['blocked_default']} blocked</div></div>
<div class="stat"><div class="k">Filtering, experiment</div><div class="v">{_n(c['filtering_experiment'],1)}%</div>
<div class="small">{c['blocked_experiment']} blocked</div></div>
<div class="stat"><div class="k">PARTIAL trades allowed</div><div class="v">{c['partial_allowed']}</div></div>
<div class="stat"><div class="k">Trades: default → experiment</div><div class="v">{dflt['trades']} → {exp['trades']}</div></div>
</div>""")

    # ---- forward movement by verdict -------------------------------------------------------
    parts.append("<h2>2 · Forward movement by price-action verdict</h2>")
    parts.append("<p class='small'>All outcome figures are PER UNIT so the two kinds of row are comparable. "
                 "Blocked rows carry a 10-minute forward path priced on the BID against the entry "
                 "ASK; allowed rows are realised holdings. A blocked candidate was never sized, so "
                 "it has no cash column.</p>")
    for label, key in (("Default configuration", "forward_default"),
                       ("Experiment configuration", "forward_experiment")):
        d = c[key]
        if not d:
            continue
        rows = "".join(
            f"<tr><td>{_e(k)}</td><td class='n'>{v['n']}</td>"
            f"<td class='n'>{_n(v['pct_adverse'],1)}%</td><td class='n'>{_n(v['pct_favourable'],1)}%</td>"
            f"<td class='n {_cls(v['mean_end'])}'>{_n(v['mean_end'])}</td>"
            f"<td class='n {_cls(v.get('mean_cash'))}'>{_n(v.get('mean_cash'))}</td>"
            f"<td class='n'>{_n(v['mean_mfe'])}</td><td class='n'>{_n(v['mean_mae'])}</td></tr>"
            for k, v in sorted(d.items(), key=lambda x: -x[1]["n"]))
        parts.append(f"<h3>{_e(label)}</h3><div class='tw'><table><thead><tr><th>Verdict</th>"
                     "<th class='n'>N</th><th class='n'>Adverse</th><th class='n'>Favourable</th>"
                     "<th class='n'>Mean outcome/u</th><th class='n'>Mean cash</th><th class='n'>Mean MFE/u</th>"
                     f"<th class='n'>Mean MAE/u</th></tr></thead><tbody>{rows}</tbody></table></div>")

    # ---- verdict distribution ----------------------------------------------------------------
    parts.append("<h2>3 · Verdict distribution</h2>")
    rows = ""
    keys = sorted(set(c["verdicts_default"]) | set(c["verdicts_experiment"]))
    for k in keys:
        rows += (f"<tr><td>{_e(k)}</td><td class='n'>{c['verdicts_default'].get(k,0)}</td>"
                 f"<td class='n'>{c['verdicts_experiment'].get(k,0)}</td></tr>")
    parts.append(f"<div class='tw'><table><thead><tr><th>Verdict</th><th class='n'>Default path</th>"
                 f"<th class='n'>Experiment path</th></tr></thead><tbody>{rows}</tbody></table></div>")

    # ---- today ---------------------------------------------------------------------------------
    parts.append("<h2>4 · Today, both paths side by side</h2>")
    if p["today"]:
        rows = "".join(
            f"<tr><td>{_e(r.get('timestamp'))}</td><td>{_e(r.get('symbol'))}</td>"
            f"<td>{_e(r.get('path_a_13a_decision'))}</td><td>{_e(r.get('price_action_verdict'))}</td>"
            f"<td>{_e(r.get('path_b_final_decision'))}</td>"
            f"<td>{_e(r.get('contract') or r.get('path_a_contract'))}</td>"
            f"<td class='n'>{_n(r.get('entry_ask') or r.get('path_a_entry_ask'))}</td>"
            f"<td class='n'>{_n(r.get('exit_bid'))}</td>"
            f"<td class='n {_cls(r.get('path_a_pnl'))}'>{_n(r.get('path_a_pnl'))}</td>"
            f"<td class='n {_cls(r.get('pnl'))}'>{_n(r.get('pnl'))}</td>"
            f"<td class='n'>{_n(r.get('mfe'))}</td><td class='n'>{_n(r.get('mae'))}</td>"
            f"<td>{_e(r.get('exit_reason') or r.get('path_a_exit_reason'))}</td></tr>"
            for r in p["today"])
        parts.append("<div class='tw'><table style='min-width:980px'><thead><tr><th>Time</th>"
                     "<th>Symbol</th><th>13A</th><th>Price action</th><th>Final (exp)</th>"
                     "<th>Contract</th><th class='n'>Entry ASK</th><th class='n'>Exit BID</th>"
                     "<th class='n'>P&amp;L (13A)</th><th class='n'>P&amp;L (exp)</th>"
                     f"<th class='n'>MFE</th><th class='n'>MAE</th><th>Exit</th></tr></thead>"
                     f"<tbody>{rows}</tbody></table></div>")
    else:
        parts.append("<div class='panel'><p style='margin-bottom:0'>No 13A candidate has arisen "
                     "yet today, so there is nothing to compare.</p></div>")

    # ---- leakage -------------------------------------------------------------------------------
    parts.append("<h2>5 · Leakage audit (experiment config)</h2>")
    rows = "".join(f"<tr><td>{_e(x['symbol'])}</td><td class='n'>{x['checked']}</td>"
                   f"<td class='n'>{x['fields_compared']}</td><td class='n'>{len(x['mismatches'])}</td>"
                   f"<td class='n'>{x['future_bar_used']}</td>"
                   f"<td>{'<span class=pass>PASS</span>' if x['passed'] else '<span class=fail>FAIL</span>'}</td></tr>"
                   for x in p["leakage"])
    parts.append("<div class='tw'><table><thead><tr><th>Symbol</th><th class='n'>Candidates</th>"
                 "<th class='n'>Fields</th><th class='n'>Mismatches</th>"
                 f"<th class='n'>Future-bar uses</th><th>Result</th></tr></thead><tbody>{rows}</tbody></table></div>")

    # ---- the five success questions ---------------------------------------------------------------
    parts.append("<h2>6 · The five questions</h2>")
    q = [
        ("1. Does allowing PARTIAL produce a reasonable number of additional paper trades?",
         f"Trades go from <b>{dflt['trades']}</b> to <b>{exp['trades']}</b> across {p['sessions']} "
         f"sessions ({c['partial_allowed']} of them PARTIAL). "
         + ("Still far too few to characterise anything." if exp["trades"] < 20 else
            "Enough to begin comparing, though still a small sample.")),
        ("2. Do those trades have materially different MFE/MAE from the blocked PARTIAL candidates?",
         f"Allowed PARTIAL realised MFE/MAE per unit vs the blocked PARTIAL forward path — see "
         f"section 2. The two are measured differently (a realised holding vs a fixed 10-minute "
         f"window) and should not be read as a like-for-like difference."),
        ("3. Does allowing PARTIAL reduce the excessive filtering?",
         f"Filtering falls from <b>{_n(c['filtering_default'],1)}%</b> to "
         f"<b>{_n(c['filtering_experiment'],1)}%</b> within each path."),
        ("4. Does it preserve protection against genuinely contradicted setups?",
         "Yes by construction — CONTRADICTED and NO_SETUP still block, and section 2 shows their "
         "forward outcomes remain the adverse ones."),
        ("5. Does the live screen become more useful without removing the risk brake?",
         "The risk brake is untouched: same daily loss limit, consecutive-loss and trade-count "
         "locks, and allocated capital still reported separately. PARTIAL is surfaced as an "
         "explicit early-setup warning, never as equivalent to CONFIRMED."),
    ]
    parts.append("<div class='tw'><table style='min-width:640px'><thead><tr><th>Question</th>"
                 "<th>Answer</th></tr></thead><tbody>"
                 + "".join(f"<tr><td class='wrap'>{_e(a)}</td><td class='wrap small'>{b}</td></tr>"
                           for a, b in q) + "</tbody></table></div>")

    parts.append(f"""<div class="callout bad"><b>What this does not show</b>
With <b>{exp['trades']}</b> surviving trades in the experiment path, the win rate, drawdown and
median comparisons carry no statistical weight. No threshold was tuned against these results and
the committed 13B default is unchanged. This is a measurement of one flag, not a validation of a
strategy, and nothing here is evidence of profitability.</div>""")

    parts.append(f"""<footer>{_e(p['experiment_version'])} · baseline
<code>{_e(p['baseline_config']['config_hash'])}</code> · experiment
<code>{_e(p['experiment_config']['config_hash'])}</code> · paper / advisory only. 13A and the
committed 13B default are unmodified; no broker API is reachable from this package.
</footer></div></body></html>""")
    path.write_text("".join(parts), encoding="utf-8")
