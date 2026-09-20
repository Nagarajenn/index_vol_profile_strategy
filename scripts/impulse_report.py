"""HTML renderer for scripts/run_scalp12a_impulse_research.py -- answers only the 7 gate questions."""

CSS = ("body{font-family:Georgia,serif;max-width:1240px;margin:0 auto;padding:30px 22px 70px;color:#1c1c1c;background:#fbfaf7;line-height:1.5}"
       "h1{font-size:1.6em;border-bottom:3px solid #2c3e50;padding-bottom:8px}h2{font-size:1.2em;color:#1a3a5c;margin-top:2.2em;border-left:5px solid #2c3e50;padding-left:10px}"
       "h3{font-size:1em;color:#2c3e50}table{border-collapse:collapse;width:100%;margin:10px 0;font-size:0.8em}th,td{border:1px solid #ccc;padding:4px 7px;text-align:left;vertical-align:top}"
       "th{background:#2c3e50;color:#fff}tr:nth-child(even){background:#f2f0ea}code{background:#eee;padding:1px 4px;border-radius:3px}"
       ".ans{background:#e8f0fe;border-left:4px solid #1a3a5c;padding:10px 14px;margin:14px 0}.risk{background:#ffebee;border-left:4px solid #c62828;padding:10px 14px;margin:14px 0}"
       ".ok{background:#e8f5e9;border-left:4px solid #2e7d32;padding:10px 14px;margin:14px 0}")


def v(x, nd=2):
    if x is None:
        return "&ndash;"
    if isinstance(x, bool):
        return "Yes" if x else "No"
    if isinstance(x, float):
        return f"{x:,.{nd}f}"
    return str(x)


