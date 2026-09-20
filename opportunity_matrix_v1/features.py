"""Causal feature primitives. Every function receives a timestamp T and reads only
information known at or before T (1-min candles are known at minute END, option-chain
snapshots at fetched_at, 5-s bars at bar close). Reuses existing PURE analytics."""

from datetime import timedelta

import pandas as pd

from analytics.breakout_boxes import compute_atr
from analytics.volume_intelligence.proxy import attach_buy_sell_columns
from analytics.volume_profile import compute_volume_profile
from analytics.vwap import compute_vwap

MIN = timedelta(minutes=1)


def candles_known(candles: pd.DataFrame, T) -> pd.DataFrame:
    if candles.empty:
        return candles
    return candles[candles["timestamp"] + MIN <= T]


def minute_features(candles_day: pd.DataFrame, T, bin_size: float, cfg, rvol_baseline: float | None = None) -> dict:
    c = candles_known(candles_day, T).reset_index(drop=True)
    if len(c) < 20:
        return {"data_quality": "INSUFFICIENT_1MIN"}
    close = float(c["close"].iloc[-1])
    vw = compute_vwap(c)
    vwap = float(vw.iloc[-1])
    lb = c[c["timestamp"] + MIN <= T - timedelta(minutes=cfg.vwap_slope_lookback_min)]
    vwap_prev = float(vw.iloc[len(lb) - 1]) if len(lb) else None
    vp = compute_volume_profile(c, bin_size)
    c30 = c[c["timestamp"] + MIN <= T - timedelta(minutes=cfg.poc_migration_lookback_min)]
    vp30 = compute_volume_profile(c30, bin_size) if len(c30) >= 20 else None
    atr = float(compute_atr(c, cfg.atr_period_1min).iloc[-1])
    last_r = c.tail(cfg.range_window_min)
    rng = float(last_r["high"].max() - last_r["low"].min())
    w = cfg.velocity_window_min
    vel = close - float(c["close"].iloc[-1 - w]) if len(c) > w else None
    vel_prev = float(c["close"].iloc[-1 - w] - c["close"].iloc[-1 - 2 * w]) if len(c) > 2 * w else None
    va = cfg.volume_accel_window_min
    v_now, v_prev = float(c["volume"].tail(va).sum()), float(c["volume"].iloc[-2 * va:-va].sum()) if len(c) >= 2 * va else None
    bs = attach_buy_sell_columns(last_r)
    b, s_ = float(bs["buy_volume"].sum()), float(bs["sell_volume"].sum())
    vol15 = float(last_r["volume"].sum())
    f = dict(price=close, vwap=vwap, dist_vwap=close - vwap, dist_vwap_atr=(close - vwap) / atr if atr else None,
             vwap_slope=(vwap - vwap_prev) if vwap_prev is not None else None,
             poc=vp.poc if vp else None, vah=vp.vah if vp else None, val=vp.val if vp else None,
             dist_poc=(close - vp.poc) if vp else None, dist_vah=(close - vp.vah) if vp else None, dist_val=(close - vp.val) if vp else None,
             poc_migration=(vp.poc - vp30.poc) if (vp and vp30) else None,
             value_migration=(((vp.vah + vp.val) / 2) - ((vp30.vah + vp30.val) / 2)) if (vp and vp30) else None,
             atr=atr, range15=rng, range15_atr=rng / atr if atr else None, volume15=vol15,
             rvol=(vol15 / rvol_baseline) if rvol_baseline else None,
             volume_accel=(v_now / v_prev) if v_prev else None,
             dominance=(b / (b + s_)) if (b + s_) > 0 else 0.5,
             velocity=vel, acceleration=(vel - vel_prev) if (vel is not None and vel_prev is not None) else None,
             data_quality="GOOD")
    f["vwap_rel"] = "ABOVE" if f["dist_vwap"] > 0 else ("BELOW" if f["dist_vwap"] < 0 else "AT")
    f["poc_rel"] = None if f["dist_poc"] is None else ("ABOVE" if f["dist_poc"] > 0 else ("BELOW" if f["dist_poc"] < 0 else "AT"))
    if vp:
        f["va_rel"] = "ABOVE_VAH" if close > vp.vah else ("BELOW_VAL" if close < vp.val else "INSIDE_VA")
        levels = [x for x in (vp.poc, vp.vah, vp.val, vwap) if x is not None]
        f["nearest_level_dist_atr"] = min(abs(close - x) for x in levels) / atr if atr else None
    return f


# ------------------------------------------------------------------ option chain snapshots (1-min)
def _leg(oc: dict, strike: float, typ: str):
    for k, v in oc.items():
        try:
            if abs(float(k) - strike) < 1e-6:
                return (v or {}).get(typ.lower())
        except ValueError:
            continue
    return None


def _mid(x):
    if not x:
        return None
    b, a = x.get("top_bid_price"), x.get("top_ask_price")
    return (b + a) / 2 if b and a and b > 0 and a >= b else None


def snapshot_at(chain: list, T):
    known = [c for c in chain if c[0] <= T]
    return known[-1] if known else None


