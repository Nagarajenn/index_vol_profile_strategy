"""Price structure, breaks and setup type -- a genuine price-action read, not a restatement
of 13A's direction.

Nothing in this module is allowed to look at the 13A candidate's side. The classifiers describe
what price is doing; only `decide.py` asks whether that agrees with the side being proposed.
That separation is what makes the confirmation meaningful rather than circular.
"""

from price_action_13b import bars as B
from price_action_13b.config import (BREAKDOWN, BREAKOUT_CONTINUATION, BREAKOUT_UP, CLEAN_BREAK,
                                     CLEAN_BREAK_FT, DEFAULT, EXHAUSTED_BREAK, EXTENDED_MOVE,
                                     FAILED_BREAK, INSUFFICIENT, MIXED, NO_BREAK, NO_CLEAR_SETUP,
                                     PULLBACK_IN_TREND, RANGE, RANGE_ROTATION, REVERSAL,
                                     REVERSING_DOWN, REVERSING_UP, TRENDING_DOWN, TRENDING_UP)


def structure(window: list[dict], cfg=DEFAULT) -> dict:
    """HH/HL/LH/LL from confirmed swings, then a structure state."""
    if len(window) < 2 * cfg.swing_k + 3:
        return dict(state=INSUFFICIENT, higher_high=None, higher_low=None, lower_high=None,
                    lower_low=None, swings=None,
                    note="Not enough completed bars for a structure read.")
    sw = B.swings(window, cfg.swing_k, cfg.min_swing_pct)
    lh, ph = sw["last_high"], sw["prior_high"]
    ll, pl = sw["last_low"], sw["prior_low"]
    hh = (lh["price"] > ph["price"]) if (lh and ph) else None
    hl = (ll["price"] > pl["price"]) if (ll and pl) else None
    lower_high = (lh["price"] < ph["price"]) if (lh and ph) else None
    lower_low = (ll["price"] < pl["price"]) if (ll and pl) else None

    last = window[-1]
    recent_hi = B.recent_extreme(window[:-1], cfg.structure_window, "high")
    recent_lo = B.recent_extreme(window[:-1], cfg.structure_window, "low")
    close = last["close"]
    broke_up = bool(recent_hi and close and close > recent_hi["price"])
    broke_down = bool(recent_lo and close and close < recent_lo["price"])

    if broke_up and not broke_down:
        state = BREAKOUT_UP
    elif broke_down and not broke_up:
        state = BREAKDOWN
    elif hh and hl:
        state = TRENDING_UP
    elif lower_high and lower_low:
        state = TRENDING_DOWN
    elif hl and lower_high:
        state = REVERSING_UP if (hl and not lower_low) else MIXED
    elif hh and lower_low:
        state = MIXED
    elif lower_low and hh is False:
        state = REVERSING_DOWN
    elif hh is None and lower_high is None:
        state = INSUFFICIENT
    else:
        state = RANGE

    parts = []
    if hh is not None:
        parts.append("higher high" if hh else "lower high")
    if hl is not None:
        parts.append("higher low" if hl else "lower low")
    return dict(state=state, higher_high=hh, higher_low=hl, lower_high=lower_high,
                lower_low=lower_low, swings=sw, recent_high=recent_hi, recent_low=recent_lo,
                note=(" → ".join(p.upper() for p in parts) if parts else "No confirmed swing pair yet."))


