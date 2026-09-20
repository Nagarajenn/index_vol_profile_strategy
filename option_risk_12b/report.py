"""HTML report for 12B-option-risk-v1. Research language only; every number comes from the run."""

import json
from pathlib import Path

CSS = ("body{font-family:Georgia,serif;max-width:1240px;margin:0 auto;padding:30px 22px 70px;color:#1c1c1c;background:#fbfaf7;line-height:1.5}"
       "h1{font-size:1.6em;border-bottom:3px solid #2c3e50;padding-bottom:8px}h2{font-size:1.2em;color:#1a3a5c;margin-top:2.2em;border-left:5px solid #2c3e50;padding-left:10px}"
       "h3{font-size:1em;color:#2c3e50}table{border-collapse:collapse;width:100%;margin:10px 0;font-size:0.8em}th,td{border:1px solid #ccc;padding:4px 7px;text-align:left;vertical-align:top}"
       "th{background:#2c3e50;color:#fff}tr:nth-child(even){background:#f2f0ea}code{background:#eee;padding:1px 4px;border-radius:3px}"
       ".ans{background:#e8f0fe;border-left:4px solid #1a3a5c;padding:10px 14px;margin:14px 0}.risk{background:#ffebee;border-left:4px solid #c62828;padding:10px 14px;margin:14px 0}"
       ".ok{background:#e8f5e9;border-left:4px solid #2e7d32;padding:10px 14px;margin:14px 0}")


def v(x, nd=1):
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


def _hit_rows(H, keys):
    rows = []
    for k in keys:
        x = H.get(k)
        if not x:
            continue
        rows.append([k.replace("|", " &middot; "), x["n"], x["hits"], v(x["hit_rate"]), v(x.get("majority_baseline_pct")),
                     v(x["binomial_p_vs_50"], 3), v(x.get("binomial_p_vs_majority"), 3), v(x["median_signal"], 2),
                     v(x["median_abs_print_move"], 1), x["excluded_flat_print"]])
    return rows


def _act_rows(ba):
    return [[k, x["n"], v(x["median_max_adverse_pct"], 2), v(x["median_max_favourable_pct"], 2), v(x["median_end_ret_pct"], 2),
             v(x["pct_minus1_before_plus1"]), v(x["median_t_max_adverse_min"]), v(x["median_t_max_favourable_min"])]
            for k, x in ba.items()]


