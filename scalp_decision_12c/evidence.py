"""The eight evidence categories. Each one is an independent observation with a state,
the numbers behind it and a plain-English note. Nothing is combined into a hidden score.

Every category reads only information observable at the decision minute T: the 12B minute
view at T (built from snapshots <= T) and candles that ended at or before T.
"""

from option_risk_12b.option_pressure import oi_price_state, side_flow
from option_risk_12b.option_snapshot import shift
from option_risk_12b.option_state import diff, leg, pct

BULLISH, BEARISH, NEUTRAL = "UNDERLYING_BULLISH", "UNDERLYING_BEARISH", "UNDERLYING_NEUTRAL"
STALE, MISSING = "UNDERLYING_STALE", "UNDERLYING_MISSING"
CALL_RS, PUT_RS = "CALL_RELATIVE_STRENGTH", "PUT_RELATIVE_STRENGTH"
EXPANSION, CONTRACTION, BALANCED = "MOVEMENT_EXPANSION", "PREMIUM_CONTRACTION", "BALANCED"
INSUFFICIENT = "INSUFFICIENT_DATA"


def _cat(name, state, detail, note):
    return dict(category=name, state=state, detail=detail, note=note)


# ---------------------------------------------------------------- 1. underlying
def underlying_direction(view, und_all, levels, symbol, cfg) -> dict:
    u = view["underlying"]
    m = view["minute"]
    eps = cfg.min_move_pts.get(symbol, 8.0)
    near = cfg.level_proximity_pts.get(symbol, 10.0)
    px = u["value"]
    rets, ctx = {}, []
    if u["state"] == "MISSING":
        return _cat("UNDERLYING", MISSING, dict(price=None), "No underlying print is available; it is not treated as neutral.")
    for k in cfg.underlying_windows_min:
        p = und_all.get(shift(m, -k))
        rets[f"ret_{k}m"] = (px - p["value"]) if (p and p["value"] is not None and px is not None
                                                  and u["state"] == "LIVE" and p["state"] == "LIVE") else None
    if u["state"] != "LIVE":
        return _cat("UNDERLYING", STALE, dict(price=px, last_reliable=u["last_reliable_value"], age_minutes=u["age_minutes"],
                                              underlying_state=u["state"], **rets),
                    f"Underlying reference is {u['state']} (age {u['age_minutes']} min); option-chain evidence only.")
    r3 = rets.get("ret_3m")
    vwap = (levels or {}).get("vwap_now")
    poc = (levels or {}).get("today_poc")
    votes = 0
    if r3 is not None and abs(r3) >= eps:
        votes += 1 if r3 > 0 else -1
        ctx.append(f"3-minute move {r3:+.1f} pts")
    if vwap and px:
        votes += 1 if px > vwap else -1
        ctx.append(f"{'above' if px > vwap else 'below'} VWAP")
    if poc and px:
        votes += 1 if px > poc else -1
        ctx.append(f"{'above' if px > poc else 'below'} today's POC")
    state = BULLISH if votes >= 2 else BEARISH if votes <= -2 else NEUTRAL
    res, sup = (levels or {}).get("resistance_low"), (levels or {}).get("support_high")
    at_level = None
    if px and res and abs(px - res) <= near:
        at_level = "AT_RESISTANCE"
        ctx.append(f"price within {near:g} pts of resistance {res:g}")
    elif px and sup and abs(px - sup) <= near:
        at_level = "AT_SUPPORT"
        ctx.append(f"price within {near:g} pts of support {sup:g}")
    return _cat("UNDERLYING", state, dict(price=px, vwap=vwap, poc=poc, at_level=at_level, underlying_state="LIVE",
                                          trend_label=(levels or {}).get("trend_label"), **rets),
                "; ".join(ctx) or "No directional underlying evidence.")


# ---------------------------------------------------------------- 2. option relative strength
def option_relative(view, cfg) -> dict:
    p = view["pressure"]
    ce, pe = p.get("ce_premium_pct_3m"), p.get("pe_premium_pct_3m")
    thr = cfg.premium_move_pct
    if ce is None or pe is None:
        return _cat("OPTION_RELATIVE", INSUFFICIENT, dict(ce_3m=ce, pe_3m=pe), "Not enough option history for a CE/PE comparison.")
    if ce >= thr and pe >= thr:
        st = EXPANSION
        note = f"Both sides strengthening (CE {ce:+.2f}%, PE {pe:+.2f}%): movement expansion, direction unclear."
    elif ce <= -thr and pe <= -thr:
        st = CONTRACTION
        note = f"Both sides weakening (CE {ce:+.2f}%, PE {pe:+.2f}%): premium contraction, direction unclear."
    elif ce - pe >= thr and ce > 0:
        st = CALL_RS
        note = f"CE outperforming PE over 3 minutes (CE {ce:+.2f}% vs PE {pe:+.2f}%)."
    elif pe - ce >= thr and pe > 0:
        st = PUT_RS
        note = f"PE outperforming CE over 3 minutes (PE {pe:+.2f}% vs CE {ce:+.2f}%)."
    else:
        st = BALANCED
        note = f"Neither side clearly outperforming (CE {ce:+.2f}%, PE {pe:+.2f}%)."
    return _cat("OPTION_RELATIVE", st, dict(ce_3m=ce, pe_3m=pe, spread=ce - pe,
                                            call_relative_strength=p.get("CALL_RELATIVE_STRENGTH")), note)


