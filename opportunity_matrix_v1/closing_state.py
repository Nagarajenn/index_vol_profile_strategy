"""TRACK B -- CLOSING_STATE_RESEARCH (15:15-15:30), analysed separately from Track A.

Labels the underlying reference (never treating a stale value as live), tracks the
option-implied spot, and runs the persistence test. It does NOT infer an auction state.
State labels use bars <= t; persistence and the Experiment J outcomes look forward and
are OUTCOME measurements only."""

from datetime import datetime, time

from config.settings import IST
from opportunity_matrix_v1 import features as F

IMPLIED_STATES = ("STABLE", "MOVING_UP", "MOVING_DOWN", "DIVERGING", "CONVERGING", "UNRELIABLE")


def _implied(day, i):
    t = day.trans[i] if 0 <= i < len(day.trans) else None
    return t.get("implied_spot") if t else None


def closing_rows(day, th, cfg) -> list[dict]:
    rows = []
    a, _ = cfg.windows["OPTION_ONLY"]
    for i in range(len(day)):
        if day.times[i].time() < time.fromisoformat(a):
            continue
        tr = day.trans[i] or {}
        T = day.known_at(i)
        valid = day.und_status[i] == "VALID"
        if valid and day.idx_close[i] is not None:
            ref, ref_type, und_q = day.idx_close[i], "INDEX", "UNDERLYING_RELIABLE"
        else:
            und_q = "UNDERLYING_STALE"
            ref, ref_type = day.last_reliable_px[i], "LAST_RELIABLE_INDEX"
        imp = tr.get("implied_spot")
        low_q = imp is None or (tr.get("implied_n") or 0) < cfg.implied_min_strikes or tr.get("implied_quality") != "OK"
        dq = "DATA_QUALITY_LOW" if low_q else und_q
        gap_last = (imp - ref) if (imp is not None and ref is not None) else None
        gap_fut = (imp - day.fut_mid[i]) if (imp is not None and day.fut_mid[i] is not None) else None
        d10 = (imp - _implied(day, i - 2)) if (imp is not None and _implied(day, i - 2) is not None) else None
        mv_thr = th["implied10"].p(cfg.implied_move_pct)
        state = "UNRELIABLE"
        if not low_q:
            state = "STABLE"
            if d10 is not None and mv_thr and abs(d10) >= mv_thr:
                state = "MOVING_UP" if d10 > 0 else "MOVING_DOWN"
            else:
                g6 = rows[-cfg.gap_trend_bars]["implied_gap_last_reliable"] if len(rows) >= cfg.gap_trend_bars else None
                if g6 is not None and gap_last is not None and mv_thr:
                    if abs(gap_last) - abs(g6) >= mv_thr:
                        state = "DIVERGING"
                    elif abs(g6) - abs(gap_last) >= mv_thr:
                        state = "CONVERGING"
        persist = 0
        for r in reversed(rows):
            if gap_last is not None and r["implied_gap_last_reliable"] is not None and (r["implied_gap_last_reliable"] > 0) == (gap_last > 0) and gap_last != 0:
                persist += 1
            else:
                break
        cf = F.chain_features(day.chain, T, day.strike_step)
        ce, pe = ("CE", 0), ("PE", 0)
        c5, c5p = F.oret(day, ce, i, 1), F.oret(day, ce, i - 1, 1)
        p5, p5p = F.oret(day, pe, i, 1), F.oret(day, pe, i - 1, 1)
        qce, qpe = day.opt[ce][i] or {}, day.opt[pe][i] or {}
        rows.append(dict(symbol=day.symbol, trade_date=str(day.trade_date), i=i, timestamp=T.isoformat(), time=T.strftime("%H:%M:%S"),
                         expiry_flag=day.is_expiry, underlying_reference=ref, underlying_reference_type=ref_type,
                         last_reliable_timestamp=str(day.last_reliable_ts[i]) if day.last_reliable_ts[i] else None,
                         futures_mid=day.fut_mid[i], atm_ce_mid=qce.get("mid"), atm_pe_mid=qpe.get("mid"), straddle=tr.get("straddle"),
                         implied_spot=imp, implied_iqr=tr.get("implied_iqr"), implied_n=tr.get("implied_n"),
                         implied_gap_last_reliable=gap_last, implied_gap_futures_mid=gap_fut, implied_change_10s=d10,
                         gap_persistence_bars=persist, ce_velocity=F.oret(day, ce, i, 2), pe_velocity=F.oret(day, pe, i, 2),
                         ce_acceleration=(c5 - c5p) if (c5 is not None and c5p is not None) else None,
                         pe_acceleration=(p5 - p5p) if (p5 is not None and p5p is not None) else None,
                         ce_pe_asymmetry=((F.oret(day, ce, i, 2) or 0) + (F.oret(day, pe, i, 2) or 0)),
                         iv_ce=cf.get("ce_iv"), iv_pe=cf.get("pe_iv"), iv_skew=cf.get("iv_skew"), pcr=tr.get("pcr_oi"),
                         ce_spread_pct=qce.get("spread_pct"), pe_spread_pct=qpe.get("spread_pct"),
                         quote_age=max(qce.get("quote_age") or 0, qpe.get("quote_age") or 0), ce_oi=qce.get("oi"), pe_oi=qpe.get("oi"),
                         ce_volume=tr.get("ce_volume"), pe_volume=tr.get("pe_volume"), data_quality=dq, closing_state=state))
    return rows