def render(S, L, audit, np_rows, sig_rows, events, ws_all, ws_by, cfg) -> str:
    NP, H, M = S["next_print"], S["next_print"]["hit_tables"], S["next_print"]["magnitude"]
    RP = S["reference_positions"]
    WA = RP["warning_study_all"]
    ev = S["event_study"]
    st = S["underlying_stale_symbol_days"]
    stale_days = st.get("NIFTY|STALE", 0) + st.get("SENSEX|STALE", 0)
    all_days = sum(st.values())
    ms = S["underlying_minute_states"]
    non_live = sum(n for k, n in ms.items() if not k.endswith("|LIVE"))
    tot_min = sum(ms.values())
    act = S["options_activity_while_underlying_not_live"]
    act_active = sum(n for k, n in act.items() if k.endswith("|ACTIVE"))
    act_tot = sum(act.values())
    v0p = Path(__file__).resolve().parent.parent / "data/cache/option_risk_12b/v0_flat_count_summary.json"
    v0 = json.loads(v0p.read_text()) if v0p.exists() else None
    o = [f"<!DOCTYPE html><html lang='en'><head><meta charset='UTF-8'><title>12B Option Risk &amp; Closing State</title><style>{CSS}</style></head><body>"]
    o.append("<h1>Milestone 12B &mdash; Option Chain Risk &amp; Closing-State Intelligence<br><span style='font-size:0.6em;font-weight:normal;color:#555'>"
             f"Version <code>{S['version']}</code> &middot; config hash <code>{S['config_hash']}</code> &middot; run <code>{S['run_id']}</code> &middot; "
             "advisory / research only &middot; 11D (hash <code>9c7c362d7e0c6a14</code>) and 12A (hash <code>994667c6d552111e</code>) unchanged</span></h1>")
    o.append("<div class='risk'><b>Read this first.</b> This milestone adds a way to <i>see</i> the option chain while the index print is stale, and an "
             "<i>advisory</i> risk monitor. It does not place, modify or cancel orders, does not open or close paper positions, and does not change any 11D "
             "or 12A decision. 11D has <b>no historical paper positions</b> (paper_positions is empty), so the position-risk study uses clearly labelled "
             "<b>hypothetical reference positions</b> (ATM BUY CE and ATM BUY PE). Every threshold is a RESEARCH DEFAULT. No result below is a trading edge.</div>")

    # ---- answers
    o.append("<h2>Answers to the 15 questions</h2>")
    miss_hist = S["missing_minute_histogram"]
    qa = [
        ("1. Does option-chain data actually exist from 15:15&ndash;15:30?",
         f"Yes, for 15:15&ndash;15:29. On {S['symbol_days_with_window_data']} of {S['symbol_days_with_option_data']} symbol-days with any option data "
         f"({S['date_range'][0]} &rarr; {S['date_range'][1]}) there is a snapshot every minute from 15:15 to 15:29. The 15:30 minute is missing on "
         f"{miss_hist.get('15:30', 0)} symbol-days, because the live loop's last capture is 15:29. After a gap, snapshots resume at about 15:36&ndash;15:39. "
         "The CE and PE legs, bid/ask, OI, volume and IV fields are all present in the raw payload."),
        ("2. How many minutes are available?", f"{S['window_minutes_available']} of {S['window_minutes_expected']} expected window minutes (15:15&ndash;15:30 inclusive)."),
        ("3. How many missing minutes?",
         f"{S['window_minutes_expected'] - S['window_minutes_available']}. Almost all of them are the 15:30 minute ({miss_hist.get('15:30', 0)}). "
         "The 15:15&ndash;15:28 minutes are missing on only 2 symbol-days: 2026-07-17, the first capture day, which has a single snapshot at 15:29. "
         f"Another {len(S['symbol_days_without_window_data'])} symbol-days have no snapshot after 15:15 at all (listed in the audit). "
         "The capture process was <b>not</b> changed: the 15:30 gap comes from the live-loop session boundary, which is protected scheduling, not a capture defect."),
        ("4. How often is the underlying stale?",
         f"On {stale_days} of {all_days} symbol-days the index print stopped updating after 15:15. The exceptions are the July days, "
         f"where the index kept printing. In minute terms, {non_live} of {tot_min} window minutes with a snapshot "
         f"({100 * non_live / tot_min:.0f}%) were STALE or CLOSING_STATE_UNCERTAIN. The typical pattern is a flat 15:15 print that persists "
         "until a new value appears near 15:29&ndash;15:30. We describe this; we do not name a mechanism."),
        ("5. How often are options still changing while the underlying is stale?",
         f"{act_active} of {act_tot} stale-underlying minutes ({100 * act_active / act_tot:.0f}%) had option activity. Activity here means at least "
         f"{cfg.active_min_changed_legs} of the ATM&plusmn;5 legs' mids changed from the previous minute."),
        ("6. Does CE/PE movement precede the next reliable underlying print?",
         f"Directionally, somewhat &mdash; but not beyond the base rate. Over {NP['n_symbol_days']} stale symbol-days, the CE-minus-PE premium change at 5 minutes "
         f"agreed with the next print's direction {v(H['5m|ALL|ce_minus_pe_pct']['hit_rate'])}% of the time (n={H['5m|ALL|ce_minus_pe_pct']['n']}). "
         f"However, {v(NP['up_print_share_pct'])}% of next prints were UP in this sample. Always guessing the majority direction would have scored "
         f"{v(H['5m|ALL|ce_minus_pe_pct']['majority_baseline_pct'])}% on the same days, and the binomial p against that baseline is "
         f"{v(H['5m|ALL|ce_minus_pe_pct']['binomial_p_vs_majority'], 3)}. Option movement <i>preceded</i> the print in the same direction more often than "
         "not, but this sample cannot separate that from the market's drift."),
        ("7. Does option pressure provide useful directional information during the stale period?",
         f"Not demonstrated. The composite OPTION_DIRECTIONAL_PRESSURE hit {v(H['5m|ALL|odp']['hit_rate'])}% at 5 minutes, "
         f"{v(H['10m|ALL|odp']['hit_rate'])}% at 10 minutes and {v(H['15m|ALL|odp']['hit_rate'])}% at about 15 minutes. That is unstable, and at best "
         f"level with the majority baseline. The implied-spot gap at ~15 minutes was associated with the print's size (Spearman &rho; "
         f"{v(M['spearman_rho'], 2)}, p {v(M['spearman_p'], 3)}, n={M['n']}), and its sign agreed {v(H['15m|ALL|implied_gap']['hit_rate'])}% of the time "
         f"(majority baseline {v(H['15m|ALL|implied_gap']['majority_baseline_pct'])}%, p {v(H['15m|ALL|implied_gap']['binomial_p_vs_majority'], 3)}). "
         "That is an association in a small sample, not validated directional information."),
        ("8. Does option-chain evidence give an earlier warning of adverse movement for an existing paper position?",
         f"Not on this evidence. There are no real paper positions to study. On {RP['n']} hypothetical reference positions, every position received at least one "
         f"PREPARE_EXIT / BREAK_EXIT ({WA['saturation']['warned_at_all']} of {WA['saturation']['positions']}), so the warning is not selective. Over the "
         f"next {WA['horizon_min']} minutes, BREAK_EXIT minutes were followed by a median {v(WA['by_action']['BREAK_EXIT']['median_end_ret_pct'], 2)}% option "
         f"move against {v(WA['by_action']['HOLD']['median_end_ret_pct'], 2)}% after HOLD minutes. &minus;1% came before +1% in "
         f"{v(WA['by_action']['BREAK_EXIT']['pct_minus1_before_plus1'])}% of BREAK_EXIT cases against {v(WA['by_action']['HOLD']['pct_minus1_before_plus1'])}% "
         "of HOLD cases. Warnings were <b>not</b> followed by worse outcomes than HOLD; if anything the opposite, which is consistent with short-term mean reversion."),
        ("9. Which variables appear useful descriptively?",
         "(a) The <b>underlying state</b> itself: it is explicit and reliable, and a frozen print is never shown as live. "
         "(b) <b>Option activity while the underlying is stale</b>: the option chain keeps changing. "
         "(c) <b>Option-implied spot</b> (parity) as a description of where the option market sits relative to the frozen print. It tracks the live index "
         "within a few points on live days, and its gap was associated with the size of the next print. "
         "(d) CE vs PE relative premium change as a readable summary. "
         "All four are descriptive; none is a validated signal."),
        ("10. Which variables are unavailable or unreliable?",
         "The index print itself after ~15:15 (stale on most days since August). The 15:30 option snapshot (not captured). Index volume "
         "(the 1-min index candle volume does not change once the print freezes). Greeks and IV for deep-ITM legs. The composite directional "
         "pressure, which flips between horizons. The dated news feed (it ended 2026-08-19, so it is not used)."),
        ("11. How often do Greeks become invalid?",
         f"{v(S['greeks']['invalid_pct'])}% of ATM&plusmn;5 leg-minutes had zero or degenerate IV/Greeks. They are concentrated in ITM puts "
         f"({v(S['greeks']['by_moneyness'].get('PE_ITM', {}).get('invalid_pct'))}%) and ITM calls "
         f"({v(S['greeks']['by_moneyness'].get('CE_ITM', {}).get('invalid_pct'))}%). They are marked INVALID, never repaired or replaced by zero."),
        ("12. How often does the bid/ask spread expand?",
         f"ATM CE/PE spread was at least {cfg.spread_expansion_ratio}&times; its 15:15 value in {v(S['spreads']['expanded_vs_1515_pct'])}% of window "
         f"leg-minutes, and at least {cfg.wide_spread_pct}% wide in {v(S['spreads']['wide_pct'])}%."),
        ("13. How much warning time exists before adverse movement?",
         f"Of the reference positions that fell 5% from entry ({WA['drawdown_lead']['n_positions_with_5pct_drawdown']}), "
         f"{WA['drawdown_lead']['warned_before']} had a warning first, with a median lead of {v(WA['drawdown_lead']['median_lead_minutes'])} minutes. "
         f"But all {WA['drawdown_lead']['n_positions_without_drawdown']} positions that never fell 5% were also warned. "
         "The lead time is therefore not meaningful: a warning that fires on every position gives no information about which ones will fall."),
        ("14. Does this justify adding an OPTION RISK BRAKE to the future scalping decision architecture?",
         "<b>Not yet.</b> The <i>visibility</i> part (underlying state, option continuation, implied spot, explicit reasons) is justified as a display and "
         "a diagnostic. A <i>brake</i> that changes decisions is not: the current evidence ladder saturates on ordinary option noise, and warned minutes "
         "were not followed by worse outcomes. A future brake would need thresholds scaled to each option's own recent volatility, fixed in advance, and "
         "tested out of sample on real (paper) positions."),
        ("15. Does the evidence justify automatic exits?",
         "<b>No.</b> Keep the monitor advisory. The 11D exit engine remains authoritative."),
    ]
    for q, a in qa:
        o.append(f"<h3>{q}</h3><div class='ans'>{a}</div>")

    # ---- audit
    o.append("<h2>1. Data audit (SELECT-only, read-only session)</h2>")
    o.append("<p>Source: <code>option_chain_raw</code> (1-minute snapshots; the raw payload has LTP, top bid/ask with quantities, OI, cumulative volume, IV and "
             "Greeks per strike), <code>raw_candles</code> (1-min index), <code>raw_daily_candles</code> (outcome only). The session opened with "
             "<code>default_transaction_read_only=on</code>.</p>")
    rows = []
    for a in audit:
        if not a.get("snapshots_1515_1530"):
            rows.append([a["symbol"], a["date"], "&ndash;", "&ndash;", 0, "all", "&ndash;", "&ndash;", "&ndash;", "&ndash;", "&ndash;", "&ndash;", "&ndash;", a.get("note", "")])
            continue
        mm = a["missing_minutes_1515_1530"]
        rows.append([a["symbol"], a["date"], a["first_snapshot_after_1515"], a["last_snapshot"], a["snapshots_1515_1530"],
                     ", ".join(mm) if mm else "none", f"{a['atm_available_minutes']}/{a['snapshots_1515_1530']}",
                     f"{v(a['ce_available_pct'], 0)} / {v(a['pe_available_pct'], 0)}", v(a["bid_ask_available_pct"], 0), v(a["oi_available_pct"], 0),
                     v(a["volume_available_pct"], 0), v(a["iv_available_pct"], 0), v(a["greeks_valid_pct"], 0), a.get("expiry")])
    o.append(t(["Symbol", "Date", "First &ge;15:15", "Last (&le;15:39)", "Snapshots 15:15&ndash;15:30", "Missing minutes", "ATM resolved",
                "CE / PE %", "Bid/ask %", "OI %", "Volume %", "IV %", "Greeks valid %", "Expiry / note"], rows))

    # ---- stale
    o.append("<h2>2. Underlying state and option continuation</h2>")
    o.append(t(["Key", "Minutes"], [[k, n] for k, n in sorted(ms.items())]))
    o.append("<p>Underlying states: <b>LIVE</b>; <b>STALE</b> (unchanged for 2+ minutes, or a flat 1-minute candle from 15:15 on); "
             "<b>CLOSING_STATE_UNCERTAIN</b> (a single repeat, or a new value after a frozen stretch near the close &mdash; we cannot tell whether it is "
             "continuous trading or a computed value); <b>MISSING</b>. No minute is labelled &ldquo;auction&rdquo;.</p>")

    # ---- next print
    o.append("<h2>3. Most important question &mdash; does the option chain tell us the direction of the next reliable print?</h2>")
    o.append(f"<p>For each stale symbol-day ({NP['n_symbol_days']}): the frozen value is the last LIVE print; the next reliable print is the first later "
             f"1-minute candle close that differs from it (sources: {M['print_sources']}). Option signals are taken 5, 10 and ~15 minutes after the stale "
             "start. They must be <b>strictly before</b> the print is observable; otherwise they are excluded, which is why the 15-minute n is smaller. "
             f"Prints within &plusmn;{cfg.underlying_move_pts} pts are treated as flat and excluded. The majority baseline is &lsquo;always guess the "
             "direction most prints took on these same days&rsquo;.</p>")
    keys = [f"{h}m|{s}|{k}" for h in (5, 10, 15) for s in ("ALL", "NIFTY", "SENSEX") for k in ("implied_change", "implied_gap", "odp", "ce_minus_pe_pct")]
    keys += [f"baseline|{s}|pre_stale_momentum" for s in ("ALL", "NIFTY", "SENSEX")]
    o.append(t(["Horizon &middot; scope &middot; signal", "N", "Hits", "Hit rate %", "Majority baseline %", "p vs 50%", "p vs majority",
                "Median signal", "Median |print move|", "Flat prints excl."], _hit_rows(H, keys)))
    o.append("<p>Signals: <code>implied_change</code> = option-implied spot change since the stale start; <code>implied_gap</code> = implied spot minus the "
             "frozen print; <code>odp</code> = OPTION_DIRECTIONAL_PRESSURE; <code>ce_minus_pe_pct</code> = ATM CE % change minus ATM PE % change (same "
             "contracts as at the stale start). The comparator <code>pre_stale_momentum</code> is the 15:00&rarr;15:15 index move.</p>")
    o.append(t(["Month (15-min signals)", "implied_gap n / hit %", "ce_minus_pe n / hit %"],
               [[m, f"{x['implied_gap']['n']} / {v(x['implied_gap']['hit_rate'])}", f"{x['ce_minus_pe_pct']['n']} / {v(x['ce_minus_pe_pct']['hit_rate'])}"]
                for m, x in NP["by_month_15m"].items()]))
    o.append(f"<div class='ans'>Magnitude: median |next print &minus; frozen| {v(M['median_abs_print_move'])} pts "
             f"(NIFTY {v(M['median_abs_print_move_by_symbol'].get('NIFTY'))}, SENSEX {v(M['median_abs_print_move_by_symbol'].get('SENSEX'))}); median "
             f"|implied gap| at ~15 min {v(M['median_abs_implied_gap'])} pts; Spearman &rho; {v(M['spearman_rho'], 2)} (p {v(M['spearman_p'], 3)}, "
             f"n={M['n']}). The official daily close equalled the next print (median |close &minus; print| {v(M['median_abs_close_minus_print'])}). "
             "This is described as <i>association</i>, not causation or prediction.</div>")

    # ---- event study
    o.append("<h2>4. Historical event study (15:00&ndash;15:30)</h2>")
    o.append(f"<p>A minute is an event when the live underlying moved by at least &plusmn;{cfg.underlying_move_pts} pts in one minute, or when the "
             "option-implied spot moved by that amount. Classes: A underlying moved first; B options moved first while the underlying was live; "
             "C both moved together; D underlying stale but options moved; E inconclusive. For B and D we check whether the next reliable underlying "
             "observation moved the same way.</p>")
    o.append(t(["Symbol &middot; class", "Events"], [[k.replace("|", " &middot; "), n] for k, n in sorted(ev["counts"].items())]))
    o.append(t(["Class", "With a next reliable move", "Same direction", "Rate %", "p vs 50%", "No next reliable move"],
               [[k, x["n_with_next_reliable_move"], x["same_direction"], v(x["rate"]), v(x["binomial_p_vs_50"], 3), x["n_without_next_reliable_move"]]
                for k, x in ev["preceded"].items()]))
    o.append("<div class='ans'>Option moves <i>preceded</i> a same-direction reliable underlying move only a little more often than chance. The events "
             "overlap and are not independent, so the p-values are optimistic. Full rows: <code>12b_event_study.csv</code>.</div>")

    # ---- warning study
    o.append("<h2>5. Second question &mdash; after the option chain contradicts a position, what happens?</h2>")
    o.append(f"<p>Reference positions (hypothetical, NOT paper trades): ATM BUY CE and ATM BUY PE in two cohorts. <code>11D_SHAPED_1500_1519</code> "
             "uses 11D's timing (enter 15:00, hold at most 19 minutes). <code>CLOSING_1515_1529</code> is held through the stale window. The ATM strike "
             f"is resolved from the entry-minute snapshot only. N = {RP['n']} positions.</p>")
    o.append(f"<h3>All minutes, grouped by the advisory action at that minute (forward window {WA['horizon_min']} minutes, option mid)</h3>")
    hdr = ["Action", "N", "Median max adverse %", "Median max favourable %", "Median end %", "&minus;1% before +1% %", "t max adverse", "t max favourable"]
    o.append(t(hdr, _act_rows(WA["by_action"])))
    for c, w in RP["warning_study_by_cohort"].items():
        o.append(f"<h3>Cohort {c}</h3>" + t(hdr, _act_rows(w["by_action"])))
        o.append(f"<p>Warned at all: {w['saturation']['warned_at_all']} of {w['saturation']['positions']}. Positions that fell 5% from entry: "
                 f"{w['drawdown_lead']['n_positions_with_5pct_drawdown']} ({w['drawdown_lead']['warned_before']} warned first, median lead "
                 f"{v(w['drawdown_lead']['median_lead_minutes'])} min). Positions that never fell 5%: {w['drawdown_lead']['n_positions_without_drawdown']} "
                 f"(warned {w['drawdown_lead']['warned_without_drawdown']}).</p>")
    o.append(t(["Risk state", "Minute evaluations"], [[k, n] for k, n in RP["risk_distribution"].items()]))
    if v0:
        o.append("<div class='risk'><b>Disclosure &mdash; evidence ladder revised once, before this report.</b> The first run counted every negative "
                 "signal separately. Correlated signals (own premium falling, opposite premium rising, relative strength against) then stacked up, "
                 f"and EXTREME was assigned in {v0['reference_positions']['risk_distribution'].get('EXTREME')} of "
                 f"{sum(v0['reference_positions']['risk_distribution'].values())} minute evaluations. The ladder was changed to count "
                 "<b>independent evidence families</b>, as the specification requires (PRICE, RELATIVE, FLOW, POSITIONING, LIQUIDITY, VOLATILITY; see config). "
                 "The change was made on the independence argument and the saturation count, <b>not</b> on the forward-outcome tables. The earlier version's "
                 "outcome summary is kept in <code>data/cache/option_risk_12b/v0_flat_count_summary.json</code>. Both versions reach the same conclusion: the "
                 "warning is not selective. No threshold was tuned to outcomes.</div>")
    o.append("<div class='ans'>Why it saturates: in the last 30 minutes an ATM option's premium routinely moves more than 1% in 2 minutes on ordinary "
             "index noise, and theta decay produces falling straddles every minute. Fixed-percentage research defaults therefore fire on noise. A "
             "credible brake would need thresholds expressed relative to each contract's own recent minute-return distribution, fixed in advance, "
             "and tested on real paper positions out of sample.</div>")

    # ---- data quality
    o.append("<h2>6. Data quality</h2>")
    dq = S["data_quality_flags"]
    o.append(t(["Flag", "Window minutes flagged"], [[k, n] for k, n in sorted(dq.items()) if k != "_minutes"] + [["total window minute-rows", dq.get("_minutes")]]))
    o.append(t(["Moneyness", "VALID", "INVALID", "UNAVAILABLE", "Invalid %"],
               [[k, x.get("VALID", 0), x.get("INVALID", 0), x.get("UNAVAILABLE", 0), v(x["invalid_pct"])] for k, x in sorted(S["greeks"]["by_moneyness"].items())]))
    o.append("<p>Known limitations: Dhan publishes zero/degenerate IV and Greeks for deep-ITM legs (not repaired). Option volume is cumulative, so volume "
             "change is a consecutive difference. Dhan's <code>previous_oi</code> is prior-day OI and is <b>not</b> used; intraday OI change is "
             "current minus the previous snapshot's OI. There is no interpolation or forward-fill: a missing minute stays MISSING. The index 1-minute "
             "volume is not usable once the print freezes. News classification ended 2026-08-19.</p>")

    # ---- leakage
    o.append("<h2>7. Leakage audit</h2>")
    tr = L["truncation_invariance"]
    o.append(t(["Check", "Result"], [
        ["Truncation invariance: every minute view recomputed with only snapshots &le; t and candles that ended &le; t",
         f"{tr['result']} &mdash; {tr['minutes_checked']} minute views, {tr['mismatches']} mismatches"],
        ["Next-print signals strictly before the print is observable", f"{L['signals_strictly_before_print']['result']} ({L['signals_strictly_before_print']['n']} signals)"],
        ["Dhan previous_oi (prior day) not used in live modules", v(L["static"]["previous_oi_not_used"])],
        ["Official close not referenced by live modules (outcome only)", v(L["static"]["official_close_not_in_live_modules"])],
        ["No wall-clock reads in live modules", v(L["static"]["no_clock_in_live_modules"])],
        ["No order code in the package", v(L["static"]["no_order_code"])],
        ["Thresholds", L["thresholds"]],
        ["Outcomes", L["outcomes_isolated"]],
        ["Overall", f"<b>{L['result']}</b>"]]))

    # ---- UI
    o.append("<h2>8. Paper Trading Command Center &mdash; new section (UI description)</h2>")
    o.append("<p>A new section, <b>&ldquo;15:15&ndash;15:30 OPTION RISK &amp; CLOSING STATE&rdquo;</b>, was added to the existing Paper Trading page. It "
             "reads the new read-only endpoint <code>GET /api/v1/option-risk-12b/{symbol}/closing-state?session_date=</code> and has a NIFTY/SENSEX "
             "toggle and a date picker (default: today, or the latest captured session). The same continuation view is also placed under the live "
             "CAS tracker on the Market Transition page. Blocks:</p><ul>"
             "<li><b>Underlying status</b>: a per-minute strip from 15:00 to 15:30, visually split into <i>15:00&ndash;15:15 ACTUAL UNDERLYING</i> and "
             "<i>15:15&ndash;15:30 CLOSING / STALE UNDERLYING + OPTION CHAIN CONTINUATION</i>. It shows LIVE / STALE / CLOSING_STATE_UNCERTAIN / MISSING / "
             "NEW PRINT, plus the last reliable value, its time, the current time and the age. A frozen value is never shown as live.</li>"
             "<li><b>Option chain pressure</b>: minute rows with CE, PE, PCR, CE/PE OI &Delta;, CE/PE volume &Delta;, CE/PE IV, straddle, the pressure label "
             "and the risk state, with CE/PE movement colour-coded.</li>"
             "<li><b>Option movement charts</b>: (1) CE % and PE % premium change since 15:00 plus the ATM straddle, (2) CE/PE intraday OI change, (3) CE/PE "
             "volume per minute. These are three separate charts.</li>"
             "<li><b>Position risk</b>: when a paper position exists, it shows the position, current option price, POSITION_SUPPORT, RISK, RISK_ACTION "
             "(HOLD / CAUTION / PREPARE_EXIT / BREAK_EXIT) and the explicit reasons, each marked ADVISORY. Otherwise it reads MARKET OPTION STATE.</li>"
             "<li><b>Closing state</b>: underlying state, options activity, option-derived state (CE / PE / NEUTRAL / MIXED), implied spot, gap, "
             "confidence (LOW / MODERATE / UNKNOWN, never HIGH), and the data-quality caveat, which is always shown.</li></ul>")
    o.append("<p class='risk'>The endpoint is GET-only. It reads option_chain_raw, raw_candles and paper_positions, and writes nothing. No button in the "
             "section can change a position.</p>")
    o.append(f"<h2>9. Files</h2><p>CSV/JSON in <code>milestone12b_option_risk/</code>: <code>12b_option_trajectory.csv</code> ({len(sig_rows) and ''}per-minute 15:15&ndash;15:30 "
             "trajectory, every day), <code>12b_summary.json</code>, <code>12b_leakage_audit.json</code>, <code>12b_data_quality.json</code>, "
             "<code>12b_data_audit.csv</code>, <code>12b_next_print.csv</code>, <code>12b_next_print_signals.csv</code>, <code>12b_event_study.csv</code>, "
             "<code>12b_reference_positions.csv</code>, <code>12b_reference_position_warnings.csv</code>, <code>12b_config.json</code>. No database tables "
             "were created.</p>")
    o.append("</body></html>")
    return "\n".join(o)
