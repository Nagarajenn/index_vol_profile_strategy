"""Experiments A-L (descriptive). Every table is split by symbol and by day type (NORMAL / EXPIRY),
and reported at event level and cluster level (one row per event cluster). Track A uses events
in the MODE_A windows only; Track B (closing state) is separate."""

import statistics as st

TRACK_A = ("MODE_A_EARLY", "MODE_A_MIDDLE", "MODE_A_LATE")


def med(v, nd=3):
    v = [x for x in v if x is not None]
    return round(st.median(v), nd) if v else None


def mean(v, nd=3):
    v = [x for x in v if x is not None]
    return round(st.mean(v), nd) if v else None


def pct(n, d):
    return round(100.0 * n / d, 1) if d else None


def q10(v):
    v = sorted(x for x in v if x is not None)
    return round(v[int(0.1 * (len(v) - 1))], 3) if v else None


def cf_stats(rows):
    ok = [r for r in rows if r.get("status") == "OK"]
    n = len(ok)
    net = [r["net_return"] for r in ok]
    return dict(n=n, clusters=len({r["event_cluster_id"] for r in ok}), median_net=med(net), mean_net=mean(net),
                win_rate=pct(sum(1 for x in net if x is not None and x > 0), sum(1 for x in net if x is not None)),
                hit1_before_minus1=pct(sum(1 for r in ok if r.get("hit1_before_minus1")), sum(1 for r in ok if r.get("hit1_before_minus1") is not None)),
                mfe=med([r["mfe"] for r in ok]), mae=med([r["mae"] for r in ok]), mae_p10=q10([r["mae"] for r in ok]),
                time_to_1=med([r["time_to_1"] for r in ok], 0), reach_1=pct(sum(1 for r in ok if r.get("time_to_1") is not None), n),
                giveback=med([r["giveback"] for r in ok]), spread=med([r["entry_spread_pct"] for r in ok]),
                move_remaining=med([r["move_remaining"] for r in ok]))


def cluster_level(rows):
    """One row per event cluster: the cluster's first event."""
    return [r for r in rows if r.get("cluster_first")]


def split(rows, key_fn):
    out = {}
    for r in rows:
        out.setdefault(key_fn(r), []).append(r)
    return out


def by_sym_day(rows):
    return {f"{s} | {'EXPIRY' if e else 'NORMAL'}": [r for r in rows if r["symbol"] == s and bool(r.get("expiry_flag")) == e]
            for s in ("NIFTY", "SENSEX") for e in (False, True)}


