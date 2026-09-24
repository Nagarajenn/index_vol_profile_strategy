"""One signal -> one complete diagnostic row.

Every field is measured, never inferred. A missing Greek stays None; it is never replaced with
zero, because zero is a claim ("delta is 0.00") and None is the truth ("the feed did not
publish it"). The same applies to IV and to any horizon the data does not reach.

Leakage: everything named `pre_*` or `at_entry` comes from minutes <= the signal minute.
Everything named `*_1m/3m/5m/10m` or `exit_*` is post-signal and is used ONLY to score, never
to decide.
"""

from option_risk_12b.option_snapshot import shift
from option_risk_12b.option_state import leg
from option_audit_12e.config import (ATM, DEFAULT, FAR_OTM, ITM, IV_HEADWIND, IV_NEUTRAL,
                                     IV_TAILWIND, IV_UNKNOWN, MOD_OTM, NEAR_ATM)


def _pct(now, then):
    if now is None or then in (None, 0):
        return None
    return (now - then) / abs(then) * 100


def spot_at(series: dict, minute: str):
    s = series.get(minute)
    return s.get("spot") if s else None


def leg_at(series: dict, minute: str, side: str, strike: float | None) -> dict:
    if strike is None or minute not in series:
        return {}
    return leg(series, minute, side, strike) or {}


def quotes(series, minute, side, strike) -> dict:
    q = leg_at(series, minute, side, strike)
    bid, ask = q.get("bid"), q.get("ask")
    return dict(bid=bid, ask=ask, ltp=q.get("ltp"), mid=q.get("mid"),
                spread=(ask - bid) if (bid is not None and ask is not None) else None,
                spread_pct=q.get("spread_pct"), bid_qty=q.get("bid_qty"), ask_qty=q.get("ask_qty"),
                iv=q.get("iv"), delta=q.get("delta"), gamma=q.get("gamma"), theta=q.get("theta"),
                vega=q.get("vega"), greeks_status=q.get("greeks_status"))


def strike_band(strike: float | None, spot: float | None, side: str, cfg=DEFAULT) -> tuple:
    """(distance_pts, distance_pct, band). OTM/ITM is resolved by side, not by absolute distance."""
    if strike is None or spot is None:
        return None, None, "UNKNOWN"
    dist = strike - spot
    pct = abs(dist) / spot * 100
    itm = (dist < 0) if side == "CE" else (dist > 0)
    if pct <= cfg.atm_band_pct:
        band = ATM
    elif itm:
        band = ITM
    elif pct <= cfg.near_band_pct:
        band = NEAR_ATM
    elif pct <= cfg.moderate_band_pct:
        band = MOD_OTM
    else:
        band = FAR_OTM
    return round(dist, 2), round(pct, 4), band


def iv_label(iv_change_pct: float | None, side: str, cfg=DEFAULT) -> str:
    """For a long option, falling IV is a headwind regardless of side."""
    if iv_change_pct is None:
        return IV_UNKNOWN
    if iv_change_pct <= -cfg.iv_move_pct:
        return IV_HEADWIND
    if iv_change_pct >= cfg.iv_move_pct:
        return IV_TAILWIND
    return IV_NEUTRAL


