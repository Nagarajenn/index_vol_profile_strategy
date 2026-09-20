"""Part 1 -- source-level audit of which 5-second data 12A-scalp-v1 actually uses (READ-ONLY).

Static facts are taken from the source (line references verified with grep at
build time); the trace replays one real historical candidate through the
UNCHANGED engine and prints every 5-second bar with its timestamps.
Output: milestone12a_5sec_usage_audit.html. No DB writes, no code changes.
"""

import sys
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scalp_12a import db  # noqa: E402
from scalp_12a.config import DEFAULT_CONFIG  # noqa: E402
from scalp_12a.engine import evaluate_day  # noqa: E402
from scalp_12a.exits import simulate_exit  # noqa: E402
from scalp_12a.thresholds import build_thresholds  # noqa: E402

REPORT = ROOT / "milestone12a_5sec_usage_audit.html"
TRACE = ("2026-09-17", "NIFTY", "15:00:50")      # event bar start of a canonical 30 s MOMENTUM candidate

# (field, loaded?, source table.column, loader, used for, where)  -- verified against the source
FIELDS = [
    ("5-s futures price", "YES", "hr_ohlc_5s.close (instrument_type FUTIDX) + update_count",
     "db.load_session &rarr; SessionBars.fut / fut_updated",
     "DETECTION (only input); confirmation (persistence, extension); risk (invalidation level); exit (invalidation, retrace, divergence); research",
     "events.detect_event (r15/r30/r180/r300), events.futures_stale, events.step_consistency, confirmation.confirm, exits.simulate_exit, opportunity.measure"),
    ("5-s underlying / index", "LOADED, NEVER USED", "hr_ohlc_5s.close (INDEX)", "SessionBars.idx",
     "&mdash; (not read by any 12A function)", "no reference outside models.py / db.py"),
    ("5-s CE / PE mid", "YES", "hr_option_5s.mid", "SessionBars.quotes[(type, offset)].mid",
     "OPTION SELECTION + CONFIRMATION (30 s / 180 s response of the selected leg, read only after detection); research",
     "option_selector.leg_response_pct &rarr; confirmation.confirm (option_response_ok)"),
    ("5-s bid / ask", "YES", "hr_option_5s.bid, ask, spread_pct", "Quote.bid / ask / spread_pct",
     "SELECTION (valid quote, spread &le; 1%), RISK (ASK at decision bar), ENTRY (ASK at bar i+2), EXIT (BID path, spread expansion)",
     "option_selector.select_option, risk.plan_risk, engine.evaluate_session, exits.simulate_exit, counterfactual.track"),
    ("quote age", "YES", "hr_option_5s.quote_age_s", "Quote.quote_age_s", "SELECTION (&le; 10 s)", "option_selector.select_option"),
    ("5-s option volume", "YES (liquidity only)", "hr_option_5s.volume_delta", "Quote.volume_delta",
     "SELECTION: 30 s volume must be &gt; 0 (never as a signal)", "option_selector.recent_volume"),
    ("5-s futures volume", "NOT LOADED", "hr_ohlc_5s.volume (FUTIDX)", "&mdash;", "&mdash;", "column not selected in db.load_session"),
    ("5-s OI", "NOT LOADED", "hr_option_5s.oi, oi_delta", "&mdash;", "&mdash;", "column not selected"),
    ("option depth imbalance", "LOADED, NEVER USED", "hr_option_5s.depth_imbalance", "Quote.depth_imbalance", "&mdash;", "no reference outside models.py / db.py"),
    ("option L1 / 5-level quantities", "NOT LOADED", "hr_option_5s.bid_qty_l1, ask_qty_l1, bid_qty_total5, ask_qty_total5", "&mdash;", "&mdash;", "&mdash;"),
    ("futures bid / ask / depth", "NOT LOADED", "hr_option_transition_state.futures_bid / futures_ask", "&mdash;", "&mdash;", "&mdash;"),
    ("CE/PE aggregates (straddle, PCR, imbalances)", "NOT LOADED", "hr_option_transition_state.*", "&mdash;", "&mdash;", "&mdash;"),
]


