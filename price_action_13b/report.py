"""13B_PRICE_ACTION_REPORT.html -- the nine sections spec 12 requires."""

import html


def _e(x):
    return html.escape(str(x)) if x is not None else "–"


def _n(x, d=2):
    return f"{x:,.{d}f}" if isinstance(x, (int, float)) else "–"


def _cls(x):
    if not isinstance(x, (int, float)) or x == 0:
        return ""
    return "up" if x > 0 else "down"


def _yn(v):
    if v is True:
        return '<span class="pass">YES</span>'
    if v is False:
        return '<span class="fail">NO</span>'
    return '<span class="small">not separable</span>'


CSS = """
:root{--bg:#f7f7f5;--panel:#fff;--ink:#1b1b19;--muted:#6b6b66;--line:#e2e2dd;--up:#2e7d32;
--down:#c62828;--warn:#b26a00;--chip:#f0f0ec}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#14140f;--panel:#1c1c18;
--ink:#ecece6;--muted:#9a9a92;--line:#2e2e28;--up:#7bc47f;--down:#ef8d86;--warn:#e0a34a;--chip:#26262040}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.6 ui-sans-serif,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
.wrap{max-width:1140px;margin:0 auto;padding:40px 16px 80px}
header{border-bottom:2px solid var(--ink);padding-bottom:18px;margin-bottom:30px}
h1{font-size:27px;margin:0 0 6px;letter-spacing:-.02em}
h2{font-size:13px;letter-spacing:.09em;text-transform:uppercase;color:var(--muted);margin:42px 0 12px;
padding-bottom:7px;border-bottom:1px solid var(--line)}
h3{font-size:15px;margin:22px 0 8px}
.sub{color:var(--muted);font-size:14px}
.meta{display:flex;flex-wrap:wrap;gap:8px;margin-top:14px}
.chip{background:var(--chip);border:1px solid var(--line);border-radius:999px;padding:3px 11px;
font-size:12px;color:var(--muted);white-space:nowrap}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:16px 18px;margin:14px 0}
.callout{border-left:4px solid var(--warn);background:var(--panel);border-radius:0 8px 8px 0;padding:13px 17px;margin:16px 0}
.callout.bad{border-left-color:var(--down)}.callout.good{border-left-color:var(--up)}
.callout b{display:block;margin-bottom:4px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(155px,1fr));gap:13px;margin:16px 0}
.stat{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:13px}
.stat .k{font-size:11px;letter-spacing:.07em;text-transform:uppercase;color:var(--muted)}
.stat .v{font-size:21px;font-weight:650;margin-top:3px;letter-spacing:-.02em}
.tw{overflow-x:auto;-webkit-overflow-scrolling:touch;margin:12px 0}
table{border-collapse:collapse;width:100%;font-size:13.5px;min-width:480px}
th,td{text-align:left;padding:7px 10px;border-bottom:1px solid var(--line);white-space:nowrap}
th{font-size:11px;letter-spacing:.05em;text-transform:uppercase;color:var(--muted);font-weight:600}
td.n,th.n{text-align:right;font-variant-numeric:tabular-nums}
td.wrap{white-space:normal;min-width:320px}
.up{color:var(--up)}.down{color:var(--down)}.small{font-size:12.5px;color:var(--muted)}
.pass{color:var(--up);font-weight:700}.fail{color:var(--down);font-weight:700}
.tag{display:inline-block;font-size:10.5px;padding:1px 6px;border-radius:4px;background:var(--chip);
border:1px solid var(--line);color:var(--muted)}
code{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:.9em;background:var(--chip);padding:1px 5px;border-radius:4px}
ul{margin:0 0 14px;padding-left:20px}li{margin-bottom:6px}
footer{margin-top:54px;padding-top:18px;border-top:1px solid var(--line);color:var(--muted);font-size:13px}
@media (max-width:640px){h1{font-size:22px}.wrap{padding:26px 16px 60px}}
"""


def _counts(d: dict, title: str) -> str:
    if not d:
        return ""
    rows = "".join(f"<tr><td>{_e(k).replace('_',' ')}</td><td class='n'>{v}</td></tr>"
                   for k, v in sorted(d.items(), key=lambda x: -x[1]))
    return (f"<h3>{_e(title)}</h3><div class='tw'><table><thead><tr><th>State</th>"
            f"<th class='n'>Count</th></tr></thead><tbody>{rows}</tbody></table></div>")


