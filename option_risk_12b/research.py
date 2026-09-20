"""Historical 12B research over every day with option-chain data (read-only).

Outcomes (the next reliable underlying print, the official close, forward option paths)
are computed HERE and only here; they are never fed back into any per-minute state,
pressure, risk label or threshold. Signals are always taken at minutes strictly before
the outcome becomes observable.

Reference positions: 11D has no historical paper positions (paper_positions is empty),
so the risk-monitor study uses clearly-labelled HYPOTHETICAL reference positions
(ATM BUY CE and ATM BUY PE). They are not paper trades and are not 11D.
"""

import statistics
from collections import Counter, defaultdict

from scipy import stats

from option_risk_12b.closing_state import LIVE, MISSING, STALE, UNCERTAIN
from option_risk_12b.engine import build_session, minute_view, prepare, truncate
from option_risk_12b.closing_state import underlying_states
from option_risk_12b.option_snapshot import minute_range, resolve_atm, shift, strike_window
from option_risk_12b.option_state import leg

NON_LIVE = (STALE, UNCERTAIN, MISSING)


def med(xs):
    xs = [x for x in xs if x is not None]
    return statistics.median(xs) if xs else None


def sign(x, eps=0.0):
    if x is None:
        return None
    return 0 if abs(x) <= eps else (1 if x > 0 else -1)


# ---------------------------------------------------------------- data audit
def data_audit(symbol, d, snaps, cfg) -> dict:
    series, _ = prepare(snaps, [])
    win = minute_range(cfg.window_start, cfg.window_end)
    ext = minute_range(shift(cfg.window_end, 1), "15:39")
    after = sorted(m for m in series if m >= cfg.window_start)
    legs_tot = Counter()
    atm_ok = 0
    for m in win:
        s = series.get(m)
        if not s:
            continue
        atm, _ = resolve_atm(s)
        if atm is None:
            continue
        atm_ok += 1
        for k in strike_window(s, atm, cfg.strikes_each_side):
            for t in ("CE", "PE"):
                q = s["legs"].get((t, k))
                legs_tot["legs"] += 1
                if not q:
                    continue
                legs_tot[f"{t}_present"] += 1
                legs_tot["bid_ask"] += q["mid"] is not None
                legs_tot["oi"] += q["oi"] is not None
                legs_tot["volume"] += q["volume"] is not None
                legs_tot["iv"] += bool(q["iv_raw"]) and q["iv_raw"] > 0
                legs_tot["greeks_valid"] += q["greeks_status"] == "VALID"
    n = legs_tot["legs"] or 1
    per_side = n / 2
    return dict(symbol=symbol, date=str(d), first_snapshot_after_1515=after[0] if after else None,
                last_snapshot=after[-1] if after else None, snapshots_1515_1530=sum(m in series for m in win),
                expected_minutes_1515_1530=len(win), missing_minutes_1515_1530=[m for m in win if m not in series],
                snapshots_1531_1539=sum(m in series for m in ext), missing_minutes_1531_1539=[m for m in ext if m not in series],
                atm_available_minutes=atm_ok, ce_available_pct=100 * legs_tot["CE_present"] / per_side,
                pe_available_pct=100 * legs_tot["PE_present"] / per_side, bid_ask_available_pct=100 * legs_tot["bid_ask"] / n,
                oi_available_pct=100 * legs_tot["oi"] / n, volume_available_pct=100 * legs_tot["volume"] / n,
                iv_available_pct=100 * legs_tot["iv"] / n, greeks_valid_pct=100 * legs_tot["greeks_valid"] / n,
                expiry=str(next(iter(series.values()))["expiry"]) if series else None)