def t(h, rows):
    return "<table><tr>" + "".join(f"<th>{x}</th>" for x in h) + "</tr>" + "".join(
        "<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows) + "</table>"


STAT_H = ["n", "median active-exit %", "mean %", "% profitable", "+1% before &minus;1% (60 s)", "MFE %", "MAE %", "t +0.5% s", "t +1% s",
          "t +2% s", "t MAE s", "entry spread %", "futures move remaining at entry", "option move consumed at entry"]


def srow(label, s):
    return [label] + [v(s.get(k), 3) if isinstance(s.get(k), float) else v(s.get(k)) for k in
                      ("n", "pnl", "pnl_mean", "profitable", "hit1first", "mfe", "mae", "t05", "t1", "t2", "tmae", "spread", "remain", "optcons")]


def render(R):
    H, C = R["headline"], R["counts"]
    o = [f"<!DOCTYPE html><html lang='en'><head><meta charset='UTF-8'><title>12A Impulse Research Gate</title><style>{CSS}</style></head><body>"]
    o.append("<h1>12A &mdash; Impulse Research Gate<br><span style='font-size:0.6em;font-weight:normal;color:#555'>Research only &middot; nothing "
             "implemented &middot; 11D, 12A (hash <code>994667c6d552111e</code>), the 12A shadow recorder and HR capture unchanged</span></h1>")
    o.append(f"<div class='risk'><b>Sample-size rule applies.</b> HR days {len(R['days'])} ({', '.join(R['days'])}); evaluable with causal thresholds "
             f"{len(R['evaluable'])} ({', '.join(R['evaluable'])}) = 4 symbol-days, one of them an expiry symbol-day (SENSEX 09-17). "
             f"Impulses recorded: 10-s detector {C['10s']['all']} ({C['10s']['modeA']} in Mode A), 5-s detector {C['5s']['all']} ({C['5s']['modeA']}); "
             f"current-12A strong events {C['CURRENT_12A']['all']}; random entries {C['RANDOM']['all']}. <b>No trading-rule conclusion is drawn, "
             "and no parameter was chosen because it did well on 09-17 or 09-18.</b> Every figure is descriptive.</div>")
    o.append("<p><b>Method in one paragraph.</b> Reference = futures bid/ask <b>mid</b> for both symbols. Thresholds for day D are percentiles of "
             "earlier HR days only: futures from all prior days, options from prior non-expiry days. An <b>impulse</b> is recorded whenever the 10-second "
             "futures-mid move or the 10-second CE&minus;PE mid response reaches its prior p90 (a 5-second variant uses p95), with a 60-second cooldown "
             "per direction. Every impulse is recorded; approval is a separate step allowed up to 10 s after detection. Lead/lag classes use only "
             "bars up to the trigger. Entry is the ASK at i+1 (streaming) or i+2 (the current 5-second poller). Exits are on the BID, with the "
             "current 12A exit engine unless stated. &ldquo;+1% before &minus;1%&rdquo; is a scalp-relevant outcome label, never an input.</p>")

    # Q1
    o.append("<h2>1. Is 5-second option movement actually leading useful futures moves?</h2>")
    for scope in ("Mode A | both", "Mode A | NIFTY", "Mode A | SENSEX"):
        o.append(f"<h3>{scope} (10-s impulses, entry i+2)</h3>")
        o.append(t(["Class"] + STAT_H, [srow(k, s) for k, s in R["classes"][scope].items() if s["n"]]))
    o.append("<h3>Stability by day (Mode A, both symbols): n / median % / +1% before &minus;1%</h3>")
    o.append(t(["Class"] + R["evaluable"], [[c] + [f"{R['classes_by_day'][d][c]['n']} / {v(R['classes_by_day'][d][c]['pnl'], 3)} / {v(R['classes_by_day'][d][c]['hit1first'])}%"
                                                   for d in R["evaluable"]] for c in ("OPTION_LEAD", "UNDERLYING_LEAD", "SYNCHRONIZED", "FALSE_OPTION_MOVE", "OPTION_RESPONSE_LAG")]))
    rnd = H["random"]
    o.append(f"<div class='ans'><b>Answer: not on this evidence.</b> Option-led impulses were {v(H['option_lead']['profitable'])}% profitable, and "
             f"{v(H['option_lead']['hit1first'])}% reached +1% before &minus;1%. That is no better than synchronized impulses ({v(H['sync']['profitable'])}% / "
             f"{v(H['sync']['hit1first'])}%) or random Mode A entries ({v(rnd['profitable'])}% / {v(rnd['hit1first'])}%). The favourable result for option-led "
             "triggers in the previous iteration does <b>not</b> replicate under this cleaner definition. It is negative on both days and splits by symbol "
             "(SENSEX 4 cases good, NIFTY 7 cases poor). The option does often move first, but in these two days that did not make the impulse more "
             "useful. False option moves (option up, no futures confirmation; 21 cases) were among the weakest classes.</div>")

    # Q2
    o.append("<h2>2. Can the system detect the impulse earlier without destroying precision?</h2>")
    rows = []
    for k, s in R["variants"].items():
        if s["n"]:
            rows.append(srow(k, s) + [v(s.get("onset_age"))])
    o.append(t(["Detector | day type | symbol"] + STAT_H + ["onset&rarr;detection s"], rows))
    o.append(f"<div class='ans'><b>Answer: earlier yes, precise no.</b> The 10-s detector fires a median {v(R['variants']['10s | normal | NIFTY']['onset_age'])} s "
             f"after the impulse starts (NIFTY, normal days) against {v(R['variants']['CURRENT_12A | normal | NIFTY']['onset_age'])} s for current 12A. "
             f"Its precision (+1% before &minus;1%) is {v(H['imp10']['hit1first'])}% in Mode A, and the 5-s variant's is {v(H['imp5']['hit1first'])}%. "
             f"Both sit at the random baseline of {v(rnd['hit1first'])}%. Current 12A was {v(H['cur']['hit1first'])}% on 11 events. So detecting earlier did not "
             "destroy precision, but only because there was none to lose: no detector separated useful impulses from random entries.</div>")

    # Q3
    o.append("<h2>3. Does early detection improve move remaining at entry?</h2>")
    ap = R["approval"]
    o.append(t(["Detector (approved, Mode A)", "approved / impulses", "event start&rarr;detection s", "confirmation delay s", "event start&rarr;entry i+1 / i+2 s",
                "futures move remaining at i+1 / i+2", "option move consumed at i+1 / i+2", "rejections", "by symbol", "by day"],
               [[k, f"{a['approved']} / {a['n_modeA']}", v(a["onset_to_detect"]), v(a["confirm_delay"]),
                 f"{v(a['onset_to_entry1'])} / {v(a['onset_to_entry2'])}", f"{v(a['fut_remaining1'])} / {v(a['fut_remaining2'])}",
                 f"{v(a['opt_consumed1'])} / {v(a['opt_consumed2'])}", a["rejections"], a["by_symbol"], a["by_day"]] for k, a in ap.items()]))
    o.append(f"<div class='ans'><b>Answer: modestly, not decisively.</b> 10-s impulses leave a median {v(R['variants']['10s | normal | NIFTY']['remain'])} of "
             f"the futures move ahead at entry (NIFTY, normal days), against {v(R['variants']['CURRENT_12A | normal | NIFTY']['remain'])} for current 12A. "
             f"Random entries leave {v(R['variants']['RANDOM | normal | NIFTY']['remain'])}, because they are not placed after moves. Approval did not add delay: "
             f"confirmation passed on the detection bar itself (median {v(ap['10s']['confirm_delay'])} s), and entry comes "
             f"{v(ap['10s']['onset_to_entry1'])}&ndash;{v(ap['10s']['onset_to_entry2'])} s after the impulse began. Even so, about half of the option "
             "move is already spent at entry: the option re-prices faster than any 5-second observer can act.</div>")

    # Q4
    o.append("<h2>4. What happens to MAE?</h2>")
    o.append(t(["Scope (10-s impulses, Mode A)"] + STAT_H, [srow(k, s) for k, s in R["expiry"].items()]))
    o.append(f"<div class='ans'><b>Answer: early detection does not reduce MAE.</b> On normal days 10-s impulses have a median MAE of "
             f"{v(R['variants']['10s | normal | NIFTY']['mae'])}% (NIFTY), about the same as random entries ({v(R['variants']['RANDOM | normal | NIFTY']['mae'])}%). "
             f"Current 12A's smaller MAE ({v(R['variants']['CURRENT_12A | normal | NIFTY']['mae'])}%) rests on 9 events. On the expiry symbol-day the median MAE "
             f"was {v(R['expiry']['EXPIRY']['mae'])}%, in 15:00&ndash;15:10, a window where approval is still allowed. The expiry restrictions stay unchanged, and this is "
             "one expiry symbol-day, far too few to act on.</div>")

    # Q5
    ex = R["exits"]
    o.append("<h2>5. What happens within the first 20&ndash;60 seconds after entry?</h2>")
    o.append(f"<p>Pool: 10-s impulses, Mode A, normal days, entry i+2 (n={ex['pool']}). <b>Good</b> = bid reached +1% within 60 s ({ex['good']}); "
             f"<b>bad</b> = never reached +0.5% within 60 s ({ex['bad']}).</p>")
    o.append(t(["Seconds after entry", "good underwater", "bad underwater", "good &le;&minus;0.5%", "bad &le;&minus;0.5%", "good median %", "bad median %"],
               [[k, f"{s['good_underwater']}%", f"{s['bad_underwater']}%", f"{s['good_le_m05']}%", f"{s['bad_le_m05']}%", v(s["good_med"], 3), v(s["bad_med"], 3)]
                for k, s in ex["separation"].items()]))
    u = ex["usable"]
    o.append(f"<p><b>Usable profit (good entries):</b> +0.5% in a median {v(u['t05'])} s, +1% in {v(u['t1'])} s, +1.5% in {v(u['t15'])} s and +2% in "
             f"{v(u['t2'])} s. Only {v(u['reach2'])}% of good entries reached +2% within 60 s.</p>")
    o.append(t(["Exit rule (fixed a priori, not optimised)", "n", "mean %", "median %", "% profitable", "median hold s", "median give-back %", "mean by day"],
               [[k, s["n"], v(s["mean"], 3), v(s["median"], 3), v(s["profitable"]), v(s["hold"]), v(s["giveback"], 3), s["by_day"]] for k, s in ex["rules"].items()]))
    o.append("<div class='ans'><b>Answer.</b> Bad and good scalps become distinguishable at about <b>15 s</b>: 92% of bad entries are underwater "
             "against 21% of good ones, and 69% of bad ones are already at &minus;0.5%. Good scalps produce their usable profit fast: +1% in a median "
             "20 s. +2% is rare within a minute. Exits that act on that evidence (a two-bar momentum failure, or a combined no-progress-at-20 s / "
             "&minus;1% / half-give-back rule) lose less than fixed holds or the current 12A exit engine. <b>Every rule is still negative on both "
             "days</b>: exits reduce the damage but do not create an edge. No +5% or +2% target is assumed anywhere.</div>")

    # Q6
    o.append("<h2>6. Is there evidence for a short-duration scalp architecture?</h2>")
    o.append(t(["Dimension (value at trigger)", "Spearman day 1 (n)", "Spearman day 2 (n)", "same sign", "out-of-sample: day-2 mean % top / bottom tercile (day-1 cuts)",
                "OOS +1% first: top / bottom", "consistent OOS"],
               [[k, f"{v(s['rho_day1'][0], 3)} ({s['rho_day1'][1]})", f"{v(s['rho_day2'][0], 3)} ({s['rho_day2'][1]})", v(s["stable"]),
                 (f"{v(s['oos']['top_mean'], 3)} (n={s['oos']['n_top']}) / {v(s['oos']['bottom_mean'], 3)} (n={s['oos']['n_bottom']})" if s["oos"] else "&ndash;"),
                 (f"{v(s['oos']['top_hit1'])}% / {v(s['oos']['bottom_hit1'])}%" if s["oos"] else "&ndash;"), v(s["oos_consistent"])]
                for k, s in R["dims"].items()]))
    o.append("<div class='ans'><b>Answer: evidence for the <i>shape</i> of a scalp, not for its <i>edge</i>.</b> The time structure supports a "
             "short-duration design. Impulses can be caught about 20 s after they start rather than 55 s; outcomes separate by about 15 s; "
             "usable profit, when it comes, arrives in about 20 s. What is missing is selection: no detector, lead/lag class or exit rule beat random "
             "entries, and every exit rule lost money on both days. Of the nine impulse dimensions, only option acceleration and liquidity kept the "
             "same sign on both days <i>and</i> ranked day 2 in the direction day 1 suggested. Those tercile tests rest on 2&ndash;10 trades per bucket. "
             "Nothing here supports a trading rule.</div>")

    # Q7
    o.append("<h2>7. What additional data is required?</h2>")
    ref = R["reference"]
    o.append("<h3>Reference verification (Part 1): futures last-trade vs bid/ask mid</h3>")
    o.append(t(["Date", "Symbol", "bars", "quote updates / bar", "trades / bar", "bars without trade", "mid moved (bars)", "last-trade longest stale s",
                "last-trade stale runs &ge;30 s", "mid longest stale s", "mid stale runs &ge;30 s", "HR FROZEN bars", "write latency mean / max s",
                "exchange trade time lag median / p95 s"],
               [[r["date"], r["symbol"], r["bars"], r["quote_updates_per_bar"], r["trades_per_bar"], f"{r['no_trade_bar_pct']}%", f"{r['mid_moved_pct']}%",
                 r["last_trade_longest_stale_s"], r["last_trade_stale_runs_30s"], r["mid_longest_stale_s"], r["mid_stale_runs_30s"], r["frozen_status_bars"],
                 f"{r['write_latency_mean_s']} / {r['write_latency_max_s']}", f"{r['ltt_lag_median_s']} / {r['ltt_lag_p95_s']}"] for r in ref]))
    o.append("<p><b>Same reference live and in replay:</b> 12A's live shadow and replay both read <code>hr_ohlc_5s</code> FUTIDX close (last trade) through "
             "<code>scalp_12a.db.load_session</code>. That is consistent, but stale for SENSEX. The research mid comes from "
             "<code>hr_option_transition_state</code>, written in the same flush as the option bars (mean latency 8.3 s, max 11.3 s) with one row per "
             "5-s bar. A live reader and a replay would therefore see identical values. The SENSEX exchange trade time trails receipt by a median "
             "22&ndash;66 s, confirming that its last-trade price is not a 5-s signal.</p>")
    tr = R["trace"]
    o.append("<h3>Data path (Part 2): raw ticks &rarr; 5-s bar for 2026-09-17 NIFTY CE 23300 and futures, 15:00:15&ndash;15:01:15</h3>")
    o.append(t(["instrument", "5-s bucket (receive time)", "ticks", "first receive", "last receive", "first exchange ts", "last exchange ts", "min bid", "max ask", "min LTP", "max LTP"], tr["ticks"]))
    o.append(t(["CE 23300 bar_ts", "bid", "ask", "mid", "updates", "written to DB after bar start (s)"], tr["bars"]))
    o.append("<p>Each 5-s option bar aggregates about 5&ndash;7 packets and reaches the DB 7.7&ndash;9.6 s after the bar starts. The CE's quotes climbed "
             "steadily from 15:00:20; the futures jump came in the 15:00:45 bucket. That impulse is what the detectors in &sect;1&ndash;2 classify.</p>")
    o.append(t(["Requirement", "Now", "Target"],
               [["HR days", len(R["days"]), "&ge;22 (the first 2 only seed thresholds)"],
                ["Evaluable symbol-days", 2 * len(R["evaluable"]), "&ge;40 before the first chronological validation"],
                ["Mode A 10-s impulses", C["10s"]["modeA"], "&asymp;16 per symbol-day now &rarr; &asymp;640 at 40 symbol-days"],
                ["Per lead/lag class", "4&ndash;27", "&ge;50 per class per symbol for a stable comparison (option-led &asymp;17% of impulses &rarr; about 150&ndash;300 symbol-days per symbol for a narrow CI; 40 gives a first read)"],
                ["Expiry symbol-days", 2, "&ge;6 per symbol before any expiry question is reopened (restrictions stay unchanged)"],
                ["New capture fields", "none required", "HR already records futures bid/ask, option bid/ask/volume/OI/depth and raw ticks"]]))
    o.append("<div class='ans'><b>Answer:</b> more days, not new data types. The HR capture already records everything this research needs, including "
             "the futures mid. The binding constraint is sample size: 18 more trading days to reach 22 HR days and 40 evaluable symbol-days (about "
             "mid-October 2026), and several more weeks for expiry. This impulse research can then be re-run offline, unchanged, on genuinely unseen "
             "days.</div>")

    o.append("<h2>Decision</h2>")
    o.append("<div class='ok'><b>KEEP CURRENT 12A.</b><br>"
             "&bull; There is no evidence that an impulse-based design selects better than random. Building a separate 12A-IMPULSE engine now would "
             "add a system without a signal.<br>"
             "&bull; Nothing needs to be built to gather the missing evidence: HR capture already stores every input, and live vs replay latency is "
             "measured (&asymp;8.3 s) and identical. This research script re-runs offline, unchanged, once &ge;22 HR days / &ge;40 evaluable symbol-days "
             "exist, and that is the first genuinely out-of-sample test.<br>"
             "&bull; Current 12A continues unchanged in shadow as the control. Its known limitation (SENSEX last-trade reference) is documented, "
             "not fixed, because fixing it would modify 12A.<br>"
             "&bull; If the re-run on unseen days shows an impulse class or dimension beating random with stable signs, that is the point to propose "
             "BUILD SEPARATE 12A-IMPULSE RESEARCH, using the architecture already outlined in the next-generation report.</div>")
    o.append("<footer style='margin-top:40px;color:#666;font-size:0.85em'>Generated by scripts/run_scalp12a_impulse_research.py &middot; data in "
             "milestone12a_impulse_research/ &middot; read-only, no DB writes &middot; 12A hash 994667c6d552111e unchanged</footer></body></html>")
    return "\n".join(o)
