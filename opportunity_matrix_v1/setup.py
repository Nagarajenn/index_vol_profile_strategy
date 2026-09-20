"""Pre-3PM setup snapshots (14:30 ... 14:59) and the descriptive PRE_3PM_SETUP_STATE.
NOT a trade signal. Uses only data known at each snapshot time."""

from datetime import datetime, time, timedelta

from config.settings import IST
from opportunity_matrix_v1 import features as F
from opportunity_matrix_v1.market_state import market_state

SETUP_STATES = ("UP_PRESSURE_BUILDING", "DOWN_PRESSURE_BUILDING", "BALANCED", "COMPRESSION", "REVERSAL_RISK", "CONFLICTED")


def _hr_option_velocity(day, T, key, seconds):
    i = day.index_at(T)
    if i < 0:
        return None
    return F.oret(day, key, i, seconds // 5)


def snapshots(day, mth, cfg) -> list[dict]:
    out = []
    for hhmm in cfg.snapshot_times:
        T = datetime.combine(day.trade_date, time.fromisoformat(hhmm), tzinfo=IST)
        s = market_state(day, T, mth, cfg)
        s["snapshot"] = hhmm
        if hhmm >= "14:55":
            c = F.candles_known(day.candles, T)
            p = lambda m: float(c["close"].iloc[-1 - m]) if len(c) > m else None
            now = p(0)
            for m in (1, 2, 5):
                s[f"ret_{m}m_pct"] = ((now / p(m)) - 1) * 100 if now and p(m) else None
            prev = market_state(day, T - timedelta(minutes=1), mth, cfg)
            for k in ("u_dist_vwap", "u_dist_poc", "o_pcr", "o_straddle", "o_iv_skew"):
                s[f"chg_{k}"] = (s[k] - prev[k]) if (s.get(k) is not None and prev.get(k) is not None) else None
            # 5-s option velocity where HR data exists (from 14:56), else the 1-min chain velocity
            for typ in ("CE", "PE"):
                hv = _hr_option_velocity(day, T, (typ, 0), 60)
                s[f"{typ.lower()}_velocity_60s"] = hv if hv is not None else s.get(f"o_{typ.lower()}_velocity_per_min")
                s[f"{typ.lower()}_velocity_source"] = "HR_5S" if hv is not None else "CHAIN_1MIN"
            ce, pe = s.get("ce_velocity_60s"), s.get("pe_velocity_60s")
            s["ce_pe_relative_response"] = (ce - pe) if (ce is not None and pe is not None) else None
        out.append(s)
    return out


def setup_state(snaps: list[dict], mth, cfg) -> dict:
    by = {s["snapshot"]: s for s in snaps}
    s59, s55 = by.get("14:59"), by.get("14:55")
    if not s59 or s59.get("ret_5m_pct") is None:
        return dict(setup_state="BALANCED", setup_direction=0, setup_reasons=["insufficient_data"])
    r5 = s59["ret_5m_pct"]
    strong_thr = mth["ret5"].p(cfg.setup_move_pct)
    strong = strong_thr is not None and abs(r5) >= strong_thr
    rel = s59.get("ce_pe_relative_response")
    compressed = s59.get("compression_state") == "COMPRESSED"
    reasons = []
    if s55 and s55["market_state"] == "TREND_UP" and strong and r5 < 0:
        return dict(setup_state="REVERSAL_RISK", setup_direction=-1, setup_reasons=["trend_up_at_1455", "strong_down_move_1455_1459"])
    if s55 and s55["market_state"] == "TREND_DOWN" and strong and r5 > 0:
        return dict(setup_state="REVERSAL_RISK", setup_direction=1, setup_reasons=["trend_down_at_1455", "strong_up_move_1455_1459"])
    if strong and rel is not None and rel != 0 and (r5 > 0) != (rel > 0):
        return dict(setup_state="CONFLICTED", setup_direction=0, setup_reasons=["underlying_and_option_relative_response_disagree"])
    vwap_chg = s59.get("chg_u_dist_vwap")
    if strong and r5 > 0 and (rel is None or rel > 0) and (vwap_chg is None or vwap_chg >= 0):
        return dict(setup_state="UP_PRESSURE_BUILDING", setup_direction=1,
                    setup_reasons=["5m_return_up_ge_prior_p50", "ce_relative_strength" if rel else "no_option_data", "vwap_distance_rising"])
    if strong and r5 < 0 and (rel is None or rel < 0) and (vwap_chg is None or vwap_chg <= 0):
        return dict(setup_state="DOWN_PRESSURE_BUILDING", setup_direction=-1,
                    setup_reasons=["5m_return_down_ge_prior_p50", "pe_relative_strength" if rel else "no_option_data", "vwap_distance_falling"])
    if compressed and not strong:
        return dict(setup_state="COMPRESSION", setup_direction=0, setup_reasons=["range_compressed", "small_5m_move"])
    return dict(setup_state="BALANCED", setup_direction=0, setup_reasons=reasons or ["no_directional_pressure"])