def _summary_row(s: dict) -> str:
    return (f"<td class='n'>{s['trades']}</td><td class='n'>{_n(s['win_rate'],1)}%</td>"
            f"<td class='n {_cls(s['total_pnl'])}'>{_n(s['total_pnl'],0)}</td>"
            f"<td class='n'>{_n(s['mean_pnl'])}</td><td class='n'>{_n(s['median_pnl'])}</td>"
            f"<td class='n down'>{_n(s['max_drawdown'],0)}</td>"
            f"<td class='n'>{s['max_consecutive_losses']}</td>"
            f"<td class='n'>{_n(s['mean_hold_minutes'],1)}</td>"
            f"<td class='n'>{_n(s['mean_mfe_per_unit'])}</td>"
            f"<td class='n'>{_n(s['mean_mae_per_unit'])}</td>"
            f"<td class='n'>{s['stop_loss']}/{s['signal_flip']}/{s['session_end']}</td>")


def build(p: dict, path) -> None:
    cmp, v, bl = p["comparison"], p["verdict"], p["comparison"]["blocked"]
    a, b = cmp["thirteen_a"], cmp["thirteen_b"]
    cfg = p["config"]
    parts = [f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>13B Price Action</title>
<style>{CSS}</style></head><body><div class="wrap">
<header><h1>13B — Price-Action Confirmation</h1>
<div class="sub">Does the underlying actually show a clean scalp setup when 13A produces a candidate?</div>
<div class="meta"><span class="chip">{_e(cfg['version'])}</span>
<span class="chip">config {_e(cfg['config_hash'])}</span>
<span class="chip">{p['sessions']} sessions</span>
<span class="chip">Paper / advisory only</span>
<span class="chip">Not tuned to P&amp;L</span></div></header>"""]

    parts.append(f"""<div class="callout bad"><b>Read the P&amp;L line last</b>
13B can only ever REMOVE trades, so total P&amp;L will move simply because fewer trades happen.
That is not evidence the layer works. The questions that matter are in section 3: did it remove
the <em>worse</em> candidates, or just some candidates? With {b['trades']} surviving trades, most
of those answers are not yet decidable.</div>""")

    # ---- 1 / 2 -------------------------------------------------------------------------------
    parts.append("<h2>1 · 13A baseline &nbsp;·&nbsp; 2 · 13B results</h2>")
    parts.append(f"""<div class="grid">
<div class="stat"><div class="k">13A candidates</div><div class="v">{cmp['candidates']}</div></div>
<div class="stat"><div class="k">Survive price action</div><div class="v">{cmp['buys_after_price_action']}</div>
<div class="small">{_n(cmp['pct_rejected_by_price_action'],1)}% removed</div></div>
<div class="stat"><div class="k">13A trades</div><div class="v">{a['trades']}</div></div>
<div class="stat"><div class="k">13B trades</div><div class="v">{b['trades']}</div></div>
<div class="stat"><div class="k">13A total</div><div class="v {_cls(a['total_pnl'])}">₹{_n(a['total_pnl'],0)}</div></div>
<div class="stat"><div class="k">13B total</div><div class="v {_cls(b['total_pnl'])}">₹{_n(b['total_pnl'],0)}</div></div>
</div>""")

    head = ("<tr><th>Engine</th><th class='n'>Trades</th><th class='n'>Win %</th><th class='n'>Total</th>"
            "<th class='n'>Mean</th><th class='n'>Median</th><th class='n'>Max DD</th>"
            "<th class='n'>Max cons. loss</th><th class='n'>Hold</th><th class='n'>MFE/u</th>"
            "<th class='n'>MAE/u</th><th class='n'>Stop/Flip/End</th></tr>")
    parts.append("<h2>3 · 13A vs 13B</h2><div class='tw'><table><thead>" + head + "<tbody>"
                 + f"<tr><td><b>13A</b>{'' if a['sufficient'] else ' <span class=tag>small N</span>'}</td>{_summary_row(a)}</tr>"
                 + f"<tr><td><b>13B</b>{'' if b['sufficient'] else ' <span class=tag>small N</span>'}</td>{_summary_row(b)}</tr>"
                 + "</tbody></table></div>")

    parts.append("<h3>The seven questions, answered separately from P&amp;L</h3>")
    qrows = "".join(
        f"<tr><td>{_e(k).replace('_',' ').title()}</td><td>{_yn(val.get('improved'))}</td>"
        f"<td class='wrap small'>{_e(val.get('detail'))}</td></tr>"
        for k, val in v.items() if isinstance(val, dict))
    parts.append(f"<div class='tw'><table style='min-width:640px'><thead><tr><th>Question</th>"
                 f"<th>Improved?</th><th>Measurement</th></tr></thead><tbody>{qrows}</tbody></table></div>")

    parts.append(f"""<div class="panel"><h3 style="margin-top:0">What happened to the blocked candidates</h3>
<p>Measured over the 10 minutes after the blocked signal, priced on the BID against the entry ASK.</p>
<div class="grid">
<div class="stat"><div class="k">Blocked</div><div class="v">{bl['blocked']}</div>
<div class="small">{bl['measurable']} measurable</div></div>
<div class="stat"><div class="k">Moved adversely</div><div class="v">{_n(bl['pct_moved_adversely'],1)}%</div>
<div class="small">{bl['moved_adversely']} of {bl['measurable']}</div></div>
<div class="stat"><div class="k">Moved favourably</div><div class="v">{_n(bl['pct_moved_favourably'],1)}%</div>
<div class="small">{bl['moved_favourably']} of {bl['measurable']}</div></div>
<div class="stat"><div class="k">Had a positive excursion</div><div class="v">{_n(bl['pct_had_positive_mfe'],1)}%</div>
<div class="small">given up by blocking</div></div>
<div class="stat"><div class="k">Mean end / unit</div><div class="v {_cls(bl['mean_end_per_unit'])}">{_n(bl['mean_end_per_unit'])}</div></div>
<div class="stat"><div class="k">Mean MFE / MAE</div><div class="v">{_n(bl['mean_mfe_per_unit'])} / {_n(bl['mean_mae_per_unit'])}</div></div>
</div></div>""")

    # ---- 4 / 5 ------------------------------------------------------------------------------------
    parts.append("<h2>4 · Rejected candidate examples</h2>")
    parts.append("<p class='small'>The ten worst forward outcomes among blocked candidates — "
                 "the cases where the block helped most.</p>")
    rows = "".join(
        f"<tr><td>{_e(x['session_date'])} {_e(x['minute'])}</td><td>{_e(x['symbol'])}</td>"
        f"<td>{_e(x['side'])} {_n(x.get('strike'),0)}</td><td>{_e(x['confirmation'])}</td>"
        f"<td class='n'>{_n(x.get('entry_ask'))}</td>"
        f"<td class='n {_cls(x.get('mfe'))}'>{_n(x.get('mfe'))}</td>"
        f"<td class='n {_cls(x.get('mae'))}'>{_n(x.get('mae'))}</td>"
        f"<td class='n {_cls(x.get('end'))}'>{_n(x.get('end'))}</td>"
        f"<td class='wrap small'>{_e(x.get('reason'))}</td></tr>"
        for x in p["rejected_examples"])
    parts.append("<div class='tw'><table style='min-width:900px'><thead><tr><th>When</th><th>Market</th>"
                 "<th>Contract</th><th>Verdict</th><th class='n'>Entry ASK</th><th class='n'>MFE</th>"
                 f"<th class='n'>MAE</th><th class='n'>End</th><th>Reason</th></tr></thead>"
                 f"<tbody>{rows}</tbody></table></div>")

    parts.append("<h2>5 · Accepted candidate examples</h2>")
    if p["accepted_examples"]:
        rows = "".join(
            f"<tr><td>{_e(x.get('session_date'))} {_e(x.get('signal_minute'))}</td>"
            f"<td>{_e(x.get('contract'))}</td><td>{_e(x.get('quality'))}</td>"
            f"<td class='n'>{_n(x.get('entry_ask'))}</td><td class='n'>{_n(x.get('exit_bid'))}</td>"
            f"<td>{_e(x.get('exit_reason'))}</td><td class='n'>{_e(x.get('hold_minutes'))}m</td>"
            f"<td class='n {_cls(x.get('realised_pnl'))}'>₹{_n(x.get('realised_pnl'))}</td></tr>"
            for x in p["accepted_examples"])
        parts.append("<div class='tw'><table><thead><tr><th>When</th><th>Contract</th><th>Q</th>"
                     "<th class='n'>Entry ASK</th><th class='n'>Exit BID</th><th>Exit</th>"
                     f"<th class='n'>Hold</th><th class='n'>P&amp;L</th></tr></thead>"
                     f"<tbody>{rows}</tbody></table></div>")
    else:
        parts.append("<div class='callout bad'><b>No candidate survived</b>Across every session "
                     "replayed, price action rejected every 13A buy. That is itself the finding: "
                     "either the gates are too strict, or the option engine's candidates genuinely "
                     "do not coincide with clean underlying setups.</div>")

    # ---- 6 ----------------------------------------------------------------------------------------
    parts.append("<h2>6 · Price-action classifications</h2>")
    parts.append(_counts(cmp["price_action_verdicts"], "Confirmation verdicts"))
    parts.append(_counts(cmp["structures"], "Structure"))
    parts.append(_counts(cmp["breaks"], "Break quality"))
    parts.append(_counts(cmp["setups"], "Setup type"))
    parts.append(_counts(cmp["vwap_states"], "VWAP context"))
    parts.append(_counts(cmp["value_states"], "Volume-profile context"))
    parts.append(_counts(cmp["volume_states"], "Volume"))

    # ---- 7 ----------------------------------------------------------------------------------------
    parts.append("<h2>7 · Leakage audit</h2>")
    rows = "".join(f"<tr><td>{_e(x['symbol'])}</td><td class='n'>{x['checked']}</td>"
                   f"<td class='n'>{x['fields_compared']}</td><td class='n'>{len(x['mismatches'])}</td>"
                   f"<td class='n'>{x['future_bar_used']}</td>"
                   f"<td>{'<span class=pass>PASS</span>' if x['passed'] else '<span class=fail>FAIL</span>'}</td></tr>"
                   for x in p["leakage"])
    parts.append("<div class='tw'><table><thead><tr><th>Symbol</th><th class='n'>Candidates</th>"
                 "<th class='n'>Fields</th><th class='n'>Mismatches</th>"
                 f"<th class='n'>Future-bar uses</th><th>Result</th></tr></thead><tbody>{rows}</tbody></table></div>")
    parts.append("""<div class="panel"><p style="margin-bottom:0">Two things are proved here.
Every feature is recomputed with all bars from the signal minute onward deleted and compared
field by field. Separately, the audit asserts the newest bar 13B consulted is stamped
<em>before</em> the signal minute — a 1-minute bar stamped 09:30 is not complete until 09:31, and
using it would be reading one minute into the future.</p></div>""")

    # ---- 8 / 9 ------------------------------------------------------------------------------------
    dq = p["data_quality"]
    parts.append("<h2>8 · Data-quality limitations</h2>")
    parts.append(f"""<ul>
<li>Blocked candidates with no forward option data to score: <b>{dq['blocked_without_forward_data']}</b>.</li>
<li>13A buys that produced no price-action verdict at all: <b>{dq['decisions_without_price_action']}</b>.</li>
<li>UNKNOWN verdicts (insufficient completed bars, typically early session): <b>{dq['unknown_verdicts']}</b>.</li>
<li>Volume-profile levels come from <code>levels_snapshots</code>; where a level is absent the
context is reported UNKNOWN rather than substituted.</li>
<li>Index volume is exchange-reported per 1-minute bar; it is used only as a relative ratio
against its own trailing average, never as an absolute claim about participation.</li>
</ul>""")

    parts.append("<h2>9 · Does the price-action layer materially change behaviour?</h2>")
    sel = cmp["pct_rejected_by_price_action"]
    enough = v["sufficient_sample"]
    parts.append(f"""<div class="callout {'bad' if not enough else ''}">
<b>{'Yes, in selectivity — but its trade quality is not yet measurable' if not enough else 'Yes'}</b>
13B removes <b>{_n(sel,1)}%</b> of 13A's buys, so it certainly changes behaviour. Whether it
removes the <em>right</em> ones is a different question: {bl['pct_moved_adversely']}% of blocked
candidates went on to move adversely, but {bl['pct_had_positive_mfe']}% had a positive excursion
that blocking gave up. With {b['trades']} surviving trades, the win-rate and drawdown comparisons
carry no weight.</div>""")

    parts.append(f"""<footer>{_e(cfg['version'])} · config <code>{_e(cfg['config_hash'])}</code> ·
paper / advisory only. 13A, 12E, 12D, 12C, 12B, 12A and 11D are unmodified; 13B can only remove
a trade, never create one. No threshold here was tuned against this report.
</footer></div></body></html>""")
    path.write_text("".join(parts), encoding="utf-8")