def main():
    cfg = DEFAULT_CONFIG
    d_str, sym, bar_start = TRACE
    with db.connect() as conn:
        hr = [r for r in db.hr_session_ids(conn) if r[2] != "RUNNING"]
        days = [r[0] for r in hr]
        sid = {r[0]: r[1] for r in hr}
        sessions = {d: {s: db.load_session(conn, sid[d], d, s) for s in cfg.symbols} for d in days}
    d = next(x for x in days if str(x) == d_str)
    prior = [x for x in days if x < d]
    thr = {s: build_thresholds([sessions[p][s] for p in prior], cfg) for s in cfg.symbols}
    res = evaluate_day(list(sessions[d].values()), thr, cfg)
    s = sessions[d][sym]
    c = next(c for c in res[sym].candidates if c.bar_ts.strftime("%H:%M:%S") == bar_start)
    key = (c.selection.leg.option_type, c.selection.leg.atm_offset)
    e_i = c.bar_index + cfg.entry_delay_bars
    x = simulate_exit(s, key, e_i, c.event, c.risk, cfg)
    start_i = c.bar_index - 30 // cfg.bar_seconds
    close = lambda i: (s.times[i] + timedelta(seconds=5)).strftime("%H:%M:%S")
    marks = {start_i: "EVENT START (30 s origin)", c.bar_index: "DETECTION bar (r30 &ge; thr)",
             c.bar_index + 1: "bar i+1 (earliest quote formed after a streaming detector could act)",
             e_i: "ENTRY (ASK, bar i+2)", x.exit_index: f"EXIT (BID) &mdash; {x.reason}"}
    rows = []
    for i in range(start_i - 6, (x.exit_index or e_i) + 3):
        f, fp = s.fut_ffill(i), s.fut_ffill(i - 1)
        q, ce, pe = s.quote(key, i), s.quote(("CE", 0), i), s.quote(("PE", 0), i)
        rows.append([s.times[i].strftime("%H:%M:%S"), close(i), f"{f:.2f}" if f else "", f"{f - fp:+.2f}" if f and fp else "",
                     f"{ce.mid:.2f}" if ce else "", f"{pe.mid:.2f}" if pe else "",
                     f"{q.bid:.2f} / {q.ask:.2f}" if q else "", f"{q.mid:.2f}" if q else "", f"{q.spread_pct:.2f}%" if q else "",
                     f"{q.volume_delta:,.0f}" if q and q.volume_delta is not None else "", marks.get(i, "")])
    sel0 = s.quote(key, start_i).mid
    seld = s.quote(key, c.bar_index).mid
    stage = [
        ("Raw 5-s futures", f"hr_ohlc_5s FUTIDX, bars {s.times[start_i - 6].strftime('%H:%M:%S')}&hellip; (receive-time buckets; quote state = last value at bucket end)"),
        ("Raw 5-s CE/PE", "hr_option_5s ATM&plusmn;5; loaded for every bar but NOT read until an event exists"),
        ("Event start", f"{s.times[start_i].strftime('%H:%M:%S')} bar start (origin of the 30 s window), futures {s.fut_ffill(start_i):.2f}"),
        ("Event detection", f"bar {bar_start}&ndash;{close(c.bar_index)}: r30 = {c.event.r30:+.2f} pts &ge; thr30 {thr[sym].thr30_event:.2f} "
                            f"(from {', '.join(thr[sym].history_days)}); event {c.event.event_type} {c.event.strength}; "
                            f"available to a live DB poller &asymp; {close(c.bar_index)} + 3.3 s (median HR write latency)"),
        ("Confirmation", f"persistence {c.confirmation.get('persistence')}, option response {c.confirmation.get('option_response_pct'):+.2f}% "
                         f"(selected leg mid {sel0:.2f} &rarr; {seld:.2f} over the same 30 s), extended={c.confirmation.get('extended')}"),
        ("Option selection", f"{c.selection.leg.option_type} {c.selection.leg.strike:.0f} (offset {c.selection.leg.atm_offset}), "
                             f"score {c.selection.score}, rejections {c.selection.rejections}"),
        ("Risk", f"decision ASK {c.risk.entry_ref_ask:.2f}, stop {c.risk.stop_price:.2f}, target {c.risk.target_price:.2f}, "
                 f"qty {c.risk.quantity} units, invalidation {c.risk.underlying_invalidation:.2f}, reasons {c.no_trade_reasons or 'none'}"),
        ("Entry", f"ASK {x.entry_ask:.2f} at close of bar i+2 = {close(e_i)} ({(s.times[e_i] - s.times[c.bar_index]).total_seconds():.0f} s after the detection bar close)"),
        ("Exit", f"BID {x.exit_bid:.2f} at {close(x.exit_index)} &mdash; {x.reason}; P&amp;L {x.pnl_pct:+.2f}%, held {x.hold_seconds:.0f} s"),
    ]
    css = ("body{font-family:Georgia,serif;max-width:1240px;margin:0 auto;padding:30px 22px 70px;background:#fbfaf7;color:#1c1c1c;line-height:1.5}"
           "h1{border-bottom:3px solid #2c3e50;padding-bottom:8px;font-size:1.6em}h2{color:#1a3a5c;border-left:5px solid #2c3e50;padding-left:10px;font-size:1.2em;margin-top:2em}"
           "table{border-collapse:collapse;width:100%;font-size:0.8em;margin:10px 0}th,td{border:1px solid #ccc;padding:4px 7px;text-align:left;vertical-align:top}"
           "th{background:#2c3e50;color:#fff}tr:nth-child(even){background:#f2f0ea}code{background:#eee;padding:1px 4px}"
           ".finding{background:#e8f0fe;border-left:4px solid #1a3a5c;padding:10px 14px;margin:14px 0}.risk{background:#ffebee;border-left:4px solid #c62828;padding:10px 14px;margin:14px 0}")
    t = lambda h, rs: "<table><tr>" + "".join(f"<th>{x}</th>" for x in h) + "</tr>" + "".join(
        "<tr>" + "".join(f"<td>{v}</td>" for v in r) + "</tr>" for r in rs) + "</table>"
    o = [f"<!DOCTYPE html><html lang='en'><head><meta charset='UTF-8'><title>12A 5-Second Usage Audit</title><style>{css}</style></head><body>"]
    o.append("<h1>12A-scalp-v1 &mdash; 5-Second Data Usage Audit<br><span style='font-size:0.6em;font-weight:normal;color:#555'>"
             f"Source-level, read-only &middot; config hash <code>{cfg.config_hash()}</code> &middot; no code changed</span></h1>")
    o.append("<div class='risk'><b>Answer to C (the critical question):</b> option 5-second data is used <b>only AFTER</b> the event detector has "
             "triggered. <code>engine.evaluate_session</code> calls <code>detect_event</code> (line 72) &mdash; which reads only the futures series &mdash; "
             "and returns early when it finds nothing (line 73). Only then does it call <code>select_option</code> (line 83) and <code>confirm</code> "
             "(line 85), which read the option quotes. No option field, and no index, OI, depth or futures-volume field, can cause or accelerate a "
             "detection. The option response is measured over the SAME 30 s window that the futures move used, ending at the detection bar.</div>")
    o.append("<h2>A/B. Field-by-field usage</h2>")
    o.append(t(["Field", "Consumed?", "Source table.column", "Loaded into", "Used for", "Where (module.function)"], FIELDS))
    o.append("<p><b>Timestamps.</b> Every series is keyed by <code>bar_ts</code> = start of the 5-second receive-time bucket "
             "(<code>hr_capture/bars.py</code>: &ldquo;Bucketing uses receive time&rdquo;). Futures/index use the bucket's last trade; option fields are "
             "&ldquo;the last OBSERVED values as of bucket end&rdquo; (<code>hr_capture/option_state.py</code>). 12A therefore treats a bar's values "
             "as known at <code>bar_ts + 5 s</code>; the HR writer lands them in the DB about 3.3 s later (median), which is why entry is "
             "modelled at the close of bar i+2.</p>")
    o.append("<h2>D. One complete historical candidate, bar by bar</h2>")
    o.append(f"<p>{d_str} {sym}, the first gate-passing Mode A candidate of the session (a 30-second MOMENTUM event). "
             "This is the unit-sized view (config as is); with a real 65-lot it would be blocked by RISK_TOO_LARGE.</p>")
    o.append(t(["Stage", "What happened (exact data / timestamps)"], stage))
    o.append(t(["bar_ts (start)", "known at (close)", "FUT close", "FUT 5-s &Delta;", "ATM CE mid", "ATM PE mid",
                f"selected {key[0]} {c.selection.leg.strike:.0f} bid / ask", "selected mid", "spread", "vol &Delta; (5 s)", "stage"], rows))
    o.append("<div class='finding'>Read the trace from the top. The selected CE started rising from about 15:00:20, from 109.60 up to 112.75, while "
             "the futures were still flat or choppy. The futures impulse (+12.9 points) came only in the 15:00:45 bar, so here the option <b>led the "
             "futures by about 25 seconds</b>. 12A notices only at the detection bar, looks at the option there for the first time, and fills "
             "10 seconds later, after the option has already stopped rising.</div>")
    o.append("<div class='risk'><b>Futures reference caveat (found in Part 2):</b> the futures price 12A reads is the <b>last trade</b>. For SENSEX "
             "there was no futures trade in 84&ndash;95% of 5-second bars, so its last-trade price is stale and moves in jumps. 12A's staleness check "
             "(<code>events.futures_stale</code>) looks at quote updates (<code>update_count</code>), not trades, so it does not detect this. The captured "
             "futures bid/ask (<code>hr_option_transition_state</code>) is live but is not read by 12A.</div>")
    o.append("</body></html>")
    REPORT.write_text("\n".join(o), encoding="utf-8")
    print("audit written", REPORT, "| trace exit", x.reason, round(x.pnl_pct, 3))


if __name__ == "__main__":
    main()