# ---------------------------------------------------------------- trajectory rows (CSV)
def trajectory_rows(out: dict, cfg) -> list[dict]:
    rows = []
    for r in out["minutes"]:
        if r["minute"] < cfg.window_start:
            continue
        ce, pe, u, tr, p, imp = r["ce"], r["pe"], r["underlying"], r["trajectory"] or {}, r["pressure"], r["implied"]
        g = lambda x, k: x.get(k) if isinstance(x, dict) else None
        rows.append(dict(symbol=out["symbol"], date=out["session_date"], timestamp=r["minute"], underlying_state=u["state"],
                         underlying_price=u["value"], underlying_age=u["age_minutes"], closing_state=r["closing_state"],
                         combination_state=r["combination_state"], atm_strike=r["atm_strike"],
                         ce_premium=g(ce, "mid"), pe_premium=g(pe, "mid"), ce_premium_change=g(ce, "premium_change_pct"),
                         pe_premium_change=g(pe, "premium_change_pct"), ce_volume=g(ce, "volume"), pe_volume=g(pe, "volume"),
                         ce_intraday_oi_change=g(ce, "intraday_oi_change"), pe_intraday_oi_change=g(pe, "intraday_oi_change"),
                         ce_iv=g(ce, "iv"), pe_iv=g(pe, "iv"), ce_delta=g(ce, "delta"), pe_delta=g(pe, "delta"),
                         ce_gamma=g(ce, "gamma"), pe_gamma=g(pe, "gamma"), ce_theta=g(ce, "theta"), pe_theta=g(pe, "theta"),
                         ce_vega=g(ce, "vega"), pe_vega=g(pe, "vega"), ce_spread_pct=g(ce, "spread_pct"), pe_spread_pct=g(pe, "spread_pct"),
                         pcr=g(tr.get("pcr", {}), "value"), atm_straddle=g(tr.get("straddle", {}), "value"),
                         ce_premium_trajectory=g(tr.get("ce_premium", {}), "label"), pe_premium_trajectory=g(tr.get("pe_premium", {}), "label"),
                         ce_pressure=p.get("CE_PRESSURE"), pe_pressure=p.get("PE_PRESSURE"),
                         option_directional_pressure=p.get("OPTION_DIRECTIONAL_PRESSURE"), option_pressure_label=p.get("label"),
                         position_support=None, risk_state=None, implied_spot=imp.get("implied_spot"),
                         implied_spot_gap=imp.get("gap_points"), implied_quality=imp.get("quality"),
                         data_quality="|".join(r["data_quality"]) or "OK"))
    return rows


# ---------------------------------------------------------------- next reliable print study
def next_print(out, candles_map, daily_close, cfg) -> dict | None:
    rows = {r["minute"]: r for r in out["minutes"]}
    win = [m for m in minute_range(cfg.window_start, cfg.window_end) if m in rows]
    s0 = next((m for m in win if rows[m]["underlying"]["state"] == STALE), None)
    if s0 is None:
        return None
    frozen = rows[s0]["underlying"]["last_reliable_value"]
    frozen_min = rows[s0]["underlying"]["last_reliable_minute"]
    if frozen is None:
        return None
    pv = known = None
    src = None
    for m in minute_range(s0, "15:39"):
        c = candles_map.get(m)
        if c and c["close"] is not None and c["close"] != frozen:
            pv, known, src = c["close"], shift(m, 1), "FIRST_CHANGED_1MIN_CANDLE"
            break
    if pv is None and daily_close is not None:
        pv, known, src = daily_close, "EOD", "OFFICIAL_DAILY_CLOSE_FALLBACK"
    if pv is None:
        return None
    return dict(stale_start=s0, frozen_value=frozen, frozen_minute=frozen_min, print_value=pv, print_known_at=known,
                print_source=src, print_move=pv - frozen, official_close=daily_close,
                close_minus_print=(daily_close - pv) if daily_close is not None else None)


def next_print_signals(out, series, np_row, cfg) -> list[dict]:
    """Option signals at 5 / 10 / ~15 minutes after the stale start, each taken strictly before the
    next reliable print is observable (otherwise excluded)."""
    rows = {r["minute"]: r for r in out["minutes"]}
    s0 = np_row["stale_start"]
    base = rows[s0]
    atm0 = base["atm_strike"]
    imp0 = base["implied"]["implied_spot"]
    res = []
    for h, t in ((5, shift(s0, 5)), (10, shift(s0, 10)), (15, min(shift(s0, 15), "15:29"))):
        t = max((m for m in rows if m <= t and rows[m]["snapshot_present"]), default=None)
        if t is None or t <= s0:
            continue
        if np_row["print_known_at"] != "EOD" and t >= np_row["print_known_at"]:
            continue                     # not strictly before the print -- excluded (leakage guard)
        r = rows[t]
        imp_t = r["implied"]["implied_spot"]
        ce, pe, rel = rel_premium(series, s0, t, atm0) if atm0 is not None else (None, None, None)
        res.append(dict(horizon_min=h, signal_minute=t,
                        implied_change=(imp_t - imp0) if (imp_t is not None and imp0 is not None) else None,
                        implied_gap=r["implied"]["gap_points"], odp=r["pressure"].get("OPTION_DIRECTIONAL_PRESSURE"),
                        odp_label=r["pressure"].get("label"), ce_change_pct=ce, pe_change_pct=pe, ce_minus_pe_pct=rel))
    return res


