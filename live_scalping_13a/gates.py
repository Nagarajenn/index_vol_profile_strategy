"""The gates. Each returns a verdict plus the measurements behind it.

Design rules:
  * Pure functions of a feature row. No clock, no DB, no network.
  * Default-deny: a missing measurement produces WAIT, never a pass-through.
  * Each gate answers ONE question, so a WAIT can always name a single primary cause.

12E motivated the DIRECTION of these gates (signals fire overwhelmingly in RANGE; friction eats
84% of the gross result). It did not establish their exact values, and nothing here is claimed
to be optimal.
"""

from live_scalping_13a.config import (A, B, C, DEFAULT, EARLY, EXTENDED, IV_HEADWIND, IV_NEUTRAL,
                                      IV_TAILWIND, NORMAL, NO_TRADE, RANGE, REVERSING,
                                      TRENDING_DOWN, TRENDING_UP, UNKNOWN)

CRITICAL_FIELDS = ("underlying", "bid", "ask", "mid", "strike")


# ---------------------------------------------------------------- 1. data validity (spec 7)
def critical_data(f: dict) -> dict:
    """Missing critical data means WAIT. Nothing is ever fabricated or defaulted."""
    missing = [k for k in CRITICAL_FIELDS if f.get(k) is None]
    if not f.get("quote_ok"):
        missing.append("two_sided_quote")
    return dict(ok=not missing, missing=missing,
                note="All critical fields present." if not missing
                     else f"Missing: {', '.join(missing)}. No value is substituted.")


# ---------------------------------------------------------------- 2. regime (spec 3)
def regime(f: dict, cfg=DEFAULT) -> dict:
    g = cfg.gates
    look, recent = f.get("regime_lookback_pct"), f.get("regime_recent_pct")
    if look is None:
        return dict(state=UNKNOWN, lookback_pct=None, recent_pct=recent,
                    note="No underlying history for a regime reading.")
    if recent is not None and abs(look) >= g.regime_trend_pct and look * recent < 0 \
            and abs(recent) >= g.regime_reversal_ratio * abs(look):
        return dict(state=REVERSING, lookback_pct=look, recent_pct=recent,
                    note=f"{g.regime_lookback_min}-minute move {look:+.2f}% is being retraced "
                         f"({recent:+.2f}% in the last 3).")
    if look >= g.regime_trend_pct:
        return dict(state=TRENDING_UP, lookback_pct=look, recent_pct=recent,
                    note=f"Underlying up {look:+.2f}% over {g.regime_lookback_min} minutes.")
    if look <= -g.regime_trend_pct:
        return dict(state=TRENDING_DOWN, lookback_pct=look, recent_pct=recent,
                    note=f"Underlying down {look:+.2f}% over {g.regime_lookback_min} minutes.")
    return dict(state=RANGE, lookback_pct=look, recent_pct=recent,
                note=f"No trend: {look:+.2f}% over {g.regime_lookback_min} minutes.")


def regime_allows(state: str, side: str, cfg=DEFAULT) -> tuple:
    """(allowed, rejection_reason). CE wants TRENDING_UP, PE wants TRENDING_DOWN."""
    g = cfg.gates
    want = TRENDING_UP if side == "CE" else TRENDING_DOWN
    if state == want:
        return True, None
    if state == RANGE:
        return (False, "REGIME_RANGE") if g.enable_range_filter else (True, None)
    if state == REVERSING:
        return (False, "REGIME_REVERSING") if g.enable_reversing_filter else (True, None)
    if state == UNKNOWN:
        return False, "REGIME_UNKNOWN"
    return False, "REGIME_AGAINST"


# ---------------------------------------------------------------- 3. underlying confirmation (spec 4)
def underlying_confirms(f: dict, side: str, cfg=DEFAULT) -> dict:
    """Direction must be visible in the underlying itself, over 3 minutes AND not contradicted
    in the last one."""
    g = cfg.gates
    want_up = side == "CE"
    u1, u3, u5 = f.get("und_pre_1m"), f.get("und_pre_3m"), f.get("und_pre_5m")
    if u3 is None:
        return dict(ok=False, note="No 3-minute underlying reading.", u1=u1, u3=u3, u5=u5)
    moved = (u3 >= g.und_confirm_pct_3m) if want_up else (u3 <= -g.und_confirm_pct_3m)
    not_against = True if u1 is None else ((u1 >= -g.und_confirm_pct_1m) if want_up
                                           else (u1 <= g.und_confirm_pct_1m))
    ok = moved and not_against
    return dict(ok=ok, u1=u1, u3=u3, u5=u5, momentum=f.get("und_momentum"),
                acceleration=f.get("und_acceleration"),
                note=(f"Underlying {u3:+.2f}% over 3 minutes"
                      + ("" if not_against else f", but the last minute went the other way ({u1:+.2f}%)")
                      + "." if moved else
                      f"Underlying only {u3:+.2f}% over 3 minutes; needs "
                      f"{'+' if want_up else '-'}{g.und_confirm_pct_3m}%."))


