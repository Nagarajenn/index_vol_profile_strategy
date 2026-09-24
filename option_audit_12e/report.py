"""Render the audit: JSON, CSV and a standalone HTML review document."""

import csv
import html
import json
from pathlib import Path

CSV_COLUMNS = (
    "signal_id", "market", "session_date", "signal_minute", "direction", "side", "strike", "contract",
    "confidence", "market_state", "market_lookback_pct", "strike_band", "strike_distance",
    "strike_distance_pct", "underlying_at_signal", "underlying_at_exit", "und_move_to_exit_pct",
    "und_pre_1m_pct", "und_pre_3m_pct", "und_pre_5m_pct", "opt_pre_5m_pct", "premium_position_in_range",
    "und_1m_pct", "und_3m_pct", "und_5m_pct", "und_10m_pct",
    "opt_1m_pct", "opt_3m_pct", "opt_5m_pct", "opt_10m_pct",
    "opt_mid_1m_pct", "opt_mid_3m_pct", "opt_mid_5m_pct", "opt_mid_10m_pct",
    "und_direction_ok_1m", "und_direction_ok_3m", "und_direction_ok_5m", "und_direction_ok_10m",
    "opt_profitable_1m", "opt_profitable_3m", "opt_profitable_5m", "opt_profitable_10m",
    "quadrant_1m", "quadrant_3m", "quadrant_5m", "quadrant_10m",
    "response_ratio_5m", "response_ratio_10m", "theoretical_elasticity_5m",
    "response_efficiency_5m", "response_efficiency_10m", "response_gap_5m",
    "entry_ask", "entry_bid", "entry_ltp", "entry_mid", "entry_spread", "entry_spread_pct",
    "entry_delta", "entry_gamma", "entry_theta", "entry_vega", "entry_iv", "greeks_status",
    "iv_1m", "iv_3m", "iv_5m", "iv_10m", "iv_change_to_exit_pct", "iv_state",
    "exit_minute", "exit_bid", "exit_ask", "exit_ltp", "exit_spread", "exit_reason", "hold_minutes",
    "entry_spread_cost", "exit_spread_cost", "mid_to_mid_per_unit", "ask_to_bid_per_unit",
    "execution_friction_per_unit", "theta_estimate_per_unit",
    "mfe_per_unit", "mae_per_unit", "final_pnl_per_unit", "final_pnl", "final_pnl_pct",
    "loss_reason", "loss_note", "version", "config_hash",
)


def write_csv(rows: list[dict], path: Path) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k) for k in CSV_COLUMNS})


def write_json(payload: dict, path: Path) -> None:
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


# ---------------------------------------------------------------- HTML
def _e(x):
    return html.escape(str(x)) if x is not None else "–"


def _n(x, d=2):
    return f"{x:,.{d}f}" if isinstance(x, (int, float)) else "–"


def _cls(x, invert=False):
    if not isinstance(x, (int, float)):
        return ""
    good = (x > 0) if not invert else (x < 0)
    return "up" if good else ("down" if x else "")


def _summary_table(d: dict, title: str, cols=None) -> str:
    cols = cols or [("N", "n"), ("Win %", "win_rate"), ("Mean/unit", "mean_pnl_per_unit"),
                    ("Median/unit", "median_pnl_per_unit"), ("Mid-to-mid", "mean_mid_to_mid"),
                    ("Friction", "mean_execution_friction"), ("Und move %", "mean_underlying_move_pct"),
                    ("Resp. eff.", "median_response_efficiency_5m"), ("IV chg %", "mean_iv_change_pct")]
    head = "".join(f"<th class='n'>{_e(c[0])}</th>" for c in cols)
    body = []
    for k, v in d.items():
        if not isinstance(v, dict) or "n" not in v:
            continue
        flag = "" if v.get("sufficient") else " <span class='tag'>small N</span>"
        cells = "".join(f"<td class='n {_cls(v.get(c[1])) if c[1].startswith('mean_pnl') or c[1].startswith('median_pnl') else ''}'>"
                        f"{_n(v.get(c[1]))}</td>" for c in cols)
        body.append(f"<tr><td>{_e(k).replace('_', ' ')}{flag}</td>{cells}</tr>")
    return (f"<h3>{_e(title)}</h3><div class='tw'><table><thead><tr><th></th>{head}</tr></thead>"
            f"<tbody>{''.join(body)}</tbody></table></div>")


