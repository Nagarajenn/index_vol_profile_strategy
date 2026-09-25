"""The two HTML reports (spec 33): implementation and replay."""

import html


def _e(x):
    return html.escape(str(x)) if x is not None else "–"


def _n(x, d=2):
    return f"{x:,.{d}f}" if isinstance(x, (int, float)) else "–"


def _cls(x):
    if not isinstance(x, (int, float)) or x == 0:
        return ""
    return "up" if x > 0 else "down"


CSS = """
:root{--bg:#f7f7f5;--panel:#fff;--ink:#1b1b19;--muted:#6b6b66;--line:#e2e2dd;--up:#2e7d32;
--down:#c62828;--warn:#b26a00;--chip:#f0f0ec}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#14140f;--panel:#1c1c18;
--ink:#ecece6;--muted:#9a9a92;--line:#2e2e28;--up:#7bc47f;--down:#ef8d86;--warn:#e0a34a;--chip:#26262040}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.6 ui-sans-serif,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
.wrap{max-width:1120px;margin:0 auto;padding:40px 16px 80px}
header{border-bottom:2px solid var(--ink);padding-bottom:18px;margin-bottom:30px}
h1{font-size:27px;margin:0 0 6px;letter-spacing:-.02em}
h2{font-size:13px;letter-spacing:.09em;text-transform:uppercase;color:var(--muted);margin:42px 0 12px;
padding-bottom:7px;border-bottom:1px solid var(--line)}
h3{font-size:15px;margin:24px 0 8px}
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
.up{color:var(--up)}.down{color:var(--down)}.small{font-size:12.5px;color:var(--muted)}
.tag{display:inline-block;font-size:10.5px;padding:1px 6px;border-radius:4px;background:var(--chip);
border:1px solid var(--line);color:var(--muted)}
.pass{color:var(--up);font-weight:700}.fail{color:var(--down);font-weight:700}
code{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:.9em;background:var(--chip);padding:1px 5px;border-radius:4px}
ul{margin:0 0 14px;padding-left:20px}li{margin-bottom:6px}
footer{margin-top:54px;padding-top:18px;border-top:1px solid var(--line);color:var(--muted);font-size:13px}
@media (max-width:640px){h1{font-size:22px}.wrap{padding:26px 16px 60px}}
"""


def _head(title, h1, sub, chips):
    cs = "".join(f'<span class="chip">{_e(c)}</span>' for c in chips)
    return (f'<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width, initial-scale=1">'
            f'<title>{_e(title)}</title><style>{CSS}</style></head><body><div class="wrap">'
            f'<header><h1>{_e(h1)}</h1><div class="sub">{_e(sub)}</div>'
            f'<div class="meta">{cs}</div></header>')


def _status(ok, yes="PASS", no="FAIL"):
    return f'<span class="{"pass" if ok else "fail"}">{yes if ok else no}</span>'