# ---------------------------------------------------------------- 4. option confirmation (spec 5)
def option_confirms(f: dict, side: str, cfg=DEFAULT) -> dict:
    """Four INDEPENDENT categories. No single indicator is sufficient."""
    g = cfg.gates
    cats, detail = [], {}
    own3, other3 = f.get(f"opt_pre_3m"), f.get("other_pre_3m")

    # (a) relative strength of this side against the other
    rel = (own3 - other3) if (own3 is not None and other3 is not None) else None
    detail["relative_strength"] = rel
    if rel is not None and rel > 0 and (own3 or 0) > 0:
        cats.append("RELATIVE_STRENGTH")
    # (b) own premium momentum
    detail["own_momentum_3m"] = own3
    if own3 is not None and own3 > 0:
        cats.append("OWN_MOMENTUM")
    # (c) participation: traded volume above its own trailing average
    vr = f.get("volume_ratio")
    detail["volume_ratio"] = vr
    if vr is not None and vr >= 1.0:
        cats.append("PARTICIPATION")
    # (d) the other side weakening
    detail["other_momentum_3m"] = other3
    if other3 is not None and other3 < 0:
        cats.append("OTHER_SIDE_WEAK")

    ok = len(cats) >= g.option_min_categories
    return dict(ok=ok, categories=cats, n=len(cats), required=g.option_min_categories,
                detail=detail,
                note=f"{len(cats)} of 4 independent option categories agree "
                     f"({', '.join(c.replace('_', ' ').lower() for c in cats) or 'none'}); "
                     f"{g.option_min_categories} required.")


# ---------------------------------------------------------------- 5. entry timing (spec 6)
def entry_timing(f: dict, side: str, cfg=DEFAULT) -> dict:
    """EARLY / NORMAL / EXTENDED / UNKNOWN, from continuous pre-signal measurements.

    Deliberately NOT 12D's classification, which 12D's own report showed has no discriminative
    power. This one asks a narrower question: how much of the move is already behind us?"""
    g = cfg.gates
    want_up = side == "CE"
    o3, o5 = f.get("opt_pre_3m"), f.get("opt_pre_5m")
    u5 = f.get("und_pre_5m")
    pos = f.get("premium_range_position")
    accel = f.get("und_acceleration")
    m = dict(opt_pre_3m=o3, opt_pre_5m=o5, und_pre_5m=u5, premium_range_position=pos,
             und_acceleration=accel)
    if o5 is None and o3 is None:
        return dict(state=UNKNOWN, measurements=m, note="No premium history before the signal.")

    already = o5 if o5 is not None else o3
    und_already = u5 if u5 is not None else 0.0
    und_extended = (und_already >= g.timing_extended_und_pre_5m) if want_up \
        else (und_already <= -g.timing_extended_und_pre_5m)
    if (already is not None and already >= g.timing_extended_opt_pre_5m) or und_extended:
        return dict(state=EXTENDED, measurements=m,
                    note=f"Premium already {already:+.2f}% and the underlying {und_already:+.2f}% "
                         f"before this signal.")
    if pos is not None and pos >= g.timing_extended_range_position and (accel is None or
                                                                       (accel <= 0 if want_up else accel >= 0)):
        return dict(state=EXTENDED, measurements=m,
                    note=f"Premium sits at {pos:.0f}% of its recent range and is no longer accelerating.")
    if o3 is not None and abs(o3) < g.timing_early_opt_pre_3m:
        return dict(state=EARLY, measurements=m,
                    note=f"Premium has barely moved yet ({o3:+.2f}% over 3 minutes).")
    return dict(state=NORMAL, measurements=m,
                note=f"Entry lands {already:+.2f}% into the premium move.")


# ---------------------------------------------------------------- 6. IV (spec 8)
def iv_state(f: dict, series_prev_iv: float | None, cfg=DEFAULT) -> dict:
    """IV never rejects on its own; it costs a quality grade."""
    g = cfg.gates
    now = f.get("iv")
    if now is None or series_prev_iv in (None, 0):
        return dict(state=UNKNOWN, change_pct=None, note="IV not available for both minutes.")
    ch = (now - series_prev_iv) / abs(series_prev_iv) * 100
    if ch <= -g.iv_move_pct:
        return dict(state=IV_HEADWIND, change_pct=ch, note=f"IV down {ch:+.2f}% into the signal.")
    if ch >= g.iv_move_pct:
        return dict(state=IV_TAILWIND, change_pct=ch, note=f"IV up {ch:+.2f}% into the signal.")
    return dict(state=IV_NEUTRAL, change_pct=ch, note=f"IV flat ({ch:+.2f}%).")


