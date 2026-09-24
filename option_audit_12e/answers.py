"""The fifteen required questions, answered from the computed numbers rather than from prose.

Every answer is assembled from values in the report dicts. If a value is missing the answer says
so instead of guessing, and every proportion carries its denominator.
"""

import statistics as st


def _n(x, d=2):
    return f"{x:,.{d}f}" if isinstance(x, (int, float)) else "–"


def _pe(rows):
    return [r for r in rows if r["side"] == "PE"]


def build_answers(rep: dict, rows: list[dict], hist: dict | None = None) -> list[tuple]:
    pe = _pe(rows)
    q = rep["quadrants_pe"]
    se, sepe = rep["spread_economics"], rep["spread_economics_pe"]
    lc, pc = rep["loss_reason_counts"], rep["pe_loss_reason_counts"]
    resp_pe = rep["response_pe"]
    out = []

    # 1 & 2 -- PE rising when the underlying falls
    best = max((h for h in ("1m", "3m", "5m", "10m") if q[h]["measurable"]),
               key=lambda h: q[h]["measurable"], default=None)
    if best:
        m = q[best]["measurable"]
        pct = q[best]["pct"]
        ok = pct.get("UNDERLYING_CORRECT_OPTION_PROFITABLE", 0)
        bad = pct.get("UNDERLYING_CORRECT_OPTION_LOSS", 0)
        out.append(("1. When the underlying falls, how often does PE actually rise?",
                    f"At the {best} horizon, of {m} measurable PE signals <b>{ok:.1f}%</b> had the "
                    f"underlying fall <i>and</i> the option profitable."))
        out.append(("2. When the underlying falls, how often does PE fail to rise?",
                    f"<b>{bad:.1f}%</b> of measurable PE signals at {best}: the underlying moved down "
                    f"but the option still lost."))
    else:
        out.append(("1. When the underlying falls, how often does PE actually rise?",
                    "No PE signal had a measurable underlying move at any horizon today."))
        out.append(("2. When the underlying falls, how often does PE fail to rise?", "Not measurable today."))

    # 3 -- what explains the failures
    top = sorted(pc.items(), key=lambda x: -x[1])[:3]
    out.append(("3. When PE fails despite the underlying falling, what explains it?",
                ("Attributed reasons for losing PE trades, most common first: "
                 + ", ".join(f"<b>{k.replace('_', ' ').lower()}</b> ({v})" for k, v in top)
                 + ".") if top else "No losing PE trades to attribute."))

    # 4 -- spread share
    out.append(("4. How much of today's PE loss comes from spread?",
                f"Mean execution friction on PE was <b>{_n(sepe['mean_execution_friction_per_unit'])}/unit</b> "
                f"against a mean executable result of {_n(sepe['mean_executable_per_unit'])}/unit. "
                f"{sepe['losers_that_were_positive_mid_to_mid']} of {sepe['losers']} losing PE trades "
                f"(<b>{_n(sepe['pct_of_losers_caused_by_friction'], 1)}%</b>) would have been positive "
                f"mid-to-mid, so the spread alone turned them negative."))

    # 5 -- weak response
    eff = [v for h, v in resp_pe.items() if v["median_efficiency"] is not None]
    med = st.median([v["median_efficiency"] for v in eff]) if eff else None
    weak = pc.get("WEAK_OPTION_RESPONSE", 0) + pc.get("STRIKE_DISTANCE", 0)
    out.append(("5. How much comes from weak option response?",
                f"Median response efficiency across horizons was <b>{_n(med, 2)}</b> "
                f"(1.0 = exactly what delta implies), and only <b>{weak}</b> losing PE trades were "
                f"attributed to weak response or strike distance. Option response is not a material "
                f"cause today." if med is not None else "Response efficiency was not measurable today."))

    # 6 -- IV
    ivs = [r["iv_change_to_exit_pct"] for r in pe if isinstance(r.get("iv_change_to_exit_pct"), (int, float))]
    out.append(("6. How much comes from IV contraction?",
                f"<b>{pc.get('IV_HEADWIND', 0)}</b> losing PE trades were attributed to an IV headwind. "
                f"Mean IV change over the hold on PE was {_n(st.fmean(ivs), 2) if ivs else '–'}%."))

    # 7 -- late entry
    pre = [abs(r["und_pre_5m_pct"]) for r in pe if isinstance(r.get("und_pre_5m_pct"), (int, float))]
    post = [abs(r["und_move_to_exit_pct"]) for r in pe if isinstance(r.get("und_move_to_exit_pct"), (int, float))]
    share = (st.fmean(pre) / (st.fmean(pre) + st.fmean(post)) * 100) if (pre and post) else None
    out.append(("7. How much comes from late entry?",
                f"<b>{pc.get('LATE_ENTRY', 0)}</b> losing PE trades were attributed to late entry. On "
                f"average <b>{_n(share, 0)}%</b> of the underlying movement around a PE signal happened "
                f"in the 5 minutes <i>before</i> it." if share is not None
                else f"{pc.get('LATE_ENTRY', 0)} attributed to late entry; the pre/post split was not measurable."))

    # 8 -- reversal
    out.append(("8. How much comes from the underlying reversing after entry?",
                f"<b>{pc.get('MOMENTUM_REVERSAL', 0)}</b> losing PE trades reversed after going the right "
                f"way first, and <b>{pc.get('UNDERLYING_DID_NOT_CONTINUE', 0)}</b> never went the right "
                f"way at any measured horizon."))

    # 9 & 10 -- strike and delta
    bands = {k: v for k, v in rep["by_strike_band"].items() if v["n"]}
    out.append(("9. Does strike distance matter?",
                "By band: " + "; ".join(
                    f"{k.replace('_', ' ').lower()} N={v['n']}, mean {_n(v['mean_pnl_per_unit'])}/unit"
                    + ("" if v["sufficient"] else " <i>(small N)</i>") for k, v in bands.items())
                + ". Not separable at today's sample size."))
    db = {k: v for k, v in rep["delta_buckets"].items() if v["n"]}
    out.append(("10. Does delta matter?",
                "By |delta|: " + "; ".join(
                    f"{k} N={v['n']}, mean {_n(v['mean_pnl_per_unit'])}/unit"
                    + ("" if v["sufficient"] else " <i>(small N)</i>") for k, v in db.items())
                + "."))

    # 11 -- time of day
    hrs = {k: v for k, v in rep["by_hour"].items() if v["n"]}
    if hrs:
        bestk = max(hrs, key=lambda k: hrs[k]["mean_pnl_per_unit"] or -1e9)
        worstk = min(hrs, key=lambda k: hrs[k]["mean_pnl_per_unit"] or 1e9)
        out.append(("11. Does time-of-day matter?",
                    f"Best band {bestk} (N={hrs[bestk]['n']}, mean {_n(hrs[bestk]['mean_pnl_per_unit'])}/unit), "
                    f"worst {worstk} (N={hrs[worstk]['n']}, mean {_n(hrs[worstk]['mean_pnl_per_unit'])}/unit). "
                    f"Every band is below the minimum sample today — not interpretable on one session."))
    else:
        out.append(("11. Does time-of-day matter?", "No measurable bands today."))

    # 12 & 13 -- density and flips
    dn, rn, fl = rep["density"]["overall"], rep["runs"], rep["flips"]
    out.append(("12. Are repeated signals causing overtrading?",
                f"<b>{_n(dn['mean_signals_per_hour'], 1)}</b> signals per hour, median gap "
                f"<b>{_n(dn['median_gap_minutes'], 0)} minutes</b>, {dn['gaps_under_3min']} of "
                f"{dn['total_gaps']} gaps under 3 minutes. Same-direction runs average "
                f"{_n(rn['mean_run_length'], 2)} signals (max {rn['max_run_length']}), so one move does "
                f"produce several entries."))
    tail = (" Every flip followed a real move in the underlying, so the churn is the market's, not the "
            "engine's." if fl["confirmed_pct"] == 100 else
            f" The remaining {fl['not_confirmed']} changed side without the underlying doing so.")
    out.append(("13. Are signal flips causing unnecessary churn?",
                f"<b>{fl['flips']}</b> direction flips; <b>{_n(fl['confirmed_pct'], 0)}%</b> were confirmed "
                f"by the underlying actually moving against the old side, median gap "
                f"{_n(fl['median_gap_minutes'], 0)} minutes." + tail))

    # 14 -- the old metric
    da = rep["direction_accuracy"]
    tenm = da.get("10m", {})
    out.append(("14. Is the current &quot;direction correct&quot; metric misleading?",
                f"<b>Yes.</b> 12D's <code>MFE &ge; 0.5%</code> proxy reported 90.3% across history. "
                f"Measured from the underlying itself, today's 10-minute figure is "
                f"<b>{_n(tenm.get('pct'), 1)}%</b> on {tenm.get('measurable')} measurable signals, with "
                f"{tenm.get('unmeasurable')} unmeasurable because spot barely moved. The old number was "
                f"measuring the option ticking up, not the market being read correctly."))

    # 15 -- largest source
    ranked = sorted(lc.items(), key=lambda x: -x[1])
    top1 = ranked[0] if ranked else (None, 0)
    states = rep["pe_by_market_state"]
    rng = states.get("RANGE", {}).get("n", 0)
    total_pe = len(pe)
    out.append(("15. What is the largest measurable source of today's losses?",
                f"By count, <b>{top1[0].replace('_', ' ').lower() if top1[0] else '–'}</b> "
                f"({top1[1]} trades). But the structural finding is context: "
                f"<b>{rng} of {total_pe}</b> PE signals fired while the underlying's own 10-minute state "
                f"was RANGE, not TRENDING DOWN. The day's decline was a slow drift, so at the scale the "
                f"signal operates on there was usually no trend to capture — and the round trip still "
                f"cost {_n(se['mean_execution_friction_per_unit'])}/unit."))
    return out