def persistence_movements(day, rows, th, cfg) -> list[dict]:
    """First appearance of each implied-spot movement (|10 s change| >= prior p75), its
    forward persistence, and OUTCOME comparisons for Experiment J."""
    mv_thr = th["implied10"].p(cfg.implied_move_pct)
    if not mv_thr:
        return []
    by_i = {r["i"]: r for r in rows}
    out, prev_moving = [], False
    close = day.daily_close
    close_src = "OFFICIAL_DAILY_CLOSE" if close is not None else None
    if close is None and not day.candles.empty:
        close, close_src = float(day.candles["close"].iloc[-1]), "LAST_1MIN_CANDLE_FALLBACK"
    last_fut = next((m for m in reversed(day.fut_mid) if m is not None), None)
    for r in rows:
        moving = r["closing_state"] in ("MOVING_UP", "MOVING_DOWN")
        if moving and not prev_moving:
            i, m = r["i"], r["implied_change_10s"]
            base = _implied(day, i - 2)
            per = {}
            for h in cfg.persistence_horizons_s:
                k = i + h // 5
                v = _implied(day, k) if k < len(day) else None
                per[h] = None if (v is None or base is None) else ((v - base) * (1 if m > 0 else -1) >= cfg.persistence_keep_frac * abs(m))
            d = 1 if m > 0 else -1
            conf = i + 30 // 5                       # the moment 30 s persistence becomes known
            cr = by_i.get(conf)
            out.append(dict(symbol=day.symbol, trade_date=str(day.trade_date), time=r["time"], direction="UP" if d > 0 else "DOWN",
                            implied_move=m, underlying_state_at_start=r["data_quality"], expiry_flag=day.is_expiry,
                            **{f"persist_{h}s": per[h] for h in cfg.persistence_horizons_s},
                            persistent_30s=per.get(30), one_bar_like=(per.get(10) is False),
                            fut_move_after_confirm=((last_fut - cr["futures_mid"]) * d) if (cr and cr["futures_mid"] and last_fut) else None,
                            close_vs_last_reliable_after_confirm=((close - cr["underlying_reference"]) * d) if (cr and cr["underlying_reference"] and close) else None,
                            close_source=close_src, futures_moved_same_way_10s=((r["futures_mid"] - (by_i.get(i - 2) or {}).get("futures_mid", r["futures_mid"])) * d > 0)
                            if r["futures_mid"] else None))
        prev_moving = moving
    return out