def rel_premium(series, s0, t, atm0):
    """CE% - PE% for the ATM contracts fixed at the stale start."""
    a0, b0 = leg(series, s0, "CE", atm0), leg(series, s0, "PE", atm0)
    a1, b1 = leg(series, t, "CE", atm0), leg(series, t, "PE", atm0)
    if not (a0 and b0 and a1 and b1 and a0["mid"] and b0["mid"] and a1["mid"] and b1["mid"]):
        return None, None, None
    ce = (a1["mid"] / a0["mid"] - 1) * 100
    pe = (b1["mid"] / b0["mid"] - 1) * 100
    return ce, pe, ce - pe


def hit_table(recs, key, move_eps) -> dict:
    """recs: dicts with key (signal value) and 'print_move'. Neutral signals / flat moves are excluded and counted."""
    used = [(sign(r[key]), sign(r["print_move"], move_eps)) for r in recs if r.get(key) is not None]
    excl_signal = sum(1 for s, m in used if s == 0)
    excl_move = sum(1 for s, m in used if s != 0 and m == 0)
    pairs = [(s, m) for s, m in used if s != 0 and m != 0]
    n = len(pairs)
    hits = sum(1 for s, m in pairs if s == m)
    p = stats.binomtest(hits, n, 0.5).pvalue if n else None
    ups = sum(1 for _, m in pairs if m > 0)
    base = max(ups, n - ups) / n if n else None           # always-guess-the-majority-direction baseline
    pb = stats.binomtest(hits, n, base, alternative="greater").pvalue if (n and base < 1) else None
    return dict(n=n, hits=hits, hit_rate=(100 * hits / n) if n else None, binomial_p_vs_50=p,
                majority_baseline_pct=100 * base if base is not None else None, binomial_p_vs_majority=pb,
                excluded_neutral_signal=excl_signal, excluded_flat_print=excl_move,
                median_signal=med([r[key] for r in recs if r.get(key) is not None]),
                median_abs_print_move=med([abs(r["print_move"]) for r in recs]))