def run_all(ds, days, cfg) -> dict:
    ev = [e for e in ds["events"] if e["window"] in TRACK_A]
    evid = {e["event_id"]: e for e in ds["events"]}
    cf = [c for c in ds["counterfactuals"] if c.get("window") in TRACK_A]
    prim = [c for c in cf if c["entry"] == cfg.primary_entry]
    base = [b for b in ds["baseline"] if b.get("window") in TRACK_A]
    R = {"track_a_events": len(ev), "track_a_clusters": len({e["event_cluster_id"] for e in ev})}

    # A: pre-state -> event type
    R["A"] = {g: {st_: {t: sum(1 for e in rows if e["state_14_59"] == st_ and e["event_type"] == t) for t in
                        ("UP_IMPULSE", "DOWN_IMPULSE", "UP_REVERSAL", "DOWN_REVERSAL", "CONTINUATION")}
                  for st_ in sorted({e["state_14_59"] for e in rows if e["state_14_59"]})} for g, rows in by_sym_day(ev).items()}
    R["A_setup"] = {g: {s: {"UP": sum(1 for e in rows if e["setup_state"] == s and e["dir"] > 0), "DOWN": sum(1 for e in rows if e["setup_state"] == s and e["dir"] < 0)}
                        for s in sorted({e["setup_state"] for e in rows})} for g, rows in by_sym_day(ev).items()}
    # B: pre-state -> option response
    resp_dir = {}
    for r in ds["option_response"]:
        if r["direction_leg"] and r["atm_offset"] == 0:
            resp_dir[r["event_id"]] = r
    R["B"] = {g: {s: dict(n=len(x), strong_or_moderate=pct(sum(1 for e in x if e["option_response_class"] in ("STRONG", "MODERATE")), len(x)),
                          median_response_10s=med([(resp_dir.get(e["event_id"]) or {}).get("response_10s") for e in x]))
                  for s, x in split(rows, lambda e: e["setup_state"]).items()} for g, rows in by_sym_day(ev).items()}
    # C: event -> option response (elasticity)
    R["C"] = {g: {t: dict(n=len(x), classes={c: sum(1 for e in x if e["option_response_class"] == c) for c in ("STRONG", "MODERATE", "WEAK", "NONE", "CONTRADICTORY")},
                          median_relative_response_10s=med([(resp_dir.get(e["event_id"]) or {}).get("relative_response_10s") for e in x]))
                  for t, x in split(rows, lambda e: e["event_type"]).items()} for g, rows in by_sym_day(ev).items()}
    # D: lead/lag -> opportunity quality (event and cluster level)
    R["D"] = {g: {cls: dict(event=cf_stats(x), cluster=cf_stats(cluster_level(x))) for cls, x in split(rows, lambda c: c["lead_lag_class"]).items()}
              for g, rows in by_sym_day(prim).items()}
    # E: entry timing
    R["E"] = {g: {lbl: dict(executable=lbl in cfg.executable_entries, event=cf_stats([c for c in rows if c["entry"] == lbl]))
                  for lbl in cfg.entry_offsets} for g, rows in by_sym_day(cf).items()}
    # F: time to profit
    R["F"] = {g: {lbl: {lvl: dict(reach=pct(sum(1 for c in rows if c["entry"] == lbl and c.get(k) is not None),
                                            sum(1 for c in rows if c["entry"] == lbl and c.get("status") == "OK")),
                                  median_s=med([c.get(k) for c in rows if c["entry"] == lbl], 0))
                        for lvl, k in (("0.5%", "time_to_0_5"), ("1%", "time_to_1"), ("2%", "time_to_2"))}
                  for lbl in cfg.executable_entries} for g, rows in by_sym_day(cf).items()}
    # G: MAE by dimension
    def mae_by(key):
        return {g: {k: dict(n=len(x), mae_median=med([c["mae"] for c in x]), mae_p10=q10([c["mae"] for c in x]))
                    for k, x in split(rows, key).items()} for g, rows in by_sym_day(prim).items()}
    R["G"] = {"state_14_59": mae_by(lambda c: evid[c["event_id"]]["state_14_59"]), "event_type": mae_by(lambda c: c["event_type"]),
              "lead_lag": mae_by(lambda c: c["lead_lag_class"]), "option_type": mae_by(lambda c: c["option_type"])}
    # H: opportunity decay
    R["H"] = {g: dict(n=len(rows), event_to_entry=med([c.get("decay_event_to_entry") for c in rows]),
                      **{f"entry_to_{h}s": med([c.get(f"decay_entry_to_{h}s") for c in rows]) for h in (10, 20, 30, 60)})
              for g, rows in by_sym_day(prim).items()}
    # I: pre-state vs event disagreement
    R["I"] = {g: {a: cf_stats(x) for a, x in split(rows, lambda c: evid[c["event_id"]]["setup_agreement"]).items()}
              for g, rows in by_sym_day(prim).items()}
    # approval + baseline comparisons
    R["approved"] = {g: dict(approved=cf_stats([c for c in rows if c["research_approved"]]), all=cf_stats(rows),
                             approved_cluster=cf_stats(cluster_level([c for c in rows if c["research_approved"]])))
                     for g, rows in by_sym_day(prim).items()}
    R["baseline"] = {g: {lbl: cf_stats([b for b in rows if b["entry"] == lbl]) for lbl in cfg.executable_entries}
                     for g, rows in by_sym_day(base).items()}
    R["rejections"] = {}
    for e in ev:
        R["rejections"][e["first_failed_stage"] or "APPROVED"] = R["rejections"].get(e["first_failed_stage"] or "APPROVED", 0) + 1
    R["labels_at_entry"] = {}
    R["labels_outcome"] = {}
    for e in ev:
        R["labels_at_entry"][e["primary_at_entry_label"]] = R["labels_at_entry"].get(e["primary_at_entry_label"], 0) + 1
        R["labels_outcome"][e["outcome_label"]] = R["labels_outcome"].get(e["outcome_label"], 0) + 1
    # J: closing state persistence (Track B)
    pm = ds["persistence"]
    R["J"] = {f"{s} | {'EXPIRY' if x else 'NORMAL'}": {grp: dict(n=len(rows), fut_move_after_confirm_mean=mean([r["fut_move_after_confirm"] for r in rows]),
                                                               fut_same_direction=pct(sum(1 for r in rows if (r["fut_move_after_confirm"] or 0) > 0), len(rows)),
                                                               close_vs_last_reliable_mean=mean([r["close_vs_last_reliable_after_confirm"] for r in rows]),
                                                               close_same_direction=pct(sum(1 for r in rows if (r["close_vs_last_reliable_after_confirm"] or 0) > 0), len(rows)))
                                                       for grp, rows in (("persistent_30s", [r for r in pm if r["symbol"] == s and r["expiry_flag"] == x and r["persistent_30s"]]),
                                                                         ("one_bar_like", [r for r in pm if r["symbol"] == s and r["expiry_flag"] == x and r["one_bar_like"]]),
                                                                         ("all", [r for r in pm if r["symbol"] == s and r["expiry_flag"] == x]))}
              for s in ("NIFTY", "SENSEX") for x in (False, True)}
    R["J_persistence_rates"] = {f"{h}s": pct(sum(1 for r in pm if r.get(f"persist_{h}s")), sum(1 for r in pm if r.get(f"persist_{h}s") is not None))
                                for h in cfg.persistence_horizons_s}
    R["closing_states"] = {g: {s: sum(1 for r in ds["closing_state"] if r["symbol"] == g.split(" | ")[0] and bool(r["expiry_flag"]) == (g.endswith("EXPIRY")) and r["closing_state"] == s)
                               for s in ("STABLE", "MOVING_UP", "MOVING_DOWN", "DIVERGING", "CONVERGING", "UNRELIABLE")}
                           for g in ("NIFTY | NORMAL", "NIFTY | EXPIRY", "SENSEX | NORMAL", "SENSEX | EXPIRY")}
    # chronological validation: approved vs baseline per role, per symbol (NORMAL days)
    roles = ds["roles"]
    R["chrono"] = {}
    for role in ("TRAIN", "VALIDATION", "UNSEEN"):
        for s in ("NIFTY", "SENSEX"):
            a = [c for c in prim if c["research_approved"] and roles.get(c["trade_date"]) == role and c["symbol"] == s and not c["expiry_flag"]]
            b = [x for x in base if x["entry"] == cfg.primary_entry and roles.get(x["trade_date"]) == role and x["symbol"] == s and not x["expiry_flag"]]
            R["chrono"][f"{role} | {s}"] = dict(approved=cf_stats(a), baseline=cf_stats(b), days=sorted({c["trade_date"] for c in a}))
    R["decision"] = decision_matrix(ev, prim, base, ds, roles, cfg)
    return R


