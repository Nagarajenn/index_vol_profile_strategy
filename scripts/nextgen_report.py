"""HTML renderer for scripts/run_scalp12a_nextgen_research.py (research report only)."""

CSS = ("body{font-family:Georgia,serif;max-width:1260px;margin:0 auto;padding:30px 22px 70px;color:#1c1c1c;background:#fbfaf7;line-height:1.5}"
       "h1{font-size:1.6em;border-bottom:3px solid #2c3e50;padding-bottom:8px}h2{font-size:1.2em;color:#1a3a5c;margin-top:2.2em;border-left:5px solid #2c3e50;padding-left:10px}"
       "h3{font-size:1em;color:#2c3e50}table{border-collapse:collapse;width:100%;margin:10px 0;font-size:0.8em}th,td{border:1px solid #ccc;padding:4px 7px;text-align:left;vertical-align:top}"
       "th{background:#2c3e50;color:#fff}tr:nth-child(even){background:#f2f0ea}code{background:#eee;padding:1px 4px;border-radius:3px}"
       ".risk{background:#ffebee;border-left:4px solid #c62828;padding:10px 14px;margin:14px 0}.finding{background:#e8f0fe;border-left:4px solid #1a3a5c;padding:10px 14px;margin:14px 0}"
       ".callout{background:#fff8e1;border-left:4px solid #f9a825;padding:10px 14px;margin:14px 0}.ok{background:#e8f5e9;border-left:4px solid #2e7d32;padding:10px 14px;margin:14px 0}")


