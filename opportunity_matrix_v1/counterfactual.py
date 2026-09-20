"""Research approval gates, counterfactual entries/exits, outcome windows and labels
(Steps 8-9, sections 12-17). RESEARCH ONLY: entry at ASK, exit at BID, no orders, no
positions, no account. The event-bar entry is recorded but is NEVER executable.

Separation of information:
* gates and AT-ENTRY labels use bars <= the decision bar;
* outcome windows, MFE/MAE, profit timings and OUTCOME labels use later bars and are
  never fed back into any gate, label or selection."""

from datetime import time

from opportunity_matrix_v1 import features as F
from opportunity_matrix_v1.response import event_atm_offset, liquidity_ok, response_class

AT_ENTRY_LABELS = ("EARLY_OPPORTUNITY", "MID_OPPORTUNITY", "LATE_OPPORTUNITY", "LIQUIDITY_PROBLEM", "OPTION_NON_RESPONSE")
OUTCOME_LABELS = ("NO_FOLLOW_THROUGH", "FALSE_OPPORTUNITY", "FOLLOW_THROUGH")


def gates(event, ll, day, th, cfg) -> dict:
    """Pipeline: EVENT -> DIRECTION -> OPTION RESPONSE -> LIQUIDITY -> EARLYNESS -> EXTENSION -> RESEARCH APPROVAL."""
    i, d = event["i"], event["dir"]
    off = event_atm_offset(day, i)
    key = ("CE" if d > 0 else "PE", off)
    rc = response_class(day, i, d, th, cfg)
    liq, liq_reason = liquidity_ok(day, key, i, cfg)
    age = ll.get("onset_age_s")
    r300 = F.fmove(day, i, 60)
    extended = r300 is not None and r300 * d > 0 and th["r300"].p(cfg.extension_pct) is not None and abs(r300) >= th["r300"].p(cfg.extension_pct)
    t = day.known_at(i).time()
    window_ok = event["window"] in cfg.approval_windows
    expiry_block = day.is_expiry and t >= time.fromisoformat(cfg.expiry_no_approval_from)
    stages = [("WINDOW", window_ok and not expiry_block, "OUTSIDE_TRACK_A_WINDOW" if not window_ok else "EXPIRY_RESTRICTION"),
              ("DIRECTION", d in (1, -1), "NO_DIRECTION"),
              ("OPTION_RESPONSE", rc in cfg.approval_min_response, f"RESPONSE_{rc}"),
              ("LIQUIDITY", liq, liq_reason),
              ("EARLYNESS", age is not None and age <= cfg.mid_onset_s, "LATE_ONSET"),
              ("EXTENSION", not extended, "EXTENDED")]
    failed = [(s, why) for s, ok, why in stages if not ok]
    if age is None:
        timing = None
    elif age <= cfg.early_onset_s:
        timing = "EARLY_OPPORTUNITY"
    elif age <= cfg.mid_onset_s:
        timing = "MID_OPPORTUNITY"
    else:
        timing = "LATE_OPPORTUNITY"
    at_entry = []
    if not liq:
        at_entry.append("LIQUIDITY_PROBLEM")
    if rc in ("NONE", "CONTRADICTORY"):
        at_entry.append("OPTION_NON_RESPONSE")
    if timing:
        at_entry.append(timing)
    return dict(selected_option=key[0], selected_offset=off, selected_strike=day.legs[key]["strike"] if key in day.legs else None,
                option_response_class=rc, liquidity_ok=liq, liquidity_reason=liq_reason, extended=extended,
                stage_results={s: ok for s, ok, _ in stages}, first_failed_stage=failed[0][0] if failed else None,
                rejection_reasons=[w for _, w in failed], research_approved=not failed,
                at_entry_labels=at_entry, primary_at_entry_label=at_entry[0] if at_entry else None)