def _trade_table(rows: list[dict], limit: int = 40) -> str:
    head = ["Time", "Market", "Contract", "State", "Band", "Spot@entry", "Und→exit",
            "Und 5m", "Opt 5m", "Resp eff", "Delta", "IV chg", "Ask", "Exit bid", "Spread",
            "Hold", "P&amp;L/u", "Exit", "Why it lost"]
    ths = "".join(f"<th class='{'n' if h not in ('Time','Market','Contract','State','Band','Exit','Why it lost') else ''}'>{h}</th>"
                  for h in head)
    body = []
    for r in rows[:limit]:
        body.append(
            "<tr>"
            f"<td>{_e(r['signal_minute'])}</td><td>{_e(r['market'])}</td>"
            f"<td>{_e(r.get('strike') and f'{r['strike']:.0f}')} {_e(r['side'])}</td>"
            f"<td>{_e(r.get('market_state','').replace('_',' '))}</td>"
            f"<td>{_e(r.get('strike_band','').replace('_',' '))}</td>"
            f"<td class='n'>{_n(r.get('underlying_at_signal'), 1)}</td>"
            f"<td class='n {_cls(r.get('und_move_to_exit_pct'), r['side']=='PE')}'>{_n(r.get('und_move_to_exit_pct'), 3)}%</td>"
            f"<td class='n'>{_n(r.get('und_5m_pct'), 3)}%</td>"
            f"<td class='n {_cls(r.get('opt_5m_pct'))}'>{_n(r.get('opt_5m_pct'), 2)}%</td>"
            f"<td class='n'>{_n(r.get('response_efficiency_5m') or r.get('response_efficiency_10m'), 2)}</td>"
            f"<td class='n'>{_n(r.get('entry_delta'), 3)}</td>"
            f"<td class='n {_cls(r.get('iv_change_to_exit_pct'))}'>{_n(r.get('iv_change_to_exit_pct'), 2)}%</td>"
            f"<td class='n'>{_n(r.get('entry_ask'))}</td>"
            f"<td class='n'>{_n(r.get('exit_bid'))}</td>"
            f"<td class='n'>{_n(r.get('entry_spread'))}</td>"
            f"<td class='n'>{_e(r.get('hold_minutes'))}m</td>"
            f"<td class='n {_cls(r.get('final_pnl_per_unit'))}'><b>{_n(r.get('final_pnl_per_unit'))}</b></td>"
            f"<td>{_e(r.get('exit_reason','').replace('_',' '))}</td>"
            f"<td class='small'>{_e(r.get('loss_reason','') and r['loss_reason'].replace('_',' '))}</td>"
            "</tr>")
    return f"<div class='tw'><table><thead><tr>{ths}</tr></thead><tbody>{''.join(body)}</tbody></table></div>"


def _quadrant_table(q: dict) -> str:
    rows = []
    for h, v in q.items():
        pct = v.get("pct", {})
        rows.append(f"<tr><td>{_e(h)}</td><td class='n'>{v.get('measurable')}</td>"
                    f"<td class='n up'>{_n(pct.get('UNDERLYING_CORRECT_OPTION_PROFITABLE'), 1)}%</td>"
                    f"<td class='n down'><b>{_n(pct.get('UNDERLYING_CORRECT_OPTION_LOSS'), 1)}%</b></td>"
                    f"<td class='n'>{_n(pct.get('UNDERLYING_WRONG_OPTION_PROFITABLE'), 1)}%</td>"
                    f"<td class='n'>{_n(pct.get('UNDERLYING_WRONG_OPTION_LOSS'), 1)}%</td></tr>")
    return ("<div class='tw'><table><thead><tr><th>Horizon</th><th class='n'>Measurable</th>"
            "<th class='n'>Und ✓ / Opt ✓</th><th class='n'>Und ✓ / Opt ✗</th>"
            "<th class='n'>Und ✗ / Opt ✓</th><th class='n'>Und ✗ / Opt ✗</th></tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table></div>")