def render(R, cfg, _v, _t, HOLDS, DELAYS, FAMILIES):
    D = R["data"]
    P2 = R["part2"]
    a2 = P2["all current events"]
    cmp_ = R["comparison"]
    o = [f"<!DOCTYPE html><html lang='en'><head><meta charset='UTF-8'><title>12A Next-Generation Scalp Research</title><style>{CSS}</style></head><body>"]
    o.append("<h1>12A &mdash; Next-Generation Scalp Architecture Research<br><span style='font-size:0.6em;font-weight:normal;color:#555'>"
             "Research / shadow only &middot; no live orders &middot; 11D, 12A (hash <code>994667c6d552111e</code>), the shadow recorder and "
             "production behaviour are unchanged</span></h1>")
    o.append(f"<div class='risk'><b>Read this first &mdash; the sample is tiny.</b> HR days: <b>{D['hr_days']}</b> ({', '.join(D['days'])}); "
             f"evaluable with causal thresholds (&ge;2 prior HR days): <b>{len(D['evaluable'])}</b> ({', '.join(D['evaluable'])}), "
             f"i.e. {D['evaluable_symbol_days']} of {D['symbol_days']} symbol-days. Current-12A events: {D['current_events']} ({D['current_strong']} strong); "
             f"12A-EARLY triggers: {D['early_triggers']} (approved: {D['early_approved']}); option observations: {D['option_observations']:,}. "
             f"Expiry symbol-days: {', '.join(D['expiry_symbol_days'])} (evaluable: {', '.join(D['evaluable_expiry']) or 'none'}). "
             "Everything below is <b>descriptive</b>. Nothing is claimed to be profitable, and no threshold was fitted to these two days.</div>")
    o.append("<p>Part 1, the source-level audit of what 12A uses today, is in <code>milestone12a_5sec_usage_audit.html</code>. "
             "Its core finding: 12A detects events from the <b>futures only</b>, and reads option data only <b>after</b> detection.</p>")

    # futures quality
    o.append("<h2>0. A structural data finding: SENSEX futures last-trade price is stale at 5 seconds</h2>")
    o.append(_t(["Date", "Symbol", "5-s bars with no futures trade", "Trades per 5-s bar"],
                [[x["date"], x["symbol"], f"{x['no_trade_bar_pct']:.1f}%", f"{x['trades_per_bar']:.2f}"] for x in R["futures_quality"]]))
    o.append("<div class='risk'>12A's detector reads the futures <b>last-trade</b> price. On SENSEX that price did not change in 84&ndash;95% of "
             "5-second bars, so it moves in jumps between rare prints. 12A's staleness check counts <i>quote</i> updates (about 9 per bar) and "
             "never fires. Current 12A has therefore been detecting SENSEX &ldquo;events&rdquo; on stale jumps, and no SENSEX candidate has passed its gates. "
             "The captured futures <b>bid/ask mid</b> is live (it changes in 88&ndash;95% of SENSEX bars, spread &asymp;0.03&ndash;0.05%). "
             "All research below uses the futures mid; the current-12A replay keeps its own last-trade data, unchanged.</div>")

    # Part 2
    o.append("<h2>2. The current architectural bottleneck (current-12A events, futures-mid reference)</h2>")
    rows = []
    for g, v in P2.items():
        rows.append([g, v["n"], f"{v['onset_to_det_s']['p25']}/{v['onset_to_det_s']['med']}/{v['onset_to_det_s']['p75']}",
                     f"{v['pre_fut']['p25']}/{v['pre_fut']['med']}/{v['pre_fut']['p75']}",
                     f"{v['fut_consumed']['p25']}/{v['fut_consumed']['med']}/{v['fut_consumed']['p75']}",
                     f"{v['pre_opt']['p25']}/{v['pre_opt']['med']}/{v['pre_opt']['p75']}",
                     f"{v['opt_consumed']['p25']}/{v['opt_consumed']['med']}/{v['opt_consumed']['p75']}",
                     f"{v['det_to_entry_opt']['p25']}/{v['det_to_entry_opt']['med']}/{v['det_to_entry_opt']['p75']}",
                     f"{v['consumed_gt_25']}% / {v['consumed_gt_50']}%", f"{v['opt_resp_before_det']}%", f"{v['acc_both_before']}%",
                     f"{v['fade']}%", v["t_fut_peak_after_det"]])
    o.append(_t(["Group", "n", "impulse onset&rarr;detection s (p25/med/p75)", "futures pts before detection", "share of futures move consumed at detection",
                 "option % before detection", "share of option move consumed", "option % detection&rarr;entry", "option consumed &gt;25% / &gt;50%",
                 "option responded BEFORE detector", "futures+option acceleration before detector", "option faded before entry", "futures peak after detection (s, median)"], rows))
    o.append(f"<div class='finding'><b>Answers (all current-12A events).</b> (1) The futures move a median {a2['pre_fut']['med']} points over a median "
             f"{a2['onset_to_det_s']['med']} s before detection, which is {a2['fut_consumed']['med']:.0%} of the eventual favourable move. "
             f"(2) The option moves a median {a2['pre_opt']['med']:+.2f}% before detection. "
             f"(3) Between detection and the current entry (i+2) the option adds a median {a2['det_to_entry_opt']['med']:+.2f}%: nothing is left in that gap. "
             f"(4) Of the profitable opportunities, {P2['profitable (cf>0 or MFE>=2%)']['consumed_gt_25']}% had more than a quarter of the option move "
             f"consumed at detection and {P2['profitable (cf>0 or MFE>=2%)']['consumed_gt_50']}% more than half. "
             f"(5) In <b>{a2['opt_resp_before_det']}%</b> of events the option's first significant response came <b>before</b> the detector triggered. "
             f"(6) {a2['acc_both_before']}% showed futures <i>and</i> option acceleration before the trigger. "
             "(7) The 30-second definition is structurally late relative to the option: the option usually reacts first and the detector confirms "
             "after roughly half the move. But see &sect;3: detecting earlier did not by itself produce better outcomes on these two days.</div>")

    # Part 3/16 comparison
    o.append("<h2>3 &amp; 16. 12A-EARLY research detector vs current 12A vs random</h2>")
    o.append("<p><b>12A-EARLY (research prototype, this script only).</b> It uses synchronized 5-second futures-mid and ATM CE/PE mids. Thresholds are "
             "percentiles of the same symbol's <i>prior</i> HR days; option percentiles use prior <i>non-expiry</i> days where available. "
             "Families: A early momentum (15 s move &ge; p95, 2 of 3 steps agree); B acceleration (5 s move &ge; p95 and larger than the previous step); "
             "C option-leads (synthetic CE&minus;PE 5 s response &ge; p95 while futures quiet &le; p75); D underlying-leads (futures 10 s &ge; p90 in the last "
             "10 s, option now responding &ge; p75); E both-confirm (futures 10 s &ge; p90 and option 10 s &ge; p90); F reversal; G continuation. "
             "60 s cooldown per family. <b>Approval checklist v2</b> (causal): Mode A only, no expiry zone; EARLY = impulse began &le;30 s ago and is "
             "not already a top-5% one-minute move; direction agreement (futures 10 s and CE&minus;PE synthetic agree); option response (leg 10 s &ge; "
             "prior p75); liquidity (spread &le;1%, quote &le;10 s, traded volume); not extended (5-minute move not in the prior top 10%).</p>")
    v1 = R["early_v1"]
    o.append(f"<div class='callout'><b>Research-code correction, disclosed:</b> the first version of the EARLY gate capped the move since onset at "
             "twice the prior median 60-second move. On the stale last-trade reference that cap was below the trigger thresholds themselves, so "
             "nothing could pass. It was replaced on logical grounds, before looking at approved outcomes, by the v2 definition above. On the "
             f"futures-mid reference v1 approves {v1['approved']} triggers and v2 approves {D['early_approved']}. Rejection reasons (v2): "
             + ", ".join(f"{k} {n}" for k, n in sorted(R["early_reject_reasons"].items(), key=lambda kv: -kv[1])) + ".</div>")
    keys = [("n", "n"), ("mean active-exit %", "pnl_mean"), ("median %", "pnl_median"), ("% profitable", "profitable_pct"), ("MFE med %", "mfe"),
            ("MAE med %", "mae"), ("MAE p10 %", "mae_p10"), ("time-to-MFE s", "t_mfe"), ("capture (realised/MFE)", "capture"), ("entry spread %", "spread_in")]
    o.append(_t(["Group (entry = ASK at i+2, BID exits, current 12A exit engine)"] + [k for k, _ in keys],
                [[g] + [_v(v.get(k)) if not isinstance(v.get(k), float) else _v(v.get(k), 3) for _, k in keys] for g, v in cmp_.items()]))
    o.append(f"<p><b>Share of the futures move already consumed at detection</b> (median): " + "; ".join(f"{k} {_v(v)}" for k, v in R["consumed_at_entry"].items())
             + ". The approval confirmations (option response, direction agreement) add lag, so approved triggers are <i>not</i> earlier than current 12A.</p>")
    o.append("<h3>Stability across days (mean active-exit %, n, % profitable)</h3>")
    o.append(_t(["Group"] + sorted({d for v in R["stability"].values() for d in v}),
                [[g] + [f"{_v(v[d]['pnl_mean'], 3)} (n={v[d]['n']}, {_v(v[d]['profitable_pct'])}%)" if d in v else "&ndash;"
                        for d in sorted({d for vv in R["stability"].values() for d in vv})] for g, v in R["stability"].items()]))

    # Part 4
    o.append("<h2>4. Option as a first-class signal: lead / lag classification</h2>")
    o.append("<p>Onset = most adverse point in the 60 s before the trigger; response = first 5 s step &ge; prior p75 after onset. "
             "SYNCHRONIZED: responses within 10 s; OPTION_LEAD / UNDERLYING_LEAD: one responds &gt;10 s earlier; FALSE_OPTION_MOVE: option responded, "
             "futures did not; LAGGING_OPTION: futures responded, option only after the trigger; FADE: the option gave back &ge;50% of its pre-entry "
             "response by the realistic entry. Classes use only pre-trigger data, except LAGGING_OPTION.</p>")
    for g, v in R["part4"].items():
        o.append(f"<h3>{g} (n={v['n']}, faded before entry: {v['fade']})</h3>")
        o.append(_t(["Class", "n", "median active-exit %", "% profitable", "MFE med %", "MAE med %"],
                    [[c, v["counts"][c], _v(x["pnl_median"], 3), _v(x["profitable_pct"]), _v(x["mfe"], 2), _v(x["mae"], 2)]
                     for c, x in sorted(v["outcome"].items(), key=lambda kv: -v["counts"][kv[0]])]))
    o.append("<div class='finding'>Among 12A-EARLY triggers, <b>option-led</b> events had the best median and hit rate, and "
             "<b>underlying-led</b> and <b>false option moves</b> the worst. This is a hypothesis to test on new days, not a rule: two days, and the "
             "classes overlap with time-of-day and symbol.</div>")

    # Part 5
    o.append("<h2>5. Entry timing (earliest realistically observable quote after detection)</h2>")
    o.append("<p>A bar is known at its close and lands in the DB about 3.3 s later. &ldquo;0 s&rdquo; = ASK at close of bar i+1, which needs a "
             "streaming consumer (the current 5 s DB poller cannot guarantee it). &ldquo;5 s&rdquo; = i+2, current 12A. Never the detection bar's own price.</p>")
    rows = []
    for g, v in R["part5"].items():
        for lbl, x in v.items():
            rows.append([g, lbl, x["n"], _v(x["entry_ask"], 2), _v(x["spread_in"], 3), _v(x["mfe"], 2), _v(x["mae"], 2), _v(x["t_mfe"], 0),
                         _v(x["t_mae"], 0), _v(x["pnl_mean"], 3), _v(x["pnl_median"], 3), _v(x["profitable_pct"])])
    o.append(_t(["Group", "Entry", "n", "entry ASK med", "spread %", "MFE %", "MAE %", "t-MFE s", "t-MAE s", "mean %", "median %", "% profitable"], rows))
    o.append("<p>No delay is selected. On these two days the one-bar-earlier fill (streaming) has a better median and hit rate for both current-12A "
             "gate-passing events and 12A-EARLY approved triggers; means are dominated by a few outliers.</p>")

    # Part 6 & 8
    o.append("<h2>6 &amp; 8. Event &ne; trade: separate detection from approval</h2>")
    o.append("<div class='ok'>EVENT (recorded always, with counterfactual) &rarr; CONFIRMATION (direction agreement, strength, acceleration) &rarr; "
             "OPTION RESPONSE (selected leg, 5&ndash;10 s, relative to prior non-expiry distribution) &rarr; LIQUIDITY (spread, freshness, traded volume) "
             "&rarr; EXTENSION (not already a top-decile move, impulse &le;30 s old) &rarr; RISK (lot-feasible within caps, expiry/window) &rarr; TRADE APPROVAL. "
             "A strong event is <b>never</b> sufficient on its own: the research shows strong current-12A events at "
             f"{_v(cmp_['1c. Current 12A - all strong events (ATM)']['profitable_pct'])}% profitable.</div>")

    # Part 7
    o.append("<h2>7. Trade-quality components (no weights): chronological sign stability</h2>")
    o.append("<p>Spearman rank correlation between each component, measured at trigger time, and the active-exit result (5 s entry). "
             "12A-EARLY Mode A triggers, per day. &ldquo;Stable&rdquo; = same sign on both days. n per day shown.</p>")
    o.append(_t(["Component"] + sorted({d for v in R["part7"].values() for d in v["by_day"]}) + ["stable sign"],
                [[k] + [f"{_v(v['by_day'][d][0], 3)} (n={v['by_day'][d][1]})" for d in sorted(v["by_day"])] + [_v(v["stable_sign"])]
                 for k, v in R["part7"].items()]))
    o.append("<p>Same-sign on both days: underlying strength, acceleration, option acceleration, direction agreement, liquidity and time remaining "
             "(positive), and the &ldquo;earlyness&rdquo; score (negative: triggers with <i>more</i> move already made did slightly better). "
             "Option response level, extension and reversal risk flipped sign. With 40&ndash;48 triggers per day these are leads for the next "
             "research iteration, not weights.</p>")

    # Part 9
    o.append("<h2>9. Risk / lot-size forensics</h2>")
    o.append(_t(["Group", "Date", "Time", "Symbol", "Premium", "Lot", "Stop distance (5%)", "Risk / lot", "Capital / lot", "Risk % acct", "Capital % acct"],
                [[r["group"], r["date"], r["time"], r["symbol"], _v(r["premium"], 2), r["lot"], _v(r["stop_dist"], 2), _v(r["risk_lot"], 2),
                  _v(r["cap_lot"], 2), f"{r['risk_pct_acct']}%", f"{r['cap_pct_acct']}%"] for r in R["part9_rows"]]))
    o.append(_t(["Signals", "Max loss", "Max capital", "Trades", "Risk-blocked", "Expectancy &#8377;", "Win %", "Avg win", "Avg loss", "Net &#8377;",
                 "Max DD", "Max consec. losses", "Capture (realised/MFE)", "Risk-adj (mean/sd)", "By day &#8377;"],
                [[s["group"], s["max_loss"], s["max_cap"], s["trades"], s["blocked"], _v(s["expectancy"], 2), _v(s["win_rate"]), _v(s["avg_win"], 2),
                  _v(s["avg_loss"], 2), _v(s["net"], 2), _v(s["max_dd"], 2), s["max_consec_losses"], _v(s["capture"], 3), _v(s["risk_adj"], 3),
                  s["by_day"]] for s in R["part9_scenarios"]]))
    o.append("<div class='finding'>One NIFTY lot (65) at a 12A-type premium needs about half the &#8377;15,000 account and risks &asymp;2.5% of it at a 5% stop. "
             "In every scenario that unlocks trades, expectancy is negative; larger caps scale the losses rather than fixing them. "
             "The sizing question cannot be answered by loosening caps until the signal itself shows positive expectancy. Note: this table uses the "
             "ATM leg for every signal, which is why current 12A shows no trade at &#8377;300 / &#8377;6,000 here (its own ITM/OTM choice fitted once).</div>")

    # Part 10
    p10 = R["part10"]
    o.append("<h2>10. Exit research</h2>")
    o.append(f"<p>Pool: {p10['pool']} simulated entries (current-12A strong events, all 12A-EARLY triggers and random). <b>Good</b> = bid reached "
             f"+2% within 120 s ({p10['good']}); <b>bad</b> = never reached +1% within 120 s ({p10['bad']}).</p>")
    o.append(_t(["Seconds after entry", "good: underwater", "bad: underwater", "good: &le;&minus;1%", "bad: &le;&minus;1%"],
                [[t, f"{v['good_underwater_pct']}%", f"{v['bad_underwater_pct']}%", f"{v['good_below_minus1_pct']}%", f"{v['bad_below_minus1_pct']}%"]
                 for t, v in p10["abandon"].items()]))
    o.append(_t(["Profit level (good trades)", "median seconds to first reach", "p75 seconds"],
                [[f"+{k}%", _v(v["median_s"], 0), _v(v["p75_s"], 0)] for k, v in p10["first_hit"].items()]))
    o.append(_t(["Fixed hold (BID exit)"] + [f"{h} s" for h in HOLDS],
                [["all median %"] + [_v(p10["fixed_all"].get(str(h), p10["fixed_all"].get(h)), 3) for h in HOLDS],
                 ["good median %"] + [_v(p10["fixed_good"].get(str(h), p10["fixed_good"].get(h)), 3) for h in HOLDS],
                 ["bad median %"] + [_v(p10["fixed_bad"].get(str(h), p10["fixed_bad"].get(h)), 3) for h in HOLDS]]))
    o.append("<div class='finding'><b>Fastest point to abandon a bad scalp:</b> around 20&ndash;30 s. By then 85&ndash;86% of bad entries are underwater "
             "against 28&ndash;34% of good ones, and 56&ndash;62% of bad entries are at &minus;1% or worse against 16&ndash;17% of good ones. At 5&ndash;10 s the two groups "
             "are not yet separable. <b>Usable profit arrives quickly when it arrives:</b> good trades reach +0.5% in a median 10 s, +1% in 20 s and +2% in "
             "35 s. Their fixed-hold value peaks at 45&ndash;60 s and decays after. A controlled small profit after about 35&ndash;60 s beats waiting for +5%.</div>")

    # Part 11
    miss = R["part11"]
    from collections import Counter
    cc = Counter(m["cls"] for m in miss)
    o.append("<h2>11. Missed-opportunity analysis (rejected current-12A candidates whose option moved profitably)</h2>")
    o.append("<p>Included when the active-exit counterfactual was positive or the option's MFE reached +2%. The class is assigned in this order: data quality &rarr; "
             "expiry &rarr; window &rarr; risk &rarr; option-not-responding (sole) &rarr; false opportunity (the scalp would not have captured it: active exit "
             "&le;0, or the stop came before the peak) &rarr; move too small &rarr; late &rarr; good missed trade. &ldquo;Early trigger&rdquo; = a 12A-EARLY trigger in the "
             "same symbol and direction up to 60 s before, i.e. information that was available at the time.</p>")
    o.append("<p><b>Counts:</b> " + ", ".join(f"{k} {n}" for k, n in cc.most_common()) +
             f". An earlier 12A-EARLY trigger existed for {sum(1 for m in miss if m['early_trigger'] != 'none')} of {len(miss)}; "
             f"{sum(m['early_approved'] for m in miss)} of those were approved by the v2 checklist.</p>")
    o.append(_t(["Date", "Time", "Symbol", "Dir", "Mode", "First reason", "Class", "Active-exit %", "MFE %", "MAE %", "t-MFE", "t-MAE", "Timing",
                 "Earlier 12A-EARLY trigger", "Approved"],
                [[m["date"], m["time"], m["symbol"], m["dir"], m["mode"], m["first_reason"], m["cls"], _v(m["cf_pnl"], 2), _v(m["mfe"], 2),
                  _v(m["mae"], 2), _v(m["t_mfe"], 0), _v(m["t_mae"], 0), m["timing"], m["early_trigger"], _v(m["early_approved"])] for m in miss]))

    # Part 12
    o.append("<h2>12. Time windows &times; event class (12A-EARLY triggers)</h2>")
    o.append(_t(["Window | class", "n", "median active-exit %", "% profitable", "MFE %", "MAE %"],
                [[k, v["n"], _v(v["pnl_median"], 3), _v(v["profitable_pct"]), _v(v["mfe"], 2), _v(v["mae"], 2)] for k, v in R["part12"].items()]))
    o.append("<p>NOISE is an outcome label (no follow-through), shown so the classes add up. It is not a predictor. Cells hold 1&ndash;25 triggers, and "
             "windows are <b>not ranked</b>. The strategy should stay event-driven.</p>")

    # Part 13
    o.append("<h2>13. Expiry vs normal days (random ATM entries on all 4 HR days, same exit engine)</h2>")
    o.append(_t(["Day type | window", "entries", "symbol-days", "MAE med %", "MAE p10 %", "MFE med %", "60 s hold %", "120 s hold %", "spread %"],
                [[k, v["n"], v["symbol_days"], _v(v["mae"], 2), _v(v["mae_p10"], 2), _v(v["mfe"], 2), _v(v["fixed60"], 3), _v(v["fixed120"], 3),
                  _v(v["spread"], 3)] for k, v in R["part13"].items()]))
    o.append("<div class='risk'>On the two expiry symbol-days the option regime differs from <b>15:00</b>, not only from 15:10. The median 5-minute MAE "
             "is &asymp;&minus;10% at 15:00&ndash;15:10, &asymp;&minus;19% at 15:10&ndash;15:15 and &asymp;&minus;66% after 15:15, against &asymp;&minus;3% on normal days in every window. "
             "The existing expiry restrictions stay, and the evidence would, if anything, argue for stricter ones. Two expiry symbol-days are far too few to decide.</div>")

    # Part 14
    o.append("<h2>14. NIFTY vs SENSEX (never combined)</h2>")
    o.append(_t(["Symbol | group", "n", "mean active-exit %", "% profitable", "MAE med %"],
                [[f"{sym} | {g}", x["n"], _v(x["pnl_mean"], 3), _v(x["profitable_pct"]), _v(x["mae"], 2)] for sym, v in R["part14"].items() for g, x in v.items()]))
    o.append("<p>SENSEX needs the futures-mid reference (&sect;0) before any SENSEX conclusion means anything; its option premiums (lot 20) are also "
             "lot-feasible far more often than NIFTY's (lot 65). All measurements above are normalized (percent of premium, percentiles), with no "
             "symbol-specific strike rules.</p>")

    # Part 15
    o.append("<h2>15. WHAT SHOULD THE TRADER ACTUALLY DO? (proposed research decision flow, not a live rule)</h2>")
    steps = [
        ("1. DETECT", "Futures bid/ask mid and ATM CE/PE mids for the latest closed 5-s bar (bars &le; i), plus prior-day distributions.",
         "A 5&ndash;15 s futures impulse (&ge; prior p90&ndash;p95), or an option synthetic (CE&minus;PE) impulse with futures quiet. Record every event.",
         "Nothing unusual (no event); futures last-trade for SENSEX (stale).", "Future bars; same-day percentiles; hindsight labels (NOISE, early/late).",
         "&mdash;", "Event is information only; no exposure."),
        ("2. CONFIRM", "Same bar: futures 10 s, CE&minus;PE 10 s synthetic, selected leg 10 s, acceleration.",
         "Futures and option agree in direction; the move is accelerating or strong (prior p75+); the impulse is &le;30 s old and not a top-5% minute already.",
         "Disagreement; option not responding (&lt; prior p75); impulse &gt;30 s old or extended.", "The option's move after the trigger.", "&mdash;", "Rejected events keep their counterfactual."),
        ("3. SELECT", "Quotes of ATM&plusmn;2 at bar i.", "Direction-matched CE/PE, ITM&le;2 / OTM&le;1, spread &le;1%, quote &le;10 s old, traded volume in the last 15 s.",
         "Wide spread, stale quote, no volume.", "Cheapest-premium preference; future spreads.", "&mdash;", "Liquidity checked before risk."),
        ("4. SIZE", "Decision-bar ASK, exchange lot size, account policy.", "At least 1 whole lot fits the per-trade loss cap at the stop and the capital cap.",
         "Even 1 lot breaches either cap (RISK_TOO_LARGE). Do not shrink the stop to make it fit.", "Outcome of the trade.", "&mdash;",
         "Rupee risk fixed before entry. Current caps block most NIFTY signals; the policy is open (&sect;9)."),
        ("5. ENTER", "The first quote formed after the trigger could be observed.",
         "Buy at the ASK of bar i+1 if the system can act on streaming data, otherwise i+2. Re-check spread &le;1%.",
         "Quote missing or spread widened; window or expiry zone reached.", "The detection bar's own price as a fill.", "&mdash;", "ASK in, BID out, always."),
        ("6. MONITOR", "Each new 5-s bar: BID, spread, futures mid.",
         "By 20&ndash;30 s the trade should be above entry. Good scalps reach +0.5% in ~10 s, +1% in ~20 s and +2% in ~35 s.",
         "Underwater at 20&ndash;30 s, or &le;&minus;1%; futures back through the event origin; spread blows out; futures/option divergence.",
         "Anything not yet printed.", "15&ndash;60 s", "Stop only tightens; stale data forces an exit."),
        ("7. EXIT", "BID and momentum of the premium.",
         "Take a controlled profit when +1&ndash;2% is reached and the premium stops accelerating; hard time limit about 60 s.",
         "Momentum failure, give-back of half the peak, no progress, time limit, expiry/session limits.", "&mdash;", "Median useful horizon 35&ndash;60 s",
         "Never wait for a large target; value decays after 60 s."),
        ("8. NO TRADE", "Any failed check above.", "&mdash;",
         "Mode B (research only); expiry day, especially from 15:10 (and plausibly from 15:00); SENSEX until the futures reference is fixed; "
         "insufficient history; data quality.", "&mdash;", "&mdash;", "Every NO TRADE keeps its reason and counterfactual."),
    ]
    o.append(_t(["Step", "Information available at that moment", "Required", "Rejects", "Must NOT be used", "Horizon", "Risk control"], [list(s) for s in steps]))

    # Part 17
    o.append("<h2>17. Data requirement</h2>")
    o.append(_t(["Item", "Now", "Needed for a first chronological validation"],
                [["HR days captured", D["hr_days"], "&ge;22 (the first 2 only seed thresholds, leaving &ge;20 evaluable)"],
                 ["Evaluable symbol-days", D["evaluable_symbol_days"], "&ge;40"],
                 ["Expiry symbol-days", len(D["expiry_symbol_days"]), "&ge;6 per symbol before any expiry rule is relaxed (about 6 weekly expiries)"],
                 ["Current-12A events", D["current_events"], "grows about 30 per day"],
                 ["12A-EARLY triggers", D["early_triggers"], "grows about 90 per day"],
                 ["Option observations", f"{D['option_observations']:,}", "&asymp;18,500 per day"]]))
    o.append("<p>At one HR day per trading day, 18 more trading days (to about mid-October 2026) reach the first chronological split. The live 12A shadow "
             "recorder keeps running unchanged, so the dataset grows.</p>")

    # Part 18
    o.append("<h2>18. Implementation decision</h2>")
    o.append("<div class='ok'><b>Choice: C &mdash; BUILD 12A-EARLY AS A SEPARATE RESEARCH (SHADOW) VERSION.</b> Not implemented; awaiting instruction.<br><br>"
             "<b>Why not A (keep current 12A only):</b> current 12A has two structural problems, not threshold problems. It reads the stale SENSEX "
             "last-trade price, and it ignores option data until after detection, although the option responds first in most events. Keeping only "
             "12A leaves both unanswered.<br><b>Why not B (modify 12A):</b> 12A's live shadow record is the baseline, and changing it would break "
             "continuity. There is also no evidence yet that any alternative performs better: 12A-EARLY-approved results are negative and "
             "indistinguishable from random on two days. Current 12A therefore stays unchanged as the control.<br>"
             "<b>Why C:</b> the architectural fixes (futures mid, option-first detection, event/approval separation, expiry-conditioned thresholds, "
             "streaming entry, a 20&ndash;30 s abandon and 35&ndash;60 s profit exit, lot-aware sizing) can only be judged on new days collected in parallel.</div>")
    o.append(_t(["Proposed file (new unless stated)", "Purpose"], [
        ["<code>scalp_12a_early/config.py</code>", "Own version <code>12A-EARLY-v1</code> and config hash; every parameter labelled with its evidence status"],
        ["<code>scalp_12a_early/reference.py</code>", "Futures bid/ask mid from <code>hr_option_transition_state</code>, with last-trade staleness diagnostics"],
        ["<code>scalp_12a_early/distributions.py</code>", "Causal prior-day percentiles, expiry-conditioned for options"],
        ["<code>scalp_12a_early/triggers.py</code>", "Families A&ndash;G at 5&ndash;15 s"],
        ["<code>scalp_12a_early/anatomy.py</code>", "Option/futures onset, lead/lag class, fade (pre-trigger data only for decisions)"],
        ["<code>scalp_12a_early/approval.py</code>", "Event &rarr; confirmation &rarr; option response &rarr; liquidity &rarr; extension &rarr; risk &rarr; approval, all reasons recorded"],
        ["<code>scalp_12a_early/sizing.py</code>", "Exchange-lot sizing from instrument data; RISK_TOO_LARGE when 1 lot breaches caps"],
        ["<code>scalp_12a_early/exits.py</code>", "Abandon at 20&ndash;30 s if underwater, profit-take on momentum fade, max hold about 60 s, stop tighten-only"],
        ["<code>scalp_12a_early/engine.py</code>, <code>db.py</code>, <code>schema.sql</code>", "Replay/shadow engine; own tables <code>scalp12a_early_*</code>; own connection"],
        ["<code>scripts/run_scalp12a_early_shadow.py</code> + scheduled task", "Parallel shadow beside 12A (observation only)"],
        ["<code>tests/test_scalp12a_early_*.py</code>", "Causality/truncation, approval, sizing, exits; isolation pins for 11D, 12A (hash) and HR"],
        ["No existing file modified", "12A, the 12A shadow recorder, HR capture, 11D and the pipeline are untouched"]]))
    o.append("<footer style='margin-top:40px;color:#666;font-size:0.85em'>Generated by scripts/run_scalp12a_nextgen_research.py &middot; machine-readable "
             "outputs in milestone12a_nextgen_research/ &middot; read-only; no DB writes; current 12A config hash 994667c6d552111e unchanged</footer></body></html>")
    return "\n".join(o)