# ---------------------------------------------------------------- event study
def event_study(out, cfg, symbol) -> list[dict]:
    rows = [r for r in out["minutes"]]
    thr = cfg.underlying_move_pts.get(symbol, 5.0)
    by = {r["minute"]: r for r in rows}
    ev = []
    for r in rows:
        m, p1 = r["minute"], by.get(shift(r["minute"], -1))
        if not p1 or not r["snapshot_present"] or not p1["snapshot_present"]:
            continue
        u, u1 = r["underlying"], p1["underlying"]
        du = (u["value"] - u1["value"]) if (u["state"] == LIVE and u1["state"] == LIVE and u["value"] is not None and u1["value"] is not None) else None
        i0, i1 = r["implied"]["implied_spot"], p1["implied"]["implied_spot"]
        di = (i0 - i1) if (i0 is not None and i1 is not None) else None
        und_moved = du is not None and abs(du) >= thr
        opt_moved = di is not None and abs(di) >= thr
        und_live = u["state"] == LIVE
        prev_opt = [by.get(shift(m, -k)) for k in (1, 2)]
        prev_opt_moved = any(x and x["implied"]["implied_spot"] is not None and by.get(shift(x["minute"], -1)) and
                             by[shift(x["minute"], -1)]["implied"]["implied_spot"] is not None and
                             abs(x["implied"]["implied_spot"] - by[shift(x["minute"], -1)]["implied"]["implied_spot"]) >= thr
                             for x in prev_opt)
        if not und_live and opt_moved:
            cls, direction = "D_UNDERLYING_STALE_OPTIONS_MOVED", sign(di)
        elif und_moved and opt_moved and sign(du) == sign(di):
            cls, direction = "C_BOTH_MOVED_TOGETHER", sign(du)
        elif und_moved and not opt_moved and not prev_opt_moved:
            cls, direction = "A_UNDERLYING_MOVED_FIRST", sign(du)
        elif opt_moved and und_live and not und_moved:
            cls, direction = "B_OPTIONS_MOVED_FIRST", sign(di)
        elif und_moved or opt_moved:
            cls, direction = "E_INCONCLUSIVE", None
        else:
            continue
        # did the option movement precede the next reliable underlying observation in the same direction?
        follow = None
        if cls in ("B_OPTIONS_MOVED_FIRST", "D_UNDERLYING_STALE_OPTIONS_MOVED"):
            base = u["last_reliable_value"] if not und_live else u["value"]
            for k in range(1, 20):
                nx = by.get(shift(m, k))
                if nx is None:
                    break
                nu = nx["underlying"]
                if nu["value"] is not None and base is not None and nu["value"] != base and nu["state"] in (LIVE, UNCERTAIN):
                    mv = nu["value"] - base
                    follow = dict(next_minute=nx["minute"], next_move=mv, same_direction=sign(mv) == direction if abs(mv) >= thr else None)
                    break
        ce, pe = r["ce"], r["pe"]
        tr = r["trajectory"] or {}
        ev.append(dict(symbol=symbol, date=out["session_date"], minute=m, event_class=cls, direction=direction,
                       underlying_state=u["state"], underlying_change=du, implied_change=di,
                       ce_change_pct=ce.get("premium_change_pct"), pe_change_pct=pe.get("premium_change_pct"),
                       option_pressure=r["pressure"].get("OPTION_DIRECTIONAL_PRESSURE"),
                       ce_oi_change=ce.get("intraday_oi_change"), pe_oi_change=pe.get("intraday_oi_change"),
                       ce_volume_accel=ce.get("volume_acceleration"), pe_volume_accel=pe.get("volume_acceleration"),
                       ce_iv_change=(tr.get("ce_iv") or {}).get("chg_1m"), pe_iv_change=(tr.get("pe_iv") or {}).get("chg_1m"),
                       ce_spread_change=None if not (ce.get("spread_pct") and p1["ce"].get("spread_pct")) else ce["spread_pct"] - p1["ce"]["spread_pct"],
                       next_reliable_minute=follow["next_minute"] if follow else None,
                       next_reliable_move=follow["next_move"] if follow else None,
                       preceded_same_direction=follow["same_direction"] if follow else None))
    return ev


# ---------------------------------------------------------------- reference-position warning study
def reference_positions(series, candles, symbol, d, cfg, cohorts) -> list[dict]:
    """cohorts: [(name, entry_minute, exit_minute)]. ATM resolved from the entry-minute snapshot."""
    out = []
    und_all = underlying_states(series, candles, minute_range(cfg.lookback_start, cfg.window_end), cfg)
    for name, em, xm in cohorts:
        s = series.get(em)
        if not s:
            continue
        atm, _ = resolve_atm(s)
        if atm is None:
            continue
        for typ in ("CE", "PE"):
            e = leg(series, em, typ, atm)
            if not e or not e["mid"]:
                continue
            pos = dict(option_type=typ, strike=atm, entry_minute=em, exit_minute=xm, entry_spread_pct=e["spread_pct"],
                       label=f"REFERENCE {name} BUY {symbol} {typ} {atm:g} (hypothetical)")
            path = []
            for m in minute_range(em, xm):
                if m not in und_all:
                    continue
                v = minute_view(series, candles, m, und_all, d, symbol, cfg, [pos])
                q = leg(series, m, typ, atm)
                rk = v["position_risk"][0] if v["position_risk"] else None
                path.append(dict(minute=m, mid=q["mid"] if q else None, bid=q["bid"] if q else None,
                                 risk=rk["risk_state"] if rk else None, action=rk["risk_action"] if rk else None,
                                 support=rk["position_support"] if rk else None, n_neg=rk.get("n_negative") if rk else None,
                                 data_unreliable=bool(rk and "DATA_UNRELIABLE" in rk["negative"])))
            out.append(dict(symbol=symbol, date=str(d), cohort=name, option_type=typ, strike=atm, entry_minute=em,
                            exit_minute=xm, entry_mid=e["mid"], entry_ask=e["ask"], path=path))
    return out