def build_implementation_report(p: dict, path) -> None:
    cfg, rec, cs = p["config"], p["reconciliation"], p["case_study"]
    ri, ci, xs = rec["research_identity"], rec["command_center_identity"], rec["cross_source"]
    g, r = cfg["gates"], cfg["risk"]
    parts = [_head("13A Implementation", "13A — Live Scalping Engine + Risk Brake",
                   "What changed, why, and what is still uncertain.",
                   [cfg["version"], f"config {cfg['config_hash']}", "Decision support only",
                    "No broker order path", "No ML"])]

    parts.append("""<div class="callout bad"><b>Status</b>
This is a <strong>selectivity and risk-control</strong> change, not a profitability claim.
13A does not predict better than 12C — it declines far more trades and says why. Nothing here
is validated for live deployment; see the go/no-go table at the end.</div>""")

    parts.append("<h2>1 · What changed and why</h2>")
    parts.append("""<div class="panel"><p>12E established three things that shaped every gate below:</p>
<ul>
<li>Option response was <strong>not</strong> the problem — median response efficiency ≈ 1.0.</li>
<li>Signals fire overwhelmingly in <strong>RANGE</strong> conditions: 211 of 241 historical PE
signals, where there is no trend to capture.</li>
<li>Execution friction consumes <strong>84%</strong> of the gross result (mid-to-mid +0.55/unit
becomes +0.09/unit executable).</li>
</ul>
<p style="margin-bottom:0">So 13A does not try to read the market better. It refuses trades whose
<em>context</em> or <em>economics</em> do not justify paying the spread.</p></div>""")

    rows = [
        ("Regime gate", f"CE needs TRENDING_UP, PE needs TRENDING_DOWN. RANGE and REVERSING are refused "
                        f"(both toggleable). Trend = |move| ≥ {g['regime_trend_pct']}% over "
                        f"{g['regime_lookback_min']} minutes.", "12E: 211 of 241 PE signals fired in RANGE"),
        ("Underlying confirmation", f"The direction must be visible in spot itself: ≥{g['und_confirm_pct_3m']}% "
                                    f"over 3 minutes, and the last minute must not oppose it.",
         "Direction measured from spot was ~50% — a coin flip"),
        ("Option confirmation", f"{g['option_min_categories']} of 4 independent categories: relative "
                                f"strength, own momentum, participation, other-side weakness.",
         "No single indicator is sufficient"),
        ("Entry timing", f"EXTENDED when the premium is already +{g['timing_extended_opt_pre_5m']}% or spot "
                         f"±{g['timing_extended_und_pre_5m']}% before the signal, or the premium sits above "
                         f"{g['timing_extended_range_position']}% of its range without accelerating.",
         "Rebuilt from continuous measures; 12D's labels had no discriminative power"),
        ("Spread", f"Relative only: spread ≤ {g['max_spread_pct_of_premium']}% of premium. Never a fixed "
                   f"rupee threshold.", "A 0.50 spread is cheap at 250 and ruinous at 15"),
        ("Economics", f"Expected first-order move ≥ {g['min_expected_move_to_spread_ratio']}× the round-trip "
                      f"spread, from delta and the last {g['expected_move_lookback_min']} minutes.",
         "Friction consumed 84% of the gross result"),
        ("IV", "An IV headwind never rejects; it costs one quality grade.",
         "IV tailwind +9.08/unit vs headwind −2.15 historically"),
    ]
    parts.append("<div class='tw'><table><thead><tr><th>Gate</th><th>Rule</th><th>Evidence behind it</th>"
                 "</tr></thead><tbody>" + "".join(
                     f"<tr><td><b>{_e(a)}</b></td><td class='small'>{_e(b)}</td>"
                     f"<td class='small'>{_e(c)}</td></tr>" for a, b, c in rows) + "</tbody></table></div>")

    parts.append("<h2>2 · P&amp;L reconciliation <span class='tag'>gate</span></h2>")
    parts.append(f"""<div class="panel"><p>The identity checked is
<code>cash P&amp;L = (exit BID − entry ASK) × quantity</code>, per row, in both sources.</p>
<div class="tw"><table><thead><tr><th>Source</th><th class="n">Rows</th><th class="n">Checked</th>
<th class="n">Unpriced</th><th class="n">Mismatches</th><th>Result</th></tr></thead><tbody>
<tr><td>{_e(ri['source'])}</td><td class="n">{ri['rows']}</td><td class="n">{ri['checked']}</td>
<td class="n">{ri['unpriced']}</td><td class="n">{len(ri['mismatches'])}</td>
<td>{_status(ri['exact'], 'EXACT')}</td></tr>
<tr><td>{_e(ci['source'])}</td><td class="n">{ci['rows']}</td><td class="n">{ci['checked']}</td>
<td class="n">{ci['unpriced']}</td><td class="n">{len(ci['mismatches'])}</td>
<td>{_status(ci['exact'], 'EXACT')}</td></tr></tbody></table></div>
<p class="small" style="margin-bottom:0">Cross-source: <b>{xs['matched_same_exit_minute']}</b> signals
closed at the same minute in both — all agree exactly ({len(xs['mismatches'])} mismatches).
<b>{xs['matched_different_exit_minute']}</b> closed at different minutes, which is an
<em>explained</em> difference: 12C's simulator closes when the entry decision turns WAIT, while
12D's manager ignores the entry decision entirely. {xs['unmatched']} research rows have no
Command Center counterpart because only two sessions have been stored there.</p></div>""")

    parts.append("<h2>3 · Risk brake</h2>")
    parts.append(f"""<div class="callout"><b>Allocated capital is not the loss limit</b>
₹{_n(r['experiment_capital'],0)} is the money set aside for the experiment. The most it may lose in a
day is ₹{_n(r['max_daily_loss'],0)} — a separate, much smaller number. The UI shows both, plus what
remains, and never presents one as the other.</div>""")
    parts.append("<div class='tw'><table><thead><tr><th>Limit</th><th class='n'>Value</th><th>Effect</th>"
                 "</tr></thead><tbody>" + "".join(
                     f"<tr><td>{a}</td><td class='n'>{b}</td><td class='small'>{c}</td></tr>" for a, b, c in [
                         ("Allocated capital", f"₹{_n(r['experiment_capital'],0)}", "Not a loss limit"),
                         ("Max daily loss", f"₹{_n(r['max_daily_loss'],0)}", "LOCKED on realised losses"),
                         ("Max loss per trade", f"₹{_n(r['max_loss_per_trade'],0)}", "Sizing guard"),
                         ("Max consecutive losses", r['max_consecutive_losses'], "LOCKED"),
                         ("Max trades per day", r['max_trades_per_day'], "LOCKED"),
                         ("Max position value", f"₹{_n(r['max_position_value'],0)}", "Entry refused above this"),
                     ]) + "</tbody></table></div>")
    parts.append("<p class='small'>When LOCKED, BUY CE and BUY PE are both disabled and only WAIT is "
                 "produced. An already-open position is still managed — refusing to manage a live "
                 "position is not risk control.</p>")

    parts.append("<h2>4 · Case study — 2026-09-24 <span class='tag'>acceptance test</span></h2>")
    parts.append("<p class='small'>The actual decisions, not a forced result.</p>")
    for sym, s in cs["symbols"].items():
        rv = s["review"]
        parts.append(f"<h3>{_e(sym)}</h3><div class='grid'>"
                     f"<div class='stat'><div class='k'>12C candidate minutes</div><div class='v'>{s['base_signals']}</div></div>"
                     f"<div class='stat'><div class='k'>13A buys</div><div class='v'>{len(s['buys'])}</div></div>"
                     f"<div class='stat'><div class='k'>Rejected: RANGE</div><div class='v'>{rv['rejected_range']}</div></div>"
                     f"<div class='stat'><div class='k'>Rejected: EXTENDED</div><div class='v'>{rv['rejected_extended']}</div></div>"
                     f"<div class='stat'><div class='k'>Realised</div><div class='v {_cls(rv['realised_pnl'])}'>₹{_n(rv['realised_pnl'])}</div></div>"
                     f"</div>")
        if s["positions"]:
            parts.append("<div class='tw'><table><thead><tr><th>Signal</th><th>Contract</th><th>Q</th>"
                         "<th class='n'>Entry ASK</th><th class='n'>Exit BID</th><th>Exit</th>"
                         "<th class='n'>Hold</th><th class='n'>P&amp;L</th></tr></thead><tbody>" + "".join(
                             f"<tr><td>{_e(x['signal_minute'])}</td><td>{_e(x['contract'])}</td>"
                             f"<td>{_e(x['quality'])}</td><td class='n'>{_n(x['entry_ask'])}</td>"
                             f"<td class='n'>{_n(x['exit_bid'])}</td><td>{_e(x['exit_reason'])}</td>"
                             f"<td class='n'>{_e(x['hold_minutes'])}m</td>"
                             f"<td class='n {_cls(x['realised_pnl'])}'>₹{_n(x['realised_pnl'])}</td></tr>"
                             for x in s["positions"]) + "</tbody></table></div>")

    parts.append("<h2>5 · Leakage audit</h2>")
    parts.append("<div class='tw'><table><thead><tr><th>Symbol</th><th class='n'>Candidates</th>"
                 "<th class='n'>Fields</th><th class='n'>Mismatches</th><th>Result</th></tr></thead><tbody>"
                 + "".join(f"<tr><td>{_e(a['symbol'])}</td><td class='n'>{a['checked']}</td>"
                           f"<td class='n'>{a['fields_compared']}</td><td class='n'>{len(a['mismatches'])}</td>"
                           f"<td>{_status(a['passed'])}</td></tr>" for a in p["leakage"])
                 + "</tbody></table></div>")
    parts.append("<p class='small'>Every feature is recomputed with all later minutes deleted and "
                 "compared field by field, including the regime verdict itself.</p>")
    parts.append(_go_no_go(p))
    parts.append(_footer(cfg))
    path.write_text("".join(parts), encoding="utf-8")