# ---------------------------------------------------------------- 3. premium momentum
def _one_min_changes(series, minute, typ, strike, k):
    out = []
    for j in range(k):
        m = shift(minute, -j)
        a, b = leg(series, m, typ, strike), leg(series, shift(m, -1), typ, strike)
        out.append(pct(a["mid"], b["mid"]) if (a and b) else None)
    return out


def momentum(view, series, typ, cfg) -> dict:
    strike = view["atm_strike"]
    tr = (view["trajectory"] or {}).get(f"{typ.lower()}_premium") or {}
    c1, c3, c5 = tr.get("chg_1m"), tr.get("chg_3m"), tr.get("chg_5m")
    label = tr.get("label", INSUFFICIENT)
    recent = _one_min_changes(series, view["minute"], typ, strike, cfg.persistence_window) if strike is not None else []
    known = [x for x in recent if x is not None]
    same = sum(1 for x in known if c3 is not None and x * c3 > 0)
    persistent = len(known) >= cfg.persistence_min and same >= cfg.persistence_min
    spike = bool(c1 is not None and c3 is not None and abs(c3) > 0 and abs(c1) >= cfg.spike_ratio * abs(c3) and not persistent)
    if c3 is None:
        note = "Not enough option history for a momentum reading."
    elif spike:
        note = f"{typ} moved {c1:+.2f}% in one minute without follow-through ({same}/{len(known)} recent minutes agree): treated as a spike."
    else:
        note = (f"{typ} premium {c3:+.2f}% over 3 minutes, {label.lower()}, "
                f"{'persistent' if persistent else 'not persistent'} ({same}/{len(known)} recent minutes agree).")
    return _cat(f"{typ}_MOMENTUM", label, dict(chg_1m=c1, chg_3m=c3, chg_5m=c5, persistent=persistent, spike=spike,
                                               recent_1m_changes=recent, acceleration=tr.get("acceleration")), note)


# ---------------------------------------------------------------- 4. participation (volume)
def participation(view, series, cfg) -> dict:
    strike = view["atm_strike"]
    out, notes = {}, []
    for typ in ("CE", "PE"):
        # Traded volume is cumulative, so a minute-on-minute difference can only be >= 0.
        # A negative value means the two snapshots are not comparable (e.g. across the gap
        # after 15:30); it is dropped as unavailable, never shown as negative participation.
        f = side_flow(series, view["minute"], typ, [strike]) if strike is not None else None
        f = None if (f is not None and f < 0) else f
        trail = [side_flow(series, shift(view["minute"], -j), typ, [strike]) for j in range(1, 6)] if strike is not None else []
        trail = [x for x in trail if x is not None and x >= 0]
        base = sum(trail) / len(trail) if trail else None
        ratio = (f / base) if (f is not None and base) else None
        out[f"{typ.lower()}_volume"] = f
        out[f"{typ.lower()}_ratio"] = ratio
    ce_r, pe_r = out["ce_ratio"], out["pe_ratio"]
    if ce_r is None or pe_r is None:
        return _cat("PARTICIPATION", INSUFFICIENT, out, "Option volume history is incomplete.")
    ce_strong = ce_r >= cfg.volume_strong_ratio
    pe_strong = pe_r >= cfg.volume_strong_ratio
    if ce_strong and not pe_strong:
        st = "CE_STRONG"
    elif pe_strong and not ce_strong:
        st = "PE_STRONG"
    elif ce_r <= cfg.volume_weak_ratio and pe_r <= cfg.volume_weak_ratio:
        st = "WEAK"
    else:
        st = "MIXED"
    notes.append(f"CE volume {ce_r:.2f}x and PE volume {pe_r:.2f}x their own 5-minute averages")
    return _cat("PARTICIPATION", st, out, "; ".join(notes) + ". Volume is read as participation, not direction.")