def forward(path, i, horizon=None):
    """Forward option-mid path statistics from index i (exclusive) to i + horizon minutes (or the end of the
    holding window when horizon is None)."""
    base = path[i]["mid"]
    if not base:
        return None
    fut = [(k - i, p["mid"]) for k, p in enumerate(path) if k > i and p["mid"] and (horizon is None or k - i <= horizon)]
    if not fut:
        return None
    rets = [(t, (mid / base - 1) * 100) for t, mid in fut]
    lo = min(rets, key=lambda x: x[1])
    hi = max(rets, key=lambda x: x[1])
    return dict(max_adverse_pct=min(lo[1], 0.0), t_max_adverse=lo[0], max_favourable_pct=max(hi[1], 0.0), t_max_favourable=hi[0],
                end_ret_pct=rets[-1][1], adverse1_before_fav1=_first(rets))


def _first(rets):
    for _, r in rets:
        if r <= -1.0:
            return True
        if r >= 1.0:
            return False
    return None


def warning_study(refs, horizon=5) -> dict:
    """(1) Every minute evaluation grouped by the advisory action at that minute, with the option-mid path over the
    NEXT `horizon` minutes (fixed horizon, so early and late minutes are comparable). DATA_UNRELIABLE minutes are
    reported separately. (2) First option-evidence warning per position (PREPARE_EXIT / BREAK_EXIT) with the path to
    the end of the holding window. (3) How often a warning preceded a -5 % drawdown from entry, and how often
    positions were warned at all (saturation)."""
    by_action = defaultdict(list)
    warn, lead = [], []
    for r in refs:
        p = r["path"]
        for i, x in enumerate(p):
            if x["action"] is None or i >= len(p) - 1:
                continue
            f = forward(p, i, horizon)
            if f:
                key = "DATA_UNRELIABLE" if x["data_unreliable"] else x["action"]
                by_action[key].append(f)
        first = next((i for i, x in enumerate(p) if x["action"] in ("PREPARE_EXIT", "BREAK_EXIT") and not x["data_unreliable"]), None)
        if first is not None and first < len(p) - 1:
            f = forward(p, first)
            if f:
                f.update(symbol=r["symbol"], date=r["date"], cohort=r["cohort"], option_type=r["option_type"], minute=p[first]["minute"],
                         action=p[first]["action"])
                warn.append(f)
        e = r["entry_mid"]
        cross = next((i for i, x in enumerate(p) if x["mid"] and (x["mid"] / e - 1) * 100 <= -5.0), None)
        lead.append(dict(symbol=r["symbol"], date=r["date"], cohort=r["cohort"], option_type=r["option_type"],
                         warned=first is not None, drawdown_5pct=cross is not None,
                         warned_before=first is not None and cross is not None and first < cross,
                         lead_minutes=(cross - first) if (first is not None and cross is not None and first < cross) else None))

    def summ(xs):
        a1 = [x["adverse1_before_fav1"] for x in xs if x["adverse1_before_fav1"] is not None]
        return dict(n=len(xs), median_max_adverse_pct=med([x["max_adverse_pct"] for x in xs]),
                    median_max_favourable_pct=med([x["max_favourable_pct"] for x in xs]),
                    median_t_max_adverse_min=med([x["t_max_adverse"] for x in xs]),
                    median_t_max_favourable_min=med([x["t_max_favourable"] for x in xs]),
                    median_end_ret_pct=med([x["end_ret_pct"] for x in xs]),
                    pct_minus1_before_plus1=(100 * sum(a1) / len(a1)) if a1 else None, n_resolved=len(a1))
    dd = [x for x in lead if x["drawdown_5pct"]]
    nodd = [x for x in lead if not x["drawdown_5pct"]]
    return dict(horizon_min=horizon, by_action={k: summ(v) for k, v in sorted(by_action.items())},
                first_warning_to_exit=summ(warn), warnings=warn,
                saturation=dict(positions=len(lead), warned_at_all=sum(x["warned"] for x in lead)),
                drawdown_lead=dict(n_positions_with_5pct_drawdown=len(dd), warned_before=sum(x["warned_before"] for x in dd),
                                   median_lead_minutes=med([x["lead_minutes"] for x in dd]),
                                   n_positions_without_drawdown=len(nodd), warned_without_drawdown=sum(x["warned"] for x in nodd)),
                lead_rows=lead)