def _path(day, key, e, horizon_s):
    q0 = day.opt[key][e] if key in day.opt and e < len(day.opt[key]) else None
    if q0 is None or not q0.get("ask") or not q0.get("bid"):
        return None, None
    ask = q0["ask"]
    p = []
    for k in range(e + 1, min(len(day), e + 1 + horizon_s // 5)):
        qk = day.opt[key][k]
        if qk and qk.get("bid"):
            p.append(((k - e) * 5, (qk["bid"] - ask) / ask * 100, (qk["mid"] - q0["mid"]) / q0["mid"] * 100 if qk.get("mid") and q0.get("mid") else None, k))
    return q0, p


def counterfactual(event, gate, day, cfg, entry_label: str) -> dict | None:
    i, d = event["i"], event["dir"]
    key = (gate["selected_option"], gate["selected_offset"])
    e = i + cfg.entry_offsets[entry_label]
    if e >= len(day):
        return None
    q0, p = _path(day, key, e, cfg.trade_horizon_s)
    if q0 is None:
        return dict(event_id=event["event_id"], entry=entry_label, executable=entry_label in cfg.executable_entries, status="NO_QUOTE")
    ask, mid = q0["ask"], q0["mid"]
    fixed = {}
    for h in cfg.fixed_exits_s:
        pt = next((x for x in p if x[0] == h), None)
        fixed[h] = dict(net=pt[1] if pt else None, gross=pt[2] if pt else None)
    mfe = max(p, key=lambda x: x[1]) if p else None
    mae = min(p, key=lambda x: x[1]) if p else None
    first = lambda lvl: next((t for t, v, _, _ in p if v >= lvl), None)
    exit60 = fixed.get(cfg.trade_horizon_s, {}).get("net")
    peak = mfe[1] if mfe else None
    f_e = F.fmid(day, e)
    # descriptive exit behaviours (time and net return when each first appears; not a rule)
    beh, down, prev = {}, 0, None
    for t, v, _, k in p:
        down = down + 1 if (prev is not None and v < prev) else 0
        prev = v
        fav = ((F.fmid(day, k) or f_e) - f_e) * d if f_e else 0
        if "momentum_failure" not in beh and t >= 10 and down >= 2:
            beh["momentum_failure"] = (t, v)
        if "no_progress" not in beh and t == cfg.no_progress_s and v <= 0:
            beh["no_progress"] = (t, v)
        if "adverse" not in beh and v <= cfg.adverse_pct:
            beh["adverse"] = (t, v)
        if "giveback" not in beh and peak is not None and max(x[1] for x in p if x[0] <= t) >= cfg.giveback_activation_pct \
                and v <= max(x[1] for x in p if x[0] <= t) * cfg.giveback_frac:
            beh["giveback"] = (t, v)
        if "divergence" not in beh and t >= 10 and fav > 0 and v < 0:
            beh["divergence"] = (t, v)
    exit_mid = next((x for x in p if x[0] == cfg.trade_horizon_s), None)
    x_q = day.opt[key][exit_mid[3]] if exit_mid else None
    spread_cost = (((ask - mid) + ((x_q["mid"] - x_q["bid"]) if x_q else 0)) / ask * 100) if mid else None
    # futures move consumed / remaining at entry (OUTCOME measurement)
    on = event.get("onset_i")
    done = (f_e - F.fmid(day, on)) * d if (f_e is not None and on is not None and F.fmid(day, on) is not None) else None
    ahead = max([((F.fmid(day, k) or f_e) - f_e) * d for k in range(e + 1, min(len(day), e + 61))] + [0.0]) if f_e else None
    tot = (max(done or 0, 0) + (ahead or 0))
    return dict(event_id=event["event_id"], event_cluster_id=event["event_cluster_id"], symbol=day.symbol, trade_date=str(day.trade_date),
                entry=entry_label, executable=entry_label in cfg.executable_entries, status="OK", option_type=key[0], strike=day.legs[key]["strike"],
                entry_timestamp=day.known_at(e).isoformat(), entry_ask=ask, entry_mid=mid, entry_bid=q0["bid"], entry_spread_pct=q0.get("spread_pct"),
                entry_futures_mid=f_e, entry_index=day.idx_close[e], exit_timestamp=day.known_at(exit_mid[3]).isoformat() if exit_mid else None,
                exit_bid=x_q["bid"] if x_q else None, gross_return=exit_mid[2] if exit_mid else None, net_return=exit60, spread_cost=spread_cost,
                mfe=peak, mae=mae[1] if mae else None, time_to_mfe=mfe[0] if mfe else None, time_to_mae=mae[0] if mae else None,
                time_to_0_5=first(0.5), time_to_1=first(1.0), time_to_2=first(2.0),
                giveback=(peak - exit60) if (peak is not None and exit60 is not None) else None,
                hit1_before_minus1=_hit_first(p, cfg), **{f"exit_{h}s_net": fixed[h]["net"] for h in cfg.fixed_exits_s},
                **{f"exit_{h}s_gross": fixed[h]["gross"] for h in cfg.fixed_exits_s},
                **{f"beh_{k}_t": v[0] for k, v in beh.items()}, **{f"beh_{k}_ret": v[1] for k, v in beh.items()},
                move_consumed=(max(done, 0) / tot) if (done is not None and tot > 0) else None,
                move_remaining=(ahead / tot) if (ahead is not None and tot > 0) else None,
                decay_event_to_entry=((mid - F.omid(day, key, i)) / F.omid(day, key, i) * 100) if F.omid(day, key, i) else None,
                **{f"decay_entry_to_{h}s": next((x[2] for x in p if x[0] == h), None) for h in (10, 20, 30, 60)})


def _hit_first(p, cfg):
    """+hit_level before -hit_level within the trade horizon (outcome metric only)."""
    for t, v, _, _ in p:
        if t > cfg.trade_horizon_s:
            break
        if v >= cfg.hit_level_pct:
            return True
        if v <= -cfg.hit_level_pct:
            return False
    return False if p else None


def outcomes(event, gate, day, cfg) -> dict:
    """OUTCOME windows from the event bar close (never inputs)."""
    i, d = event["i"], event["dir"]
    f0 = F.fmid(day, i)
    key = (gate["selected_option"], gate["selected_offset"])
    o = {}
    for h in cfg.underlying_horizons_s:
        k = i + h // 5
        o[f"underlying_move_{h}s"] = ((F.fmid(day, k) - f0) * d) if (k < len(day) and F.fmid(day, k) is not None and f0) else None
    for h in cfg.option_horizons_s:
        o[f"option_move_{h}s"] = F.oret(day, key, i + h // 5, h // 5) if i + h // 5 < len(day) else None
    path = [(F.fmid(day, k) - f0) * d for k in range(i + 1, min(len(day), i + 61)) if F.fmid(day, k) is not None and f0]
    o["max_favourable_move"] = max(path) if path else None
    o["max_adverse_move"] = min(path) if path else None
    fav60 = [(F.fmid(day, k) - f0) * d for k in range(i + 3, min(len(day), i + 15)) if F.fmid(day, k) is not None and f0]
    return o, fav60


def outcome_label(cf, fav_after_entry, cfg) -> str | None:
    if cf is None or cf.get("status") != "OK":
        return None
    if not fav_after_entry or max(fav_after_entry) <= 0:
        return "NO_FOLLOW_THROUGH"
    if (cf.get("mfe") or 0) < cfg.profit_levels[0] and (cf.get("mae") or 0) <= cfg.adverse_pct:
        return "FALSE_OPPORTUNITY"
    return "FOLLOW_THROUGH"