# ---------------------------------------------------------------- 5. OI / premium relationship
def oi_relationship(view, series, cfg) -> dict:
    strike = view["atm_strike"]
    detail = {}
    for typ in ("CE", "PE"):
        a, b = leg(series, view["minute"], typ, strike), leg(series, shift(view["minute"], -3), typ, strike)
        oi3 = pct(a["oi"], b["oi"]) if (a and b) else None
        pr3 = pct(a["mid"], b["mid"]) if (a and b) else None
        rel, _ = oi_price_state(oi3, pr3, cfg.oi_move_pct, cfg.premium_move_pct)
        detail[f"{typ.lower()}_oi_pct_3m"] = oi3
        detail[f"{typ.lower()}_premium_pct_3m"] = pr3
        detail[f"{typ.lower()}_relation"] = rel
    note = (f"CE {detail['ce_relation'].replace('_', ' ').lower()}, PE {detail['pe_relation'].replace('_', ' ').lower()} "
            "(OI read together with premium, never alone).")
    return _cat("OI_RELATIONSHIP", "READ", detail, note)


def oi_vote(oi_cat, side: str) -> str:
    """CONFIRMING / CONTRADICTING / NEUTRAL for buying `side`."""
    own = oi_cat["detail"].get(f"{side.lower()}_relation")
    if own in ("LONG_BUILDUP",):
        return "CONFIRMING"
    if own in ("SHORT_BUILDUP", "LONG_UNWINDING"):
        return "CONTRADICTING"
    return "NEUTRAL"


# ---------------------------------------------------------------- 6. liquidity / execution
def liquidity(view, side: str, cfg, entry_spread_pct=None) -> dict:
    q = view[side.lower()]
    sp = q.get("spread_pct")
    bq, aq = q.get("bid_qty"), q.get("ask_qty")
    if q.get("status") != "OK" or sp is None or q.get("mid") is None:
        return _cat("LIQUIDITY", "POOR", dict(spread_pct=sp, reason="NO_TWO_SIDED_QUOTE"),
                    f"No usable two-sided quote for the {side} leg.")
    widened = bool(entry_spread_pct and sp >= cfg.spread_widening_ratio * entry_spread_pct)
    if sp >= cfg.wide_spread_pct or widened:
        st = "POOR"
    elif sp <= cfg.good_spread_pct:
        st = "GOOD"
    else:
        st = "ACCEPTABLE"
    note = f"{side} spread {sp:.2f}%" + (f" (entry {entry_spread_pct:.2f}%)" if entry_spread_pct else "")
    if bq is not None and aq is not None:
        note += f", bid/ask quantity {bq:g}/{aq:g}"
    return _cat("LIQUIDITY", st, dict(spread_pct=sp, bid_qty=bq, ask_qty=aq, widened_vs_entry=widened,
                                      bid=q.get("bid"), ask=q.get("ask")), note + ".")


# ---------------------------------------------------------------- 7. straddle
def straddle(view, cfg) -> dict:
    tr = (view["trajectory"] or {}).get("straddle") or {}
    c3 = tr.get("chg_3m")
    if c3 is None:
        return _cat("STRADDLE", INSUFFICIENT, dict(value=tr.get("value")), "No straddle history yet.")
    st = "EXPANDING" if c3 >= cfg.straddle_move_pct else "CONTRACTING" if c3 <= -cfg.straddle_move_pct else "FLAT"
    severe = c3 <= cfg.severe_contraction_pct
    return _cat("STRADDLE", st, dict(value=tr.get("value"), chg_3m=c3, severe_contraction=severe),
                f"ATM straddle {c3:+.2f}% over 3 minutes" + (" (severe premium contraction)" if severe else "") +
                ". Used as movement confirmation, not direction.")


# ---------------------------------------------------------------- 8. data quality
def data_quality(view) -> dict:
    u, act = view["underlying"], view["option_activity"]
    flags = list(view["data_quality"])
    greeks = {t: view[t].get("greeks_status") for t in ("ce", "pe")}
    st = "OK" if not flags else ("DEGRADED" if "MISSING_OPTION_DATA" not in flags else "INSUFFICIENT")
    return _cat("DATA_QUALITY", st, dict(underlying_state=u["state"], underlying_age_minutes=u["age_minutes"],
                                         options=act["status"], flags=flags, greeks_status=greeks,
                                         snapshot_present=view["snapshot_present"]),
                f"Underlying {u['state']}, options {act['status']}" + (f", flags: {', '.join(flags)}" if flags else "") +
                ". Missing Greeks are left unavailable, never replaced with zero.")


def build(view, series, und_all, levels, symbol, cfg, entry_spread_pct=None) -> dict:
    return dict(
        underlying=underlying_direction(view, und_all, levels, symbol, cfg),
        option_relative=option_relative(view, cfg),
        ce_momentum=momentum(view, series, "CE", cfg),
        pe_momentum=momentum(view, series, "PE", cfg),
        participation=participation(view, series, cfg),
        oi=oi_relationship(view, series, cfg),
        liquidity_ce=liquidity(view, "CE", cfg, entry_spread_pct),
        liquidity_pe=liquidity(view, "PE", cfg, entry_spread_pct),
        straddle=straddle(view, cfg),
        data_quality=data_quality(view),
    )