def _go_no_go(p: dict) -> str:
    rec, per = p["reconciliation"], p["periods"]
    unseen = per.get("unseen", {}).get("thirteen_a", {})
    val = per.get("validation", {}).get("thirteen_a", {})
    enough_unseen = unseen.get("sufficient", False)
    rows = [
        ("Signal engine", "IMPLEMENTED", "12C candidates filtered by 7 gates; 12C itself unmodified."),
        ("P&L reconciliation", "PASS" if rec["passed"] else "FAIL",
         "Identity exact in both sources; cross-source differences explained by exit rule."),
        ("Range filter", "IMPLEMENTED", "Configurable; the dominant rejection in every period."),
        ("Timing filter", "IMPLEMENTED", "Rebuilt from continuous pre-signal measures."),
        ("IV filter", "IMPLEMENTED", "Downgrades quality; never rejects alone."),
        ("Spread filter", "IMPLEMENTED", "Relative to premium, not a fixed rupee amount."),
        ("Risk brake", "IMPLEMENTED", "Daily loss, consecutive losses and trade count all lock."),
        ("Historical validation", "INSUFFICIENT" if not val.get("sufficient") else "LIMITED",
         f"Validation period: {val.get('trades', 0)} trades. Too few to characterise anything."),
        ("Unseen validation", "NOT VALIDATED" if not enough_unseen else "LIMITED",
         f"Unseen period: {unseen.get('trades', 0)} trades. "
         f"NOT VALIDATED FOR LIVE DEPLOYMENT."),
        ("Live decision support", "READY (decision only)",
         "Live data, real-time gates, hypothetical position, risk brake, no order path."),
    ]
    body = "".join(f"<tr><td><b>{_e(a)}</b></td><td>{_e(b)}</td><td class='small'>{_e(c)}</td></tr>"
                   for a, b, c in rows)
    return ("<h2>6 · Go / no-go</h2><div class='tw'><table><thead><tr><th>Item</th><th>Status</th>"
            f"<th>Detail</th></tr></thead><tbody>{body}</tbody></table></div>"
            "<div class='callout bad'><b>NOT VALIDATED FOR LIVE DEPLOYMENT</b>"
            "The unseen period contains too few surviving trades to validate anything. 13A is a "
            "selectivity and risk-control change with an audit trail — it is not evidence of an "
            "edge, and nothing here should be read as a profitability claim.</div>")


