"""Descriptive market state at time T (NOT a trading signal).

Transparent rule logic; magnitudes come from prior-day percentiles (minute thresholds).
Every classification stores the component reasons that produced it."""

from opportunity_matrix_v1 import features as F

STATES = ("TREND_UP", "TREND_DOWN", "BALANCED", "COMPRESSED", "EXPANSION_SETUP", "REVERSAL_SETUP", "CONFLICTED")


def classify(f: dict, mth, cfg) -> tuple[str, list, dict]:
    if f.get("data_quality") != "GOOD":
        return "BALANCED", ["insufficient_1min_data"], {}
    far = mth["dist_vwap_atr"].p(cfg.vwap_distance_pct)
    up, dn = [], []
    if f["dist_vwap_atr"] is not None and far is not None and abs(f["dist_vwap_atr"]) >= far:
        (up if f["dist_vwap"] > 0 else dn).append("price_above_vwap" if f["dist_vwap"] > 0 else "price_below_vwap")
    if f.get("vwap_slope") is not None and f["vwap_slope"] != 0:
        (up if f["vwap_slope"] > 0 else dn).append("vwap_rising" if f["vwap_slope"] > 0 else "vwap_falling")
    if f.get("poc_migration") is not None and f["poc_migration"] != 0:
        (up if f["poc_migration"] > 0 else dn).append("poc_migrating_up" if f["poc_migration"] > 0 else "poc_migrating_down")
    if f["dominance"] >= cfg.dominance_up:
        up.append("positive_volume_dominance")
    elif f["dominance"] <= cfg.dominance_down:
        dn.append("negative_volume_dominance")
    compressed = mth["range15"].p(cfg.compression_pct) is not None and f["range15"] <= mth["range15"].p(cfg.compression_pct)
    vol_acc_hi = f.get("volume_accel") is not None and mth["volume_accel"].p(cfg.expansion_vol_pct) is not None \
        and f["volume_accel"] >= mth["volume_accel"].p(cfg.expansion_vol_pct)
    vel_hi = mth["velocity"].p(cfg.reversal_velocity_pct)
    counter = None
    if f.get("velocity") is not None and vel_hi is not None and abs(f["velocity"]) >= vel_hi:
        if len(up) >= 2 and f["velocity"] < 0:
            counter = "sharp_down_move_against_up_structure"
        elif len(dn) >= 2 and f["velocity"] > 0:
            counter = "sharp_up_move_against_down_structure"
    comp = dict(vwap_state=f.get("vwap_rel"), poc_state=f.get("poc_rel"), structure_state=f.get("va_rel"),
                volume_state=("HIGH_RVOL" if (f.get("rvol") or 0) >= cfg.rvol_high else "LOW_RVOL" if (f.get("rvol") or 1) <= cfg.rvol_low else "NORMAL_RVOL"),
                compression_state="COMPRESSED" if compressed else "NOT_COMPRESSED",
                reversal_state=counter or "NONE", up_conditions=up, down_conditions=dn)
    if len(up) >= cfg.conflict_min_conditions and len(dn) >= cfg.conflict_min_conditions:
        return "CONFLICTED", up + dn, comp
    if counter:
        return "REVERSAL_SETUP", [counter] + up + dn, comp
    if compressed and vol_acc_hi:
        return "EXPANSION_SETUP", ["range_compressed", "volume_accelerating"], comp
    if compressed:
        return "COMPRESSED", ["range_compressed"], comp
    if len(up) >= cfg.trend_min_conditions:
        return "TREND_UP", up, comp
    if len(dn) >= cfg.trend_min_conditions:
        return "TREND_DOWN", dn, comp
    return "BALANCED", ["no_dominant_structure"] + up + dn, comp


def market_state(day, T, mth, cfg) -> dict:
    rv = getattr(mth, "rvol_baseline", {}).get(T.time())
    mf = F.minute_features(day.candles, T, cfg.vp_bin_size[day.symbol], cfg, rv)
    cf = F.chain_features(day.chain, T, day.strike_step, cfg.strike_universe_offsets)
    state, reasons, comp = classify(mf, mth, cfg)
    opt_state = None
    if cf.get("ce_return_5m") is not None and cf.get("pe_return_5m") is not None:
        rel = cf["ce_return_5m"] - cf["pe_return_5m"]
        opt_state = "CE_RELATIVE_STRENGTH" if rel > 0 else ("PE_RELATIVE_STRENGTH" if rel < 0 else "NEUTRAL")
    dq = "GOOD" if mf.get("data_quality") == "GOOD" and cf.get("chain_quality") == "GOOD" else "DEGRADED"
    return dict(symbol=day.symbol, trade_date=str(day.trade_date), timestamp=T.isoformat(), market_state=state,
                state_reasons=reasons, option_state=opt_state, data_quality=dq, **comp,
                **{f"u_{k}": v for k, v in mf.items() if not isinstance(v, (list, dict))},
                **{f"o_{k}": v for k, v in cf.items()})