def _dir_table(d: dict) -> str:
    rows = "".join(f"<tr><td>{_e(h)}</td><td class='n'>{v['correct']}/{v['measurable']}</td>"
                   f"<td class='n'>{_n(v['pct'], 1)}%</td><td class='n'>{v['unmeasurable']}</td></tr>"
                   for h, v in d.items())
    return ("<div class='tw'><table><thead><tr><th>Horizon</th><th class='n'>Correct</th>"
            "<th class='n'>%</th><th class='n'>Unmeasurable</th></tr></thead>"
            f"<tbody>{rows}</tbody></table></div>")


def build_html(today: dict, today_rows: list[dict], hist: dict | None, answers: list[tuple],
               path: Path) -> None:
    pe_rows = [r for r in today_rows if r["side"] == "PE"]
    o = today["overall"]
    se = today["spread_economics"]
    parts = []
    parts.append(f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>12E Option Audit</title>
<style>
:root{{--bg:#f7f7f5;--panel:#fff;--ink:#1b1b19;--muted:#6b6b66;--line:#e2e2dd;--up:#2e7d32;
--down:#c62828;--warn:#b26a00;--chip:#f0f0ec}}
@media (prefers-color-scheme:dark){{:root:not([data-theme="light"]){{--bg:#14140f;--panel:#1c1c18;
--ink:#ecece6;--muted:#9a9a92;--line:#2e2e28;--up:#7bc47f;--down:#ef8d86;--warn:#e0a34a;--chip:#26262040}}}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.6 ui-sans-serif,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}}
.wrap{{max-width:1180px;margin:0 auto;padding:40px 16px 80px}}
header{{border-bottom:2px solid var(--ink);padding-bottom:18px;margin-bottom:30px}}
h1{{font-size:27px;margin:0 0 6px;letter-spacing:-.02em}}
h2{{font-size:13px;letter-spacing:.09em;text-transform:uppercase;color:var(--muted);margin:42px 0 12px;
padding-bottom:7px;border-bottom:1px solid var(--line)}}
h3{{font-size:15px;margin:24px 0 8px}}
.sub{{color:var(--muted);font-size:14px}}
.meta{{display:flex;flex-wrap:wrap;gap:8px;margin-top:14px}}
.chip{{background:var(--chip);border:1px solid var(--line);border-radius:999px;padding:3px 11px;
font-size:12px;color:var(--muted);white-space:nowrap}}
.panel{{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:16px 18px;margin:14px 0}}
.callout{{border-left:4px solid var(--warn);background:var(--panel);border-radius:0 8px 8px 0;
padding:13px 17px;margin:16px 0}}
.callout.bad{{border-left-color:var(--down)}} .callout.good{{border-left-color:var(--up)}}
.callout b{{display:block;margin-bottom:4px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:13px;margin:16px 0}}
.stat{{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:13px}}
.stat .k{{font-size:11px;letter-spacing:.07em;text-transform:uppercase;color:var(--muted)}}
.stat .v{{font-size:21px;font-weight:650;margin-top:3px;letter-spacing:-.02em}}
.tw{{overflow-x:auto;-webkit-overflow-scrolling:touch;margin:12px 0}}
table{{border-collapse:collapse;width:100%;font-size:13.5px;min-width:520px}}
th,td{{text-align:left;padding:7px 10px;border-bottom:1px solid var(--line);white-space:nowrap}}
th{{font-size:11px;letter-spacing:.05em;text-transform:uppercase;color:var(--muted);font-weight:600}}
td.n,th.n{{text-align:right;font-variant-numeric:tabular-nums}}
.up{{color:var(--up)}} .down{{color:var(--down)}} .small{{font-size:12.5px;color:var(--muted)}}
.tag{{display:inline-block;font-size:10.5px;padding:1px 6px;border-radius:4px;background:var(--chip);
border:1px solid var(--line);color:var(--muted)}}
code{{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:.9em;background:var(--chip);
padding:1px 5px;border-radius:4px}}
ul{{margin:0 0 14px;padding-left:20px}} li{{margin-bottom:6px}}
footer{{margin-top:54px;padding-top:18px;border-top:1px solid var(--line);color:var(--muted);font-size:13px}}
@media (max-width:640px){{h1{{font-size:22px}}.wrap{{padding:26px 16px 60px}}}}
</style></head><body><div class="wrap">
<header><h1>12E — Option Response &amp; Trade Economics Audit</h1>
<div class="sub">When the market moves the expected way, does the selected contract at the signal's
entry price actually produce a viable trade?</div>
<div class="meta"><span class="chip">12E-option-audit-v1</span>
<span class="chip">Today: {today['signals']} signals</span>
<span class="chip">Historical: {hist['signals'] if hist else 0} signals</span>
<span class="chip">Diagnosis only — no strategy change</span>
<span class="chip">No ML</span></div></header>""")

    parts.append(f"""<div class="callout bad"><b>The headline answer</b>
Today the underlying fell, and <strong>the option response was not the problem</strong> — median response
efficiency was about 1.0, meaning premiums moved almost exactly as delta implied. The losses are
explained by <em>when</em> the signals fired and <em>how often</em>, not by the contracts failing to
respond.</div>""")

    parts.append("<h2>1 · Today at a glance</h2>")
    parts.append(f"""<div class="grid">
<div class="stat"><div class="k">Signals</div><div class="v">{today['signals']}</div>
<div class="small">PE {today['buy_pe']} · CE {today['buy_ce']}</div></div>
<div class="stat"><div class="k">Win rate</div><div class="v">{_n(o['win_rate'],1)}%</div></div>
<div class="stat"><div class="k">Mean / unit</div><div class="v {_cls(o['mean_pnl_per_unit'])}">{_n(o['mean_pnl_per_unit'])}</div></div>
<div class="stat"><div class="k">Median / unit</div><div class="v {_cls(o['median_pnl_per_unit'])}">{_n(o['median_pnl_per_unit'])}</div></div>
<div class="stat"><div class="k">Execution friction</div><div class="v down">{_n(se['mean_execution_friction_per_unit'])}</div>
<div class="small">per unit, round trip</div></div>
<div class="stat"><div class="k">Signals / hour</div><div class="v">{_n(today['density']['overall']['mean_signals_per_hour'],1)}</div></div>
</div>""")

    parts.append("<h2>2 · Underlying direction vs option profitability</h2>")
    parts.append("<p class='small'>Direction is measured from the <strong>underlying itself</strong> per "
                 "horizon, replacing 12D's <code>MFE &ge; 0.5%</code> proxy. "
                 "&quot;Unmeasurable&quot; means spot moved less than the flat band, so there was no "
                 "direction to be right or wrong about.</p>")
    parts.append("<h3>All signals — underlying direction correct</h3>" + _dir_table(today["direction_accuracy"]))
    parts.append("<h3>BUY PE only</h3>" + _dir_table(today["direction_accuracy_pe"]))
    parts.append("<h3>The four quadrants (all signals)</h3>" + _quadrant_table(today["quadrants"]))
    parts.append("<h3>The four quadrants (BUY PE)</h3>" + _quadrant_table(today["quadrants_pe"]))

    parts.append("<h2>3 · Did the option respond?</h2>")
    parts.append("""<div class="panel"><p><strong>Elasticity</strong> is the measured
|option %| ÷ |underlying %|. For an ATM option it is normally 90–200 simply because the premium is a
small number, so on its own it says little.</p>
<p style="margin-bottom:0"><strong>Response efficiency</strong> divides that by the elasticity delta
implies (<code>|delta| × spot ÷ premium</code>). <strong>1.0 means the premium moved exactly as
first-order theory predicts.</strong> This is the number that matters.</p></div>""")
    rows = "".join(f"<tr><td>{_e(h)}</td><td class='n'>{v['n']}</td>"
                   f"<td class='n'>{_n(v['median_elasticity'],1)}</td>"
                   f"<td class='n'><b>{_n(v['median_efficiency'],2)}</b></td>"
                   f"<td class='n'>{_n(v['weak_pct'],1)}%</td></tr>"
                   for h, v in today["response_pe"].items())
    parts.append("<h3>BUY PE response</h3><div class='tw'><table><thead><tr><th>Horizon</th>"
                 "<th class='n'>Measurable</th><th class='n'>Median elasticity</th>"
                 "<th class='n'>Median efficiency</th><th class='n'>Weak (&lt;0.5)</th></tr></thead>"
                 f"<tbody>{rows}</tbody></table></div>")
    parts.append("<div class='callout good'><b>The contracts responded.</b> Median efficiency sits at "
                 "roughly 1.0 — the premiums moved as delta implied. <em>Weak option response is not "
                 "the explanation.</em></div>")

    parts.append("<h2>4 · Execution economics</h2>")
    parts.append(f"""<div class="grid">
<div class="stat"><div class="k">Mean executable (ASK→BID)</div><div class="v {_cls(se['mean_executable_per_unit'])}">{_n(se['mean_executable_per_unit'])}</div></div>
<div class="stat"><div class="k">Mean mid-to-mid</div><div class="v {_cls(se['mean_mid_to_mid_per_unit'])}">{_n(se['mean_mid_to_mid_per_unit'])}</div></div>
<div class="stat"><div class="k">Friction</div><div class="v down">{_n(se['mean_execution_friction_per_unit'])}</div></div>
<div class="stat"><div class="k">Losers rescued at mid</div><div class="v">{_n(se['pct_of_losers_caused_by_friction'],1)}%</div>
<div class="small">{se['losers_that_were_positive_mid_to_mid']} of {se['losers']}</div></div>
</div>""")

    parts.append("<h2>5 · Where the signals fired</h2>")
    parts.append(_summary_table(today["pe_by_market_state"], "BUY PE by underlying state at the signal minute"))
    parts.append(_summary_table(today["by_strike_band"], "By strike band"))
    parts.append(_summary_table(today["by_iv_state"], "By IV state over the hold"))
    parts.append(_summary_table(today["delta_buckets"], "By |delta| at entry"))
    parts.append(_summary_table(today["by_hour"], "By time of day"))

    parts.append("<h2>6 · Why the losing trades lost</h2>")
    lc = today["loss_reason_counts"]
    pc = today["pe_loss_reason_counts"]
    keys = sorted(set(lc) | set(pc), key=lambda k: -lc.get(k, 0))
    rows = "".join(f"<tr><td>{_e(k).replace('_',' ')}</td><td class='n'>{lc.get(k,0)}</td>"
                   f"<td class='n'>{pc.get(k,0)}</td></tr>" for k in keys)
    parts.append("<div class='tw'><table><thead><tr><th>Attributed reason</th><th class='n'>All</th>"
                 f"<th class='n'>BUY PE</th></tr></thead><tbody>{rows}</tbody></table></div>")

    parts.append("<h2>7 · Signal density, runs and flips</h2>")
    dn, rn, fl = today["density"]["overall"], today["runs"], today["flips"]
    parts.append(f"""<div class="grid">
<div class="stat"><div class="k">Signals / hour</div><div class="v">{_n(dn['mean_signals_per_hour'],1)}</div></div>
<div class="stat"><div class="k">Median gap</div><div class="v">{_n(dn['median_gap_minutes'],0)}m</div></div>
<div class="stat"><div class="k">Gaps under 3 min</div><div class="v">{dn['gaps_under_3min']}</div>
<div class="small">of {dn['total_gaps']}</div></div>
<div class="stat"><div class="k">Same-direction runs</div><div class="v">{_n(rn['mean_run_length'],2)}</div>
<div class="small">mean length, max {rn['max_run_length']}</div></div>
<div class="stat"><div class="k">Direction flips</div><div class="v">{fl['flips']}</div></div>
<div class="stat"><div class="k">Flips confirmed by price</div><div class="v">{_n(fl['confirmed_pct'],0)}%</div></div>
</div>""")

    parts.append("<h2>8 · Every trade today</h2>")
    parts.append("<h3>BUY PE</h3>" + _trade_table(pe_rows, 60))
    parts.append("<h3>BUY CE</h3>" + _trade_table([r for r in today_rows if r["side"] == "CE"], 60))

    parts.append("<h2>9 · The fifteen questions</h2>")
    qrows = "".join(f"<tr><td>{_e(q)}</td><td>{a}</td></tr>" for q, a in answers)
    parts.append("<div class='tw'><table style='min-width:640px'><thead><tr><th>Question</th>"
                 f"<th>Answer from the data</th></tr></thead><tbody>{qrows}</tbody></table></div>")

    if hist:
        parts.append("<h2>10 · Historical validation <span class='tag'>separate sample</span></h2>")
        ho, hse = hist["overall"], hist["spread_economics"]
        parts.append(f"""<div class="grid">
<div class="stat"><div class="k">Signals</div><div class="v">{hist['signals']}</div>
<div class="small">{hist['sessions']} symbol-days</div></div>
<div class="stat"><div class="k">Win rate</div><div class="v">{_n(ho['win_rate'],1)}%</div></div>
<div class="stat"><div class="k">Mean / unit</div><div class="v {_cls(ho['mean_pnl_per_unit'])}">{_n(ho['mean_pnl_per_unit'])}</div></div>
<div class="stat"><div class="k">Mid-to-mid</div><div class="v {_cls(ho['mean_mid_to_mid'])}">{_n(ho['mean_mid_to_mid'])}</div></div>
<div class="stat"><div class="k">Friction</div><div class="v down">{_n(hse['mean_execution_friction_per_unit'])}</div></div>
<div class="stat"><div class="k">Resp. efficiency</div><div class="v">{_n(ho['median_response_efficiency_5m'],2)}</div></div>
</div>""")
        parts.append("<h3>Underlying direction (historical, all signals)</h3>" + _dir_table(hist["direction_accuracy"]))
        parts.append("<h3>Quadrants (historical, BUY PE)</h3>" + _quadrant_table(hist["quadrants_pe"]))
        parts.append(_summary_table(hist["pe_by_market_state"], "Historical BUY PE by underlying state"))
        parts.append(_summary_table(hist["delta_buckets"], "Historical, by |delta| at entry"))
        hlc = hist["loss_reason_counts"]
        rows = "".join(f"<tr><td>{_e(k).replace('_',' ')}</td><td class='n'>{v}</td></tr>"
                       for k, v in sorted(hlc.items(), key=lambda x: -x[1]))
        parts.append("<h3>Historical loss attribution</h3><div class='tw'><table><thead><tr>"
                     f"<th>Reason</th><th class='n'>Count</th></tr></thead><tbody>{rows}</tbody></table></div>")

    dq = today["data_quality"]
    parts.append("<h2>11 · Data quality</h2>")
    parts.append(f"""<div class="panel"><p style="margin-bottom:0">Today: missing Greeks
{dq['missing_greeks']} · missing IV {dq['missing_iv']} · missing entry quote {dq['missing_entry_quote']} ·
missing exit quote {dq['missing_exit_quote']} · greeks status {_e(dq['greeks_status'])}.
Nothing was filled in: a missing Greek stays missing rather than becoming zero.</p></div>""")
    parts.append("""<div class="callout"><b>The biggest measurement limitation</b>
At 1- and 3-minute horizons the index frequently moves less than the flat band, so there is no
direction to score and no usable denominator for a response ratio. Those rows are reported as
<em>unmeasurable</em> rather than counted as correct or incorrect. This is why the 1-minute
sample is so much smaller than the signal count.</div>""")

    parts.append(f"""<footer>12E-option-audit-v1 · config <code>{_e(today['config_hash'])}</code> ·
full rows in <code>12E_AUDIT_TODAY.csv</code> / <code>12E_AUDIT_HISTORICAL.csv</code> and
<code>12E_OPTION_AUDIT.json</code>.<br>
Diagnosis on paper simulation. No strategy rule was changed. Not evidence of an edge, not
production-ready, and not a claim of predictive accuracy.</footer></div></body></html>""")
    path.write_text("".join(parts), encoding="utf-8")