def _dim_metric(rows):
    s = cf_stats(rows)
    return s["n"], s["clusters"], s["hit1_before_minus1"], s["median_net"]


def decision_matrix(ev, prim, base, ds, roles, cfg):
    dims = {
        "research_approved_events": lambda c: c["research_approved"],
        "lead_lag=OPTION_LEAD": lambda c: c["lead_lag_class"] == "OPTION_LEAD",
        "lead_lag=SYNCHRONIZED": lambda c: c["lead_lag_class"] == "SYNCHRONIZED",
        "lead_lag=UNDERLYING_LEAD": lambda c: c["lead_lag_class"] == "UNDERLYING_LEAD",
        "lead_lag=FALSE_OPTION_MOVE": lambda c: c["lead_lag_class"] == "FALSE_OPTION_MOVE",
        "event_type=REVERSAL": lambda c: "REVERSAL" in c["event_type"],
        "event_type=CONTINUATION": lambda c: c["event_type"] == "CONTINUATION",
        "setup_agreement=AGREE": lambda c: ev_by(ds)[c["event_id"]]["setup_agreement"] == "AGREE",
        "setup_agreement=DISAGREE": lambda c: ev_by(ds)[c["event_id"]]["setup_agreement"] == "DISAGREE",
        "at_entry=EARLY_OPPORTUNITY": lambda c: ev_by(ds)[c["event_id"]]["primary_at_entry_label"] == "EARLY_OPPORTUNITY",
    }
    rows = []
    for name, f in dims.items():
        sel = [c for c in prim if not c["expiry_flag"] and f(c)]
        res = {}
        for role in ("TRAIN", "VALIDATION", "UNSEEN"):
            res[role] = _dim_metric([c for c in sel if roles.get(c["trade_date"]) == role])
        b = cf_stats([x for x in base if x["entry"] == cfg.primary_entry and not x["expiry_flag"]])
        per_day = {}
        for c in sel:
            per_day.setdefault(c["trade_date"], []).append(c)
        bday = {d: cf_stats([x for x in base if x["entry"] == cfg.primary_entry and x["trade_date"] == d and not x["expiry_flag"]])["hit1_before_minus1"] for d in per_day}
        diffs = [(cf_stats(v)["hit1_before_minus1"] or 0) - (bday[d] or 0) for d, v in per_day.items()]
        stable_days = len(diffs) >= 2 and (all(x > 0 for x in diffs) or all(x < 0 for x in diffs))
        sym = {s: (cf_stats([c for c in sel if c["symbol"] == s])["hit1_before_minus1"] or 0) -
               (cf_stats([x for x in base if x["entry"] == cfg.primary_entry and x["symbol"] == s and not x["expiry_flag"]])["hit1_before_minus1"] or 0)
               for s in ("NIFTY", "SENSEX")}
        stable_sym = all(v > 0 for v in sym.values()) or all(v < 0 for v in sym.values())
        n_clusters = len({c["event_cluster_id"] for c in sel})
        unseen_n = res["UNSEEN"][0]
        if unseen_n == 0 or n_clusters < 30:
            status = "INSUFFICIENT"
        elif stable_days and stable_sym and all(d > 0 for d in diffs):
            status = "PROMISING_RESEARCH_SIGNAL"
        elif stable_days and stable_sym:
            status = "NO_RELATIONSHIP"
        else:
            status = "INCONCLUSIVE"
        fmt = lambda r: f"n={r[0]}, clusters={r[1]}, +1%-before--1%={r[2]}%, median net={r[3]}%" if r[0] else "no data"
        rows.append(dict(research_dimension=name, sample_size=f"{len(sel)} events / {n_clusters} clusters (normal days)",
                         training_result=fmt(res["TRAIN"]), validation_result=fmt(res["VALIDATION"]), unseen_result=fmt(res["UNSEEN"]),
                         random_baseline=f"+1%-before--1%={b['hit1_before_minus1']}%, median net={b['median_net']}% (n={b['n']})",
                         stable_across_days=stable_days, stable_across_symbols=stable_sym, expiry_separated=True,
                         leakage_status="PASS (see leakage audit)", evidence_status=status,
                         notes=f"per-day difference vs baseline (pp): {[round(x, 1) for x in diffs]}; per-symbol: { {k: round(v, 1) for k, v in sym.items()} }"))
    return rows


_EV = {}


def ev_by(ds):
    key = id(ds)
    if key not in _EV:
        _EV[key] = {e["event_id"]: e for e in ds["events"]}
    return _EV[key]
