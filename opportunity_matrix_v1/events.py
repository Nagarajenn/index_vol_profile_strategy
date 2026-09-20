"""Research events (Step 6) and lead/lag (Step 7). Event != trade.

An event starts at the first 5-s bar where the 10-s futures-MID move or the 10-s CE-PE
mid response reaches the PRIOR-day p90 (a run of consecutive triggering bars in the same
direction is one event). Everything is decided from bars <= the event bar."""

from datetime import time, timedelta

from opportunity_matrix_v1 import features as F

EVENT_TYPES = ("UP_IMPULSE", "DOWN_IMPULSE", "UP_REVERSAL", "DOWN_REVERSAL", "CONTINUATION", "NO_EVENT")
LEADLAG = ("OPTION_LEAD", "UNDERLYING_LEAD", "SYNCHRONIZED", "FALSE_OPTION_MOVE", "OPTION_RESPONSE_LAG", "UNKNOWN")


def window_of(t, cfg) -> str:
    for name in ("MODE_A_EARLY", "MODE_A_MIDDLE", "MODE_A_LATE", "OPTION_ONLY", "SETUP"):
        a, b = cfg.windows[name]
        if time.fromisoformat(a) <= t < time.fromisoformat(b):
            return name
    return "OUTSIDE"


def _trigger(day, i, th, cfg):
    f10 = F.fmove(day, i, 2)
    ce, pe = F.oret(day, ("CE", 0), i, 2), F.oret(day, ("PE", 0), i, 2)
    syn = (ce - pe) if (ce is not None and pe is not None) else None
    ft = f10 is not None and f10 != 0 and th["r10"].p(cfg.detection_pct) is not None and abs(f10) >= th["r10"].p(cfg.detection_pct)
    ot = syn is not None and th["syn10"].p(cfg.detection_pct) is not None and abs(syn) >= th["syn10"].p(cfg.detection_pct)
    if not (ft or ot):
        return None
    d = (1 if f10 > 0 else -1) if ft else (1 if syn > 0 else -1)
    method = "BOTH" if (ft and ot) else ("FUTURES_MID" if ft else "OPTION_SYNTHETIC")
    return d, method, f10, syn


def detect_events(day, th, cfg) -> list[dict]:
    events, prev = [], None
    for i in range(cfg.lookback_bars + 1, len(day)):
        trg = _trigger(day, i, th, cfg)
        if trg is None:
            prev = None
            continue
        d, method, f10, syn = trg
        if prev == d:                           # continuation of the same triggered run
            continue
        prev = d
        t = day.known_at(i)
        r60p = F.fmove(day, i - 2, 12)
        ctx = th["r60"].p(cfg.context_pct)
        if r60p is not None and ctx is not None and abs(r60p) >= ctx and r60p * d < 0:
            etype = "UP_REVERSAL" if d > 0 else "DOWN_REVERSAL"
        elif r60p is not None and ctx is not None and abs(r60p) >= ctx and r60p * d > 0:
            etype = "CONTINUATION"
        else:
            etype = "UP_IMPULSE" if d > 0 else "DOWN_IMPULSE"
        leg = F.dir_leg(d)
        o10, o5, o5p = F.oret(day, leg, i, 2), F.oret(day, leg, i, 1), F.oret(day, leg, i - 1, 1)
        d1, d1p = F.fmove(day, i, 1), F.fmove(day, i - 1, 1)
        st, stp = (day.trans[i] or {}).get("straddle"), (day.trans[i - 1] or {}).get("straddle") if i else None
        st2 = (day.trans[i - 2] or {}).get("straddle") if i >= 2 else None
        vq, vqp = (day.opt[leg][i] or {}).get("volume"), (day.opt[leg][i - 1] or {}).get("volume")
        bucket_f = th["r10"].bucket(f10, cfg.descriptor_pcts) if f10 is not None else None
        bucket_o = th["syn10"].bucket(syn, cfg.descriptor_pcts) if syn is not None else None
        dq = "GOOD"
        if day.fut_mid[i] is None or day.opt[leg][i] is None:
            dq = "MISSING"
        elif (day.opt[leg][i].get("quote_age") or 0) > cfg.max_quote_age_s:
            dq = "STALE"
        events.append(dict(
            event_id=f"{day.symbol}-{day.trade_date}-{t.strftime('%H%M%S')}", symbol=day.symbol, trade_date=str(day.trade_date),
            symbol_day_id=f"{day.symbol}-{day.trade_date}", i=i, event_timestamp=t.isoformat(), event_time=t.strftime("%H:%M:%S"),
            window=window_of(t.time(), cfg), event_type=etype, direction="UP" if d > 0 else "DOWN", dir=d, detection_method=method,
            detection_percentile=max([b for b in (bucket_f, bucket_o) if b], default=None, key=lambda b: float(b.strip("<p"))),
            futures_return=f10, option_synthetic_return=syn, option_return=o10,
            futures_acceleration=(d1 - d1p) if (d1 is not None and d1p is not None) else None,
            option_acceleration=(o5 - o5p) if (o5 is not None and o5p is not None) else None,
            straddle_acceleration=((st - stp) - (stp - st2)) if (st and stp and st2) else None,
            option_volume_acceleration=(vq / vqp) if (vq is not None and vqp) else None,
            prior_60s_move=r60p, expiry_flag=day.is_expiry, data_quality=dq, news_state=news_state(day, t, cfg)))
    # event clusters (any direction), anchored on the cluster's FIRST event: an event joins the
    # current cluster only if it is within cluster_gap_s of that anchor (no chaining). Events are
    # preserved at event level; cluster-level statistics use one row per cluster.
    cid, anchor = 0, None
    for e in events:
        if anchor is None or (e["i"] - anchor) * cfg.bar_seconds > cfg.cluster_gap_s:
            cid += 1
            anchor = e["i"]
        e["event_cluster_id"] = f"{e['symbol_day_id']}-C{cid:03d}"
    first = {}
    for e in events:
        e["cluster_first"] = e["event_cluster_id"] not in first
        first.setdefault(e["event_cluster_id"], e["event_id"])
    return events


