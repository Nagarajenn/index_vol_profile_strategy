"""Option response (Step 8) and strike-universe records (option selection research).
All measurements at an event use bars <= the event bar (responses are BACKWARD-looking).
Strike records for an entry use data known at that entry bar only."""

from opportunity_matrix_v1 import features as F

CLASSES = ("STRONG", "MODERATE", "WEAK", "NONE", "CONTRADICTORY")


def response_class(day, i, d, th, cfg) -> str:
    r10 = F.oret(day, F.dir_leg(d), i, 2)
    if r10 is None:
        return "NONE"
    if r10 < 0 and abs(r10) >= th["o10"].p(cfg.weak_pct):
        return "CONTRADICTORY"
    if r10 >= th["o10"].p(cfg.strong_pct):
        return "STRONG"
    if r10 >= th["o10"].p(cfg.moderate_pct):
        return "MODERATE"
    if r10 >= th["o10"].p(cfg.weak_pct):
        return "WEAK"
    return "NONE"


def event_atm_offset(day, i) -> int:
    """Strike nearest the futures mid at bar i (causal); falls back to the band ATM."""
    m = F.fmid(day, i)
    if m is None:
        return 0
    return max(-5, min(5, round((m - day.band_atm) / day.strike_step)))


def option_response_rows(event, day, th, cfg) -> list[dict]:
    i, d = event["i"], event["dir"]
    rows = []
    fm = F.fmid(day, i)
    for (typ, off), leg in sorted(day.legs.items()):
        q = day.opt[(typ, off)][i] if i < len(day.opt[(typ, off)]) else None
        if q is None:
            continue
        r = {h: F.oret(day, (typ, off), i, h // cfg.bar_seconds) for h in cfg.response_horizons_s}
        u = {h: F.fmove(day, i, h // cfg.bar_seconds) for h in cfg.response_horizons_s}
        o5, o5p = F.oret(day, (typ, off), i, 1), F.oret(day, (typ, off), i - 1, 1)
        pers = 0
        for k in range(i, max(0, i - cfg.lookback_bars), -1):
            a, b = F.omid(day, (typ, off), k), F.omid(day, (typ, off), k - 1)
            if a is not None and b is not None and a > b:
                pers += 1
            else:
                break
        vol = sum(((day.opt[(typ, off)][k] or {}).get("volume") or 0) for k in range(max(0, i - 2), i + 1))
        oic = sum(((day.opt[(typ, off)][k] or {}).get("oi_delta") or 0) for k in range(max(0, i - 5), i + 1))
        und10 = (u[10] / fm * 100) if (u.get(10) is not None and fm) else None
        rows.append(dict(event_id=event["event_id"], symbol=day.symbol, strike=leg["strike"], option_type=typ, atm_offset=off,
                         direction_leg=(typ == ("CE" if d > 0 else "PE")),
                         **{f"response_{h}s": r[h] for h in cfg.response_horizons_s},
                         **{f"underlying_{h}s": u[h] for h in cfg.response_horizons_s},
                         relative_response_10s=(r[10] / und10) if (r.get(10) is not None and und10) else None,
                         acceleration=(o5 - o5p) if (o5 is not None and o5p is not None) else None, persistence=pers,
                         spread_pct=q.get("spread_pct"), quote_age=q.get("quote_age"), volume=vol, oi=q.get("oi"), oi_change=oic))
    return rows


def strike_universe(day, e_idx: int, d: int, cfg) -> list[dict]:
    """All ATM+/-5 CE/PE quotes as known at the ENTRY bar (greeks from the latest 1-min chain
    snapshot fetched at or before that bar's close)."""
    T = day.known_at(e_idx)
    out = []
    for (typ, off), leg in sorted(day.legs.items()):
        q = day.opt[(typ, off)][e_idx]
        if q is None:
            continue
        g = F.greeks_at(day.chain, T, leg["strike"], typ)
        out.append(dict(strike=leg["strike"], option_type=typ, atm_offset=off, moneyness_steps=off if typ == "CE" else -off,
                        premium=q.get("ask"), bid=q.get("bid"), ask=q.get("ask"), mid=q.get("mid"),
                        spread=(q["ask"] - q["bid"]) if q.get("ask") and q.get("bid") else None, spread_pct=q.get("spread_pct"),
                        volume=sum(((day.opt[(typ, off)][k] or {}).get("volume") or 0) for k in range(max(0, e_idx - 2), e_idx + 1)),
                        oi=q.get("oi"), oi_change=sum(((day.opt[(typ, off)][k] or {}).get("oi_delta") or 0) for k in range(max(0, e_idx - 5), e_idx + 1)),
                        quote_age=q.get("quote_age"), **g))
    return out


def liquidity_ok(day, key, i, cfg) -> tuple[bool, str | None]:
    q = day.opt.get(key, [None])[i] if key in day.opt and i < len(day.opt[key]) else None
    if q is None or not q.get("bid") or not q.get("ask"):
        return False, "NO_TWO_SIDED_QUOTE"
    if (q.get("spread_pct") or 99) > cfg.max_spread_pct:
        return False, "SPREAD_TOO_WIDE"
    if (q.get("quote_age") or 0) > cfg.max_quote_age_s:
        return False, "STALE_QUOTE"
    vol = sum(((day.opt[key][k] or {}).get("volume") or 0) for k in range(max(0, i - cfg.min_volume_bars + 1), i + 1))
    if vol <= 0:
        return False, "NO_RECENT_VOLUME"
    return True, None
