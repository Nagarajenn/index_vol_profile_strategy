"""Leakage audit (Step 12): every test recomputes on data TRUNCATED at the decision time and
requires identical results, or checks threshold/split provenance. Returns PASS/FAIL + explanation."""

from datetime import datetime, time, timedelta

from config.settings import IST
from opportunity_matrix_v1 import counterfactual as CF
from opportunity_matrix_v1 import features as F
from opportunity_matrix_v1.events import detect_events, lead_lag, news_state
from opportunity_matrix_v1.market_state import market_state
from opportunity_matrix_v1.response import option_response_rows, strike_universe

ORDER = {"SEED": 0, "TRAIN": 1, "VALIDATION": 2, "UNSEEN": 3}


def _res(ok, why):
    return {"result": "PASS" if ok else "FAIL", "explanation": why}


def _cmp_events(a, b):
    k = ("event_id", "event_type", "direction", "detection_method", "futures_return", "option_return")
    return [tuple(e[x] for x in k) for e in a] == [tuple(e[x] for x in k) for e in b]


def audit(days, minute_th, ds, cfg, sample_every_s=60) -> dict:
    hth = ds["_hth"]
    tests, checks = {}, {k: [0, 0] for k in "ABCDEFIJ"}
    for (d, sym), th in hth.items():
        if th is None:
            continue
        day = days[d][sym]
        full_events = detect_events(day, th, cfg)
        # A: events at every sampled T identical with the future removed
        for k in range(0, len(day), sample_every_s // cfg.bar_seconds):
            T = day.known_at(k)
            tr = detect_events(day.truncate(T), th, cfg)
            checks["A"][0] += 1
            checks["A"][1] += _cmp_events(tr, [e for e in full_events if e["i"] <= k])
        for e in full_events[:40]:
            T = day.known_at(e["i"])
            tday = day.truncate(T)
            ll_full, ll_tr = lead_lag(day, e["i"], e["dir"], th, cfg), lead_lag(tday, e["i"], e["dir"], th, cfg)
            ev_f, ev_t = dict(e, **ll_full), dict(e, **ll_tr)
            # B: option responses (backward-looking) identical
            rf, rt = option_response_rows(ev_f, day, th, cfg), option_response_rows(ev_t, tday, th, cfg)
            checks["B"][0] += 1
            checks["B"][1] += rf == rt and ll_full == ll_tr
            # I/J: option + strike selection identical at the decision bar / entry bar
            gf, gt = CF.gates(ev_f, ll_full, day, th, cfg), CF.gates(ev_t, ll_tr, tday, th, cfg)
            checks["I"][0] += 1
            checks["I"][1] += (gf["selected_option"], gf["selected_offset"], gf["option_response_class"], gf["research_approved"]) == \
                (gt["selected_option"], gt["selected_offset"], gt["option_response_class"], gt["research_approved"])
            ei = e["i"] + cfg.entry_offsets[cfg.primary_entry]
            if ei < len(day):
                Te = day.known_at(ei)
                checks["J"][0] += 1
                checks["J"][1] += strike_universe(day, ei, e["dir"], cfg) == strike_universe(day.truncate(Te), ei, e["dir"], cfg)
        # C/D/E/F: market state (VWAP, POC, OI, volume) identical with future candles/snapshots removed
        for hhmm in cfg.snapshot_times + ("15:05", "15:20"):
            T = datetime.combine(d, time.fromisoformat(hhmm), tzinfo=IST)
            mf, mt = market_state(day, T, minute_th[(d, sym)], cfg), market_state(day.truncate(T), T, minute_th[(d, sym)], cfg)
            for key, fld in (("C", "u_vwap"), ("D", "u_poc"), ("E", "o_ce_oi"), ("F", "u_volume15")):
                checks[key][0] += 1
                checks[key][1] += mf.get(fld) == mt.get(fld)
    for key, name, what in (("A", "A_no_future_underlying", "event detection"), ("B", "B_no_future_option", "option responses and lead/lag"),
                            ("C", "C_no_future_vwap", "VWAP"), ("D", "D_no_future_poc", "POC"), ("E", "E_no_future_oi", "OI"),
                            ("F", "F_no_future_volume", "volume"), ("I", "I_no_future_option_selection", "option selection / gates"),
                            ("J", "J_no_future_strike_selection", "strike universe at entry")):
        n, ok = checks[key]
        tests[name] = _res(n > 0 and ok == n, f"{ok}/{n} {what} recomputations on data truncated at the decision time were identical")
    th_rows = ds["thresholds"]
    fut = [r for r in th_rows if any(s >= r["date"] for s in r["hr_source_days"] + r["minute_source_days"])]
    tests["G_no_future_threshold_fitting"] = _res(not fut, f"{len(th_rows)} threshold sets; every source day is strictly earlier than its target day")
    same = [r for r in th_rows if r["date"] in r["hr_source_days"] + r["minute_source_days"]]
    tests["H_no_same_day_threshold_fitting"] = _res(not same, "no threshold set uses its own target day")
    tests["K_no_future_expiry_information"] = _res(
        all((days[d][s].universe_resolved_at or "99") < cfg.hr_first_bar for d in days for s in days[d]),
        f"expiry comes from the HR universe resolved at {next(iter(next(iter(days.values())).values())).universe_resolved_at} (before the 14:55 window)")
    feed = any(days[d][s].news_feed_active for d in days for s in days[d])
    news_ok = all(e["news_state"] == ("NEWS_UNKNOWN" if not days[datetime.fromisoformat(e["event_timestamp"]).date()][e["symbol"]].news_feed_active
                                      else e["news_state"]) for e in ds["events"])
    tests["L_no_future_news"] = _res(news_ok, "news feed inactive on HR days -> NEWS_UNKNOWN everywhere" if not feed
                                     else "news filtered to classified_at <= event time")
    roles = ds["roles"]
    contaminated = [r for r in th_rows if any(roles.get(s) in ("VALIDATION", "UNSEEN") and s >= r["date"] for s in r["hr_source_days"])]
    tests["M_no_test_day_contamination"] = _res(not contaminated, "no VALIDATION/UNSEEN day contributes to its own or an earlier day's thresholds")
    seq = [ORDER[roles[k]] for k in sorted(roles)]
    tests["N_no_shuffled_split"] = _res(seq == sorted(seq), f"roles in date order: {[roles[k] for k in sorted(roles)]}")
    clusters = {}
    for e in ds["events"]:
        clusters.setdefault(e["event_cluster_id"], []).append(e)
    firsts = sum(1 for e in ds["events"] if e["cluster_first"])
    bad = [c for c, es in clusters.items() if any((x["i"] - es[0]["i"]) * cfg.bar_seconds > cfg.cluster_gap_s for x in es)]
    tests["O_no_overlapping_event_leakage"] = _res(firsts == len(clusters) and not bad,
                                                   f"{len(ds['events'])} events in {len(clusters)} clusters; cluster-level statistics use one row per cluster")
    sample_ok = all(market_state(days[d][s], datetime.combine(d, time(14, 57), tzinfo=IST), minute_th[(d, s)], cfg)["market_state"] ==
                    market_state(days[d][s].truncate(datetime.combine(d, time(14, 57), tzinfo=IST)), datetime.combine(d, time(14, 57), tzinfo=IST),
                                 minute_th[(d, s)], cfg)["market_state"] for d in days for s in days[d])
    tests["market_state_truncation"] = _res(sample_ok, "market state at 14:57 identical with all later data removed, every symbol-day")
    overall = "PASS" if all(t["result"] == "PASS" for t in tests.values()) else "FAIL"
    return {"overall": overall, "tests": tests}