def build(series: dict, signal: dict, cfg=DEFAULT) -> dict:
    """`signal` is a 12D dataset row (it already carries side, strike, entry/exit minutes)."""
    m0, side, strike = signal["signal_minute"], signal["side"], signal.get("strike")
    entry = quotes(series, m0, side, strike)
    spot0 = spot_at(series, m0)
    want_down = side == "PE"

    row = dict(
        signal_id=signal["signal_id"], market=signal["market"], session_date=str(signal["session_date"]),
        signal_minute=m0, direction=signal["direction"], side=side, strike=strike,
        contract=signal.get("contract"), confidence=signal.get("confidence"),
        underlying_at_signal=spot0,
        entry_ask=entry["ask"], entry_bid=entry["bid"], entry_ltp=entry["ltp"], entry_mid=entry["mid"],
        entry_spread=entry["spread"], entry_spread_pct=entry["spread_pct"],
        entry_bid_qty=entry["bid_qty"], entry_ask_qty=entry["ask_qty"],
        entry_delta=entry["delta"], entry_gamma=entry["gamma"], entry_theta=entry["theta"],
        entry_vega=entry["vega"], entry_iv=entry["iv"], greeks_status=entry["greeks_status"],
        quantity=signal.get("quantity"),
    )
    row["strike_distance"], row["strike_distance_pct"], row["strike_band"] = \
        strike_band(strike, spot0, side, cfg)

    # ---- PRE-signal move: did the move already happen before we were told? ------------------
    for k in cfg.pre_horizons:
        pm = shift(m0, -k)
        row[f"und_pre_{k}m_pct"] = _pct(spot0, spot_at(series, pm))
        row[f"opt_pre_{k}m_pct"] = _pct(entry["mid"], leg_at(series, pm, side, strike).get("mid"))

    # ---- POST-signal: underlying and option, measured separately ------------------------------
    for k in cfg.horizons:
        fm = shift(m0, k)
        s_f = spot_at(series, fm)
        q_f = quotes(series, fm, side, strike)
        u = _pct(s_f, spot0)
        # the option is marked on the BID -- what a seller could actually receive
        o = _pct(q_f["bid"], entry["ask"]) if (q_f["bid"] is not None and entry["ask"]) else None
        o_mid = _pct(q_f["mid"], entry["mid"])
        row[f"und_{k}m_pct"] = u
        row[f"opt_{k}m_pct"] = o
        row[f"opt_mid_{k}m_pct"] = o_mid
        row[f"iv_{k}m"] = q_f["iv"]
        row[f"iv_change_{k}m_pct"] = _pct(q_f["iv"], entry["iv"])
        # direction correctness from the UNDERLYING itself, per horizon (spec 15)
        row[f"und_direction_ok_{k}m"] = None if (u is None or abs(u) < cfg.und_flat_pct) \
            else ((u < 0) if want_down else (u > 0))
        row[f"opt_profitable_{k}m"] = None if o is None else o > 0
        # Measured ELASTICITY on the MID (execution friction is accounted for separately). Only
        # computed when the underlying actually moved -- otherwise the denominator is noise.
        usable = o_mid is not None and u is not None and abs(u) >= cfg.min_und_move_for_ratio
        row[f"response_ratio_{k}m"] = round(abs(o_mid) / abs(u), 2) if usable else None
        # FIRST-ORDER THEORETICAL ESTIMATE -- an analytical benchmark, never a trading signal
        if entry["delta"] is not None and s_f is not None and spot0 is not None and entry["mid"]:
            expected_pts = entry["delta"] * (s_f - spot0)
            row[f"expected_opt_{k}m_pct"] = round(expected_pts / entry["mid"] * 100, 4)
            row[f"response_gap_{k}m"] = round(o_mid - row[f"expected_opt_{k}m_pct"], 4) \
                if o_mid is not None else None
            # The theoretical elasticity this contract should show, from entry data only:
            #   lambda = (dP/P) / (dS/S) = |delta| * S / P
            # Both the measured ratio and this are ratios of like units, so no scaling applies.
            row[f"theoretical_elasticity_{k}m"] = round(abs(entry["delta"]) * spot0 / entry["mid"], 2)
            theo = row[f"theoretical_elasticity_{k}m"]
            row[f"response_efficiency_{k}m"] = round((abs(o_mid) / abs(u)) / theo, 3) \
                if (usable and theo) else None
        else:
            row[f"expected_opt_{k}m_pct"] = None
            row[f"response_gap_{k}m"] = None
            row[f"response_efficiency_{k}m"] = None
            row[f"theoretical_elasticity_{k}m"] = None

    # ---- exit ---------------------------------------------------------------------------------------
    xm = signal.get("exit_minute")
    ex = quotes(series, xm, side, strike) if xm else {}
    spot_x = spot_at(series, xm) if xm else None
    row.update(exit_minute=xm, exit_bid=ex.get("bid"), exit_ask=ex.get("ask"), exit_ltp=ex.get("ltp"),
               exit_mid=ex.get("mid"), exit_spread=ex.get("spread"), exit_spread_pct=ex.get("spread_pct"),
               exit_iv=ex.get("iv"), underlying_at_exit=spot_x,
               und_move_to_exit_pct=_pct(spot_x, spot0),
               iv_change_to_exit_pct=_pct(ex.get("iv"), entry["iv"]),
               hold_minutes=signal.get("hold_minutes"), exit_reason=signal.get("exit_reason"),
               mfe_per_unit=signal.get("mfe_per_unit"), mae_per_unit=signal.get("mae_per_unit"),
               final_pnl_per_unit=signal.get("final_pnl_per_unit"), final_pnl=signal.get("final_pnl"),
               final_pnl_pct=signal.get("final_pnl_pct"))
    row["iv_state"] = iv_label(row["iv_change_to_exit_pct"], side, cfg)

    # ---- execution economics: what the round trip cost before anything moved -------------------
    entry_cost = entry["spread"] / 2 if entry["spread"] is not None else None
    exit_cost = ex.get("spread") / 2 if ex.get("spread") is not None else None
    row["entry_spread_cost"] = entry_cost
    row["exit_spread_cost"] = exit_cost
    row["round_trip_spread"] = (entry["ask"] - ex["bid"]) - (entry["mid"] - ex["mid"]) \
        if (entry["ask"] is not None and ex.get("bid") is not None
            and entry["mid"] is not None and ex.get("mid") is not None) else None
    # MID-to-MID strips execution friction out; ASK-to-BID is what actually happens
    row["mid_to_mid_per_unit"] = (ex["mid"] - entry["mid"]) if (ex.get("mid") is not None
                                                               and entry["mid"] is not None) else None
    row["ask_to_bid_per_unit"] = row["final_pnl_per_unit"]
    row["execution_friction_per_unit"] = (row["mid_to_mid_per_unit"] - row["ask_to_bid_per_unit"]) \
        if (row["mid_to_mid_per_unit"] is not None and row["ask_to_bid_per_unit"] is not None) else None

    # ---- theta: a bounded estimate, explicitly not an assertion ------------------------------------
    # theta is published per DAY; a 1-10 minute scalp sees a small fraction of one trading day.
    if entry["theta"] is not None and signal.get("hold_minutes"):
        row["theta_estimate_per_unit"] = entry["theta"] * (signal["hold_minutes"] / 375.0)
        row["theta_share_of_result"] = (abs(row["theta_estimate_per_unit"]) / abs(row["final_pnl_per_unit"])) \
            if row.get("final_pnl_per_unit") else None
    else:
        row["theta_estimate_per_unit"] = None
        row["theta_share_of_result"] = None
    return row