def _footer(cfg) -> str:
    return (f"<footer>{_e(cfg['version'])} · config <code>{_e(cfg['config_hash'])}</code> · "
            "decision support only. No order is placed and no broker API is reachable from this "
            "package. Gates are provisional measurement boundaries, not validated rules."
            "</footer></div></body></html>")


def build_replay_report(p: dict, path) -> None:
    ov, per = p["overall"], p["periods"]
    cfg = p["config"]
    parts = [_head("13A Replay", "13A — Historical Replay",
                   "12D unfiltered versus 13A filtered, on identical signal streams.",
                   [cfg["version"], f"{p['sessions']} sessions", "Chronological split",
                    "No threshold optimised on outcomes"])]

    a, b = ov["thirteen_a"], ov["twelve_d"]
    parts.append(f"""<div class="grid">
<div class="stat"><div class="k">12D trades</div><div class="v">{b['trades']}</div></div>
<div class="stat"><div class="k">13A trades</div><div class="v">{a['trades']}</div>
<div class="small">{_n(ov['trades_removed_pct'],1)}% removed</div></div>
<div class="stat"><div class="k">12D total</div><div class="v {_cls(b['total_pnl'])}">₹{_n(b['total_pnl'],0)}</div></div>
<div class="stat"><div class="k">13A total</div><div class="v {_cls(a['total_pnl'])}">₹{_n(a['total_pnl'],0)}</div></div>
<div class="stat"><div class="k">13A win rate</div><div class="v">{_n(a['win_rate'],1)}%</div></div>
<div class="stat"><div class="k">13A max drawdown</div><div class="v down">₹{_n(a['max_drawdown'],0)}</div></div>
</div>""")

    parts.append("<h2>1 · By period <span class='tag'>chronological, never random</span></h2>")
    head = ("<tr><th>Period</th><th class='n'>Sessions</th><th class='n'>12D trades</th>"
            "<th class='n'>12D total</th><th class='n'>13A trades</th><th class='n'>13A total</th>"
            "<th class='n'>13A win %</th><th class='n'>Max DD</th><th class='n'>Max cons. losses</th></tr>")
    body = ""
    for name in ("development", "validation", "unseen"):
        q = per.get(name)
        if not q:
            continue
        x, y = q["thirteen_a"], q["twelve_d"]
        flag = "" if x["sufficient"] else " <span class='tag'>small N</span>"
        body += (f"<tr><td><b>{_e(name)}</b>{flag}</td><td class='n'>{q['sessions']}</td>"
                 f"<td class='n'>{y['trades']}</td><td class='n {_cls(y['total_pnl'])}'>₹{_n(y['total_pnl'],0)}</td>"
                 f"<td class='n'>{x['trades']}</td><td class='n {_cls(x['total_pnl'])}'>₹{_n(x['total_pnl'],0)}</td>"
                 f"<td class='n'>{_n(x['win_rate'],1)}%</td><td class='n'>₹{_n(x['max_drawdown'],0)}</td>"
                 f"<td class='n'>{_e(x['max_consecutive_losses'])}</td></tr>")
    parts.append(f"<div class='tw'><table><thead>{head}</thead><tbody>{body}</tbody></table></div>")

    parts.append("<h2>2 · What was removed, and why</h2>")
    rj = ov["rejections"]
    body = "".join(f"<tr><td>{_e(k).replace('_',' ')}</td><td class='n'>{v}</td></tr>"
                   for k, v in rj.items())
    parts.append(f"<div class='tw'><table><thead><tr><th>Primary rejection reason</th>"
                 f"<th class='n'>Decisions</th></tr></thead><tbody>{body}</tbody></table></div>")
    parts.append(f"""<div class="panel"><p style="margin-bottom:0">Removed by category —
regime <b>{ov['removed_by_regime']}</b> · timing <b>{ov['removed_by_timing']}</b> ·
underlying <b>{ov['removed_by_underlying']}</b> · option confirmation <b>{ov['removed_by_option']}</b> ·
spread <b>{ov['removed_by_spread']}</b> · economics <b>{ov['removed_by_economics']}</b> ·
quality <b>{ov['removed_by_quality']}</b> · risk lock <b>{ov['removed_by_risk_lock']}</b>.</p></div>""")

    parts.append("<h2>3 · 13A trade composition</h2>")
    parts.append("<div class='tw'><table><thead><tr><th>Breakdown</th><th>Counts</th></tr></thead><tbody>"
                 f"<tr><td>By side</td><td>{_e(a['by_side'])}</td></tr>"
                 f"<tr><td>By quality</td><td>{_e(a['by_quality'])}</td></tr>"
                 f"<tr><td>By exit reason</td><td>{_e(a['by_exit'])}</td></tr>"
                 f"<tr><td>Mean hold</td><td>{_n(a['mean_hold_minutes'],1)} minutes</td></tr>"
                 "</tbody></table></div>")

    parts.append("""<div class="callout bad"><b>How to read this</b>
Fewer trades is the <em>intent</em>, not the achievement. A smaller loss on far fewer trades is
consistent with the filters working and also consistent with simply trading less of a
break-even-minus-costs signal. With this few surviving trades in the unseen period, the two
cannot be told apart, and no threshold here has been validated out of sample.</div>""")
    parts.append(_footer(cfg))
    path.write_text("".join(parts), encoding="utf-8")