def break_quality(window: list[dict], side: str, struct: dict, cfg=DEFAULT) -> dict:
    """Did a meaningful level break, did the close confirm it, and did it hold?

    `side` here is the DIRECTION OF THE BREAK being examined ("up"/"down"), not the option side.
    """
    up = side == "up"
    # The level must be established BEFORE any candidate break, otherwise it drifts up with the
    # breakout bar's own high and nothing can ever exceed it. So the lookback ends far enough
    # back that a break in the recent bars is measured against prior structure.
    scan = cfg.follow_through_bars + 1
    prior = window[:-scan] if len(window) > scan else []
    level = B.recent_extreme(prior, cfg.structure_window, "high" if up else "low") if prior else None
    if not level or len(window) < cfg.follow_through_bars + 2:
        return dict(state=INSUFFICIENT, level=None, note="No usable level or not enough bars.")
    lvl = level["price"]
    a = B.atr(window, cfg.atr_period)
    buf = lvl * cfg.break_buffer_pct / 100

    # the break bar is the first completed bar that closed beyond the level with a buffer
    idx = None
    for i in range(len(window) - 1, max(len(window) - cfg.structure_window, -1), -1):
        c = window[i]["close"]
        if c is None:
            continue
        if (c > lvl + buf) if up else (c < lvl - buf):
            idx = i
        elif idx is not None:
            break
    if idx is None:
        # price may have poked through without closing beyond -- that is a wick, not a break
        pierced = any((b["high"] is not None and b["high"] > lvl + buf) if up
                      else (b["low"] is not None and b["low"] < lvl - buf)
                      for b in window[-cfg.structure_window:])
        return dict(state=NO_BREAK, level=lvl, pierced_without_close=pierced,
                    note=(f"Price reached beyond {lvl:,.1f} but no bar CLOSED through it."
                          if pierced else f"No break of {lvl:,.1f}."))

    brk = window[idx]
    body, wick = B.body_and_wick(brk, lvl, side)
    if body is not None and wick is not None and body > 0 and wick > cfg.wick_body_ratio * body:
        return dict(state=FAILED_BREAK, level=lvl, break_minute=brk["minute"],
                    note=f"The move through {lvl:,.1f} was mostly wick ({wick:.1f} beyond a {body:.1f} body).")

    after = window[idx + 1:]
    held = [b for b in after if b["close"] is not None and
            ((b["close"] > lvl) if up else (b["close"] < lvl))]
    last_close = window[-1]["close"]
    back_inside = last_close is not None and ((last_close <= lvl) if up else (last_close >= lvl))
    if back_inside:
        return dict(state=FAILED_BREAK, level=lvl, break_minute=brk["minute"],
                    bars_since=len(after),
                    note=f"Broke {lvl:,.1f} at {brk['minute']} but price is back inside.")

    extension = abs(last_close - lvl) if last_close is not None else None
    if a and extension is not None and extension >= cfg.extension_atr_mult * a:
        return dict(state=EXHAUSTED_BREAK, level=lvl, break_minute=brk["minute"],
                    bars_since=len(after), extension_atr=round(extension / a, 2),
                    note=f"Already {extension / a:.1f} ATR beyond {lvl:,.1f} -- the move is extended.")

    if len(held) >= cfg.follow_through_bars:
        return dict(state=CLEAN_BREAK_FT, level=lvl, break_minute=brk["minute"],
                    bars_since=len(after), bars_held=len(held),
                    extension_atr=round(extension / a, 2) if (a and extension) else None,
                    note=f"Closed through {lvl:,.1f} at {brk['minute']} and held for "
                         f"{len(held)} completed bars.")
    return dict(state=CLEAN_BREAK, level=lvl, break_minute=brk["minute"], bars_since=len(after),
                bars_held=len(held),
                note=f"Closed through {lvl:,.1f} at {brk['minute']}; follow-through not yet "
                     f"confirmed ({len(held)} of {cfg.follow_through_bars} bars).")


def setup_type(struct: dict, brk: dict, cfg=DEFAULT) -> dict:
    """What KIND of move this is -- continuation, pullback, reversal, rotation, extended."""
    s, b = struct["state"], brk["state"]
    if b in (CLEAN_BREAK, CLEAN_BREAK_FT):
        return dict(state=BREAKOUT_CONTINUATION,
                    note=f"{b.replace('_', ' ').lower()} out of {s.replace('_', ' ').lower()}.")
    if b == EXHAUSTED_BREAK:
        return dict(state=EXTENDED_MOVE, note=brk["note"])
    if b == FAILED_BREAK:
        return dict(state=REVERSAL, note=brk["note"])
    if s in (TRENDING_UP, TRENDING_DOWN):
        return dict(state=PULLBACK_IN_TREND,
                    note=f"Trend intact ({s.replace('_', ' ').lower()}) with no fresh break -- "
                         f"a pullback, not an entry trigger.")
    if s == RANGE:
        return dict(state=RANGE_ROTATION,
                    note="Price is rotating inside the recent range with no confirmed break.")
    return dict(state=NO_CLEAR_SETUP, note=f"Structure reads {s.replace('_', ' ').lower()}.")