def chain_features(chain: list, T, step: float, offsets: int = 5) -> dict:
    now = snapshot_at(chain, T)
    if now is None:
        return {"chain_quality": "MISSING"}
    ts, spot, oc = now
    p5, p10 = snapshot_at(chain, T - timedelta(minutes=5)), snapshot_at(chain, T - timedelta(minutes=10))
    atm = round(spot / step) * step if spot else None
    ce, pe = _leg(oc, atm, "CE"), _leg(oc, atm, "PE")
    f = dict(atm_strike=atm, chain_spot=spot, quote_age_s=(T - ts).total_seconds(), chain_quality="GOOD")
    f["ce_mid"], f["pe_mid"] = _mid(ce), _mid(pe)
    f["straddle"] = (f["ce_mid"] + f["pe_mid"]) if f["ce_mid"] and f["pe_mid"] else None

    def at(snap, strike, typ, fn):
        if snap is None:
            return None
        return fn(_leg(snap[2], strike, typ))
    for typ in ("CE", "PE"):
        m0 = f[f"{typ.lower()}_mid"]
        m5 = at(p5, atm, typ, _mid)
        m10 = at(p10, atm, typ, _mid)
        r = ((m0 / m5) - 1) * 100 if m0 and m5 else None
        r_prev = ((m5 / m10) - 1) * 100 if m5 and m10 else None
        f[f"{typ.lower()}_return_5m"] = r
        f[f"{typ.lower()}_velocity_per_min"] = r / 5 if r is not None else None
        f[f"{typ.lower()}_acceleration"] = (r - r_prev) if (r is not None and r_prev is not None) else None
        leg = ce if typ == "CE" else pe
        f[f"{typ.lower()}_volume"] = leg.get("volume") if leg else None
        f[f"{typ.lower()}_oi"] = leg.get("oi") if leg else None
        f[f"{typ.lower()}_oi_change_5m"] = (leg.get("oi") - at(p5, atm, typ, lambda x: x.get("oi") if x else None)) \
            if leg and leg.get("oi") is not None and at(p5, atm, typ, lambda x: x.get("oi") if x else None) is not None else None
        f[f"{typ.lower()}_iv"] = leg.get("implied_volatility") if leg else None
        b, a = (leg or {}).get("top_bid_price"), (leg or {}).get("top_ask_price")
        f[f"{typ.lower()}_spread_pct"] = ((a - b) / a * 100) if b and a and a > 0 else None
    s5 = at(p5, atm, "CE", _mid), at(p5, atm, "PE", _mid)
    f["straddle_return_5m"] = ((f["straddle"] / (s5[0] + s5[1])) - 1) * 100 if f["straddle"] and all(s5) else None
    ce_oi = sum((_leg(oc, atm + k * step, "CE") or {}).get("oi") or 0 for k in range(-offsets, offsets + 1))
    pe_oi = sum((_leg(oc, atm + k * step, "PE") or {}).get("oi") or 0 for k in range(-offsets, offsets + 1))
    f["pcr"] = pe_oi / ce_oi if ce_oi else None
    if p5:
        ce5 = sum((_leg(p5[2], atm + k * step, "CE") or {}).get("oi") or 0 for k in range(-offsets, offsets + 1))
        pe5 = sum((_leg(p5[2], atm + k * step, "PE") or {}).get("oi") or 0 for k in range(-offsets, offsets + 1))
        f["pcr_change_5m"] = (f["pcr"] - pe5 / ce5) if (f["pcr"] is not None and ce5) else None
    iv_p = (_leg(oc, atm - 2 * step, "PE") or {}).get("implied_volatility")
    iv_c = (_leg(oc, atm + 2 * step, "CE") or {}).get("implied_volatility")
    f["iv_skew"] = (iv_p - iv_c) if (iv_p and iv_c) else None
    return f


def greeks_at(chain: list, T, strike: float, typ: str) -> dict:
    snap = snapshot_at(chain, T)
    leg = _leg(snap[2], strike, typ) if snap else None
    if not leg:
        return {}
    g = leg.get("greeks") or {}
    return dict(iv=leg.get("implied_volatility"), delta=g.get("delta"), gamma=g.get("gamma"), theta=g.get("theta"),
                vega=g.get("vega"), chain_oi=leg.get("oi"), chain_ts=snap[0].isoformat())


# ------------------------------------------------------------------ 5-second series helpers
def fmid(day, i):
    return day.fut_mid[i] if 0 <= i < len(day.fut_mid) else None


def fmove(day, i, lag):
    a, b = fmid(day, i), fmid(day, i - lag)
    return None if a is None or b is None else a - b


def omid(day, key, i):
    s = day.opt.get(key)
    if s is None or not (0 <= i < len(s)) or s[i] is None:
        return None
    return s[i]["mid"]


def oret(day, key, i, lag):
    a, b = omid(day, key, i), omid(day, key, i - lag)
    return None if a is None or b is None or b == 0 else (a / b - 1) * 100


def dir_leg(d: int):
    return ("CE", 0) if d > 0 else ("PE", 0)