# ---------------------------------------------------------------- 7. spread (spec 9)
def spread_gate(f: dict, cfg=DEFAULT) -> dict:
    """Relative economics only. A fixed rupee threshold would be wrong across premiums."""
    g = cfg.gates
    sp, mid = f.get("spread"), f.get("mid")
    if sp is None or not mid:
        return dict(ok=False, spread=sp, spread_pct=None,
                    note="No two-sided quote, so the spread cannot be assessed.")
    pct = sp / mid * 100
    ok = pct <= g.max_spread_pct_of_premium or not g.enable_spread_filter
    return dict(ok=ok, spread=round(sp, 2), spread_pct=round(pct, 3),
                limit_pct=g.max_spread_pct_of_premium,
                note=f"Spread {sp:.2f} on a {mid:.2f} premium = {pct:.2f}% "
                     f"(limit {g.max_spread_pct_of_premium:.2f}%).")


# ---------------------------------------------------------------- 8. economics (spec 10)
def economics(f: dict, side: str, cfg=DEFAULT) -> dict:
    """Is the expected first-order move worth more than the round trip?

    ANALYTICAL ESTIMATE, not a prediction: it projects the underlying's own recent movement one
    more step and asks what delta implies for the premium."""
    g = cfg.gates
    delta, spread, spot = f.get("delta"), f.get("spread"), f.get("underlying")
    recent = f.get(f"und_pre_{g.expected_move_lookback_min}m")
    if None in (delta, spread, spot) or recent is None or not spread:
        return dict(ok=False, expected_move=None, ratio=None,
                    note="Delta, spread or recent underlying movement unavailable.")
    # project the same magnitude of underlying movement forward one lookback window
    expected_pts = abs(delta) * abs(recent) / 100 * spot
    round_trip = spread                      # pay the ask, receive the bid
    ratio = expected_pts / round_trip if round_trip else None
    ok = (ratio is not None and ratio >= g.min_expected_move_to_spread_ratio) \
        or not g.enable_economics_filter
    return dict(ok=ok, expected_move=round(expected_pts, 2), round_trip_cost=round(round_trip, 2),
                ratio=round(ratio, 2) if ratio is not None else None,
                required_ratio=g.min_expected_move_to_spread_ratio,
                note=f"A repeat of the last {g.expected_move_lookback_min} minutes "
                     f"({recent:+.2f}%) implies about {expected_pts:.2f}/unit at delta "
                     f"{delta:+.3f}, against a {round_trip:.2f} round trip = {ratio:.2f}x "
                     f"(need {g.min_expected_move_to_spread_ratio:.1f}x)."
                     if ratio is not None else "Expected move could not be estimated.")


# ---------------------------------------------------------------- 9. quality (spec 11)
def trade_quality(checks: dict, iv: dict, cfg=DEFAULT) -> dict:
    """A / B / C / NO_TRADE. No numeric score -- there is no evidence to justify one."""
    g = cfg.gates
    critical = ("critical_data", "regime", "underlying", "option", "timing", "spread", "economics")
    failed = [k for k in critical if not checks.get(k, {}).get("ok", False)]
    if failed:
        return dict(grade=NO_TRADE, failed=failed, downgrades=[],
                    note=f"Critical gate(s) failed: {', '.join(failed)}.")

    downgrades = []
    if g.iv_headwind_downgrades_quality and iv.get("state") == IV_HEADWIND:
        downgrades.append("IV_HEADWIND")
    if checks["timing"].get("state") == EARLY:
        downgrades.append("TIMING_EARLY")
    if checks["option"].get("n", 0) == checks["option"].get("required", 0):
        downgrades.append("OPTION_CONFIRMATION_MINIMAL")
    if (checks["economics"].get("ratio") or 0) < g.min_expected_move_to_spread_ratio * 1.5:
        downgrades.append("ECONOMICS_THIN")

    grade = A if not downgrades else (B if len(downgrades) == 1 else C)
    return dict(grade=grade, failed=[], downgrades=downgrades,
                note=("All gates passed with no risk flag." if not downgrades
                      else f"{len(downgrades)} risk flag(s): "
                           f"{', '.join(d.replace('_', ' ').lower() for d in downgrades)}."))


def quality_allows(grade: str, cfg=DEFAULT) -> bool:
    order = {NO_TRADE: 0, C: 1, B: 2, A: 3}
    return order.get(grade, 0) >= order.get(cfg.gates.min_quality_to_buy, 2)