def news_state(day, t, cfg) -> str:
    if not day.news_feed_active:
        return "NEWS_UNKNOWN"
    recent = [n for n in day.news if n[0] <= t and n[0] >= t - timedelta(minutes=cfg.news_lookback_min)]
    return "NEWS_PRESENT" if recent else "NEWS_ABSENT"


def lead_lag(day, i, d, th, cfg) -> dict:
    """Uses only bars <= i. 'Option moved first' is a timing description, not causality."""
    lo = max(1, i - cfg.lookback_bars)
    leg = F.dir_leg(d)
    if any(F.fmid(day, k) is None for k in (lo, i)):
        return dict(lead_lag_class="UNKNOWN", reason="missing futures mid")
    fav = lambda k: ((F.fmid(day, k) or F.fmid(day, lo)) - F.fmid(day, lo)) * d
    onset = min(range(lo, i + 1), key=fav)
    thr_f, thr_o = th["d1"].p(cfg.response_step_pct), th["o5"].p(cfg.response_step_pct)
    first_fut = next((k for k in range(onset + 1, i + 1) if (F.fmove(day, k, 1) or 0) * d >= thr_f and F.fmove(day, k, 1)), None)
    first_ce = next((k for k in range(lo + 1, i + 1) if abs(F.oret(day, ("CE", 0), k, 1) or 0) >= thr_o), None)
    first_pe = next((k for k in range(lo + 1, i + 1) if abs(F.oret(day, ("PE", 0), k, 1) or 0) >= thr_o), None)
    mids = [k for k in range(lo, i + 1) if F.omid(day, leg, k)]
    o_on = min(mids, key=lambda k: F.omid(day, leg, k)) if mids else None
    first_opt = next((k for k in range(o_on + 1, i + 1) if (F.oret(day, leg, k, 1) or 0) >= thr_o), None) if o_on is not None else None
    if first_fut is not None and first_opt is not None:
        lag = first_opt - first_fut
        cls = "SYNCHRONIZED" if abs(lag) <= cfg.sync_bars else ("OPTION_LEAD" if lag < 0 else "UNDERLYING_LEAD")
    elif first_opt is not None:
        cls = "FALSE_OPTION_MOVE"
    elif first_fut is not None:
        cls = "OPTION_RESPONSE_LAG"
    else:
        cls = "UNKNOWN"
    ts = lambda k: day.known_at(k).strftime("%H:%M:%S") if k is not None else None
    persistence = 0
    for k in range(i, lo, -1):
        if (F.fmove(day, k, 1) or 0) * d > 0:
            persistence += 1
        else:
            break
    return dict(lead_lag_class=cls, event_start=ts(onset), onset_age_s=(i - onset) * cfg.bar_seconds,
                first_underlying_time=ts(first_fut), first_ce_move_time=ts(first_ce), first_pe_move_time=ts(first_pe),
                first_option_time=ts(first_opt),
                lead_lag_seconds=((first_fut - first_opt) * cfg.bar_seconds) if (first_fut is not None and first_opt is not None) else None,
                persistence_bars=persistence, onset_i=onset)
