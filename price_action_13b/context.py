"""VWAP, volume-profile and volume context.

Every level here comes from data the platform already publishes (`levels_snapshots`). Nothing
is invented: when a level is absent the answer is UNKNOWN, never a substituted number. The
levels row used is the one published AT OR BEFORE the signal minute, so a level computed later
in the session can never influence an earlier decision.
"""

from price_action_13b import bars as B
from price_action_13b.config import (ABOVE_VWAP, BELOW_VWAP, CROSSING_VWAP, DEFAULT,
                                     DISTANT_FROM_VWAP, REJECTED_VWAP, UNKNOWN, VOLUME_DECLINING,
                                     VOLUME_EXPANDING, VOLUME_NORMAL, VOLUME_SPIKE)


def vwap_context(window: list[dict], vwap: float | None, cfg=DEFAULT) -> dict:
    """Where price sits relative to VWAP, and whether it was just rejected there.

    Evidence, not a binary filter -- 13B never rejects a candidate on VWAP alone."""
    if vwap is None or not window:
        return dict(state=UNKNOWN, distance_pct=None, note="No VWAP published at this minute.")
    close = window[-1]["close"]
    if close is None:
        return dict(state=UNKNOWN, distance_pct=None, note="No completed close to compare.")
    dist = (close - vwap) / vwap * 100

    # a rejection: price traded through VWAP during the last few bars but closed back on the
    # same side it started -- more informative than a bare above/below reading
    recent = window[-3:]
    touched_above = any(b["high"] is not None and b["high"] >= vwap for b in recent)
    touched_below = any(b["low"] is not None and b["low"] <= vwap for b in recent)
    if touched_above and touched_below and abs(dist) > cfg.vwap_near_pct:
        return dict(state=REJECTED_VWAP, distance_pct=round(dist, 3), vwap=vwap,
                    note=f"Price traded both sides of VWAP recently and closed {dist:+.2f}% away.")
    if abs(dist) <= cfg.vwap_near_pct:
        return dict(state=CROSSING_VWAP, distance_pct=round(dist, 3), vwap=vwap,
                    note=f"Sitting on VWAP ({dist:+.2f}%).")
    if abs(dist) >= cfg.vwap_distant_pct:
        return dict(state=DISTANT_FROM_VWAP, distance_pct=round(dist, 3), vwap=vwap,
                    note=f"{dist:+.2f}% from VWAP -- extended from the session's mean price.")
    return dict(state=ABOVE_VWAP if dist > 0 else BELOW_VWAP, distance_pct=round(dist, 3),
                vwap=vwap, note=f"{'Above' if dist > 0 else 'Below'} VWAP by {abs(dist):.2f}%.")


def value_context(window: list[dict], levels: dict | None, cfg=DEFAULT) -> dict:
    """Price against POC / VAH / VAL. Absent levels produce UNKNOWN, never a guess."""
    if not levels or not window:
        return dict(state=UNKNOWN, note="No volume-profile levels published at this minute.")
    close = window[-1]["close"]
    poc, vah, val = levels.get("today_poc"), levels.get("today_vah"), levels.get("today_val")
    if close is None or (poc is None and vah is None and val is None):
        return dict(state=UNKNOWN, poc=poc, vah=vah, val=val,
                    note="Volume-profile levels are not available for this minute.")
    edge = close * cfg.value_edge_pct / 100
    if vah is not None and close > vah + edge:
        state, note = "ACCEPTANCE_ABOVE_VAH", f"Accepted above value ({close:,.1f} vs VAH {vah:,.1f})."
    elif val is not None and close < val - edge:
        state, note = "ACCEPTANCE_BELOW_VAL", f"Accepted below value ({close:,.1f} vs VAL {val:,.1f})."
    elif vah is not None and abs(close - vah) <= edge:
        state, note = "AT_VAH", f"At the value-area high ({vah:,.1f})."
    elif val is not None and abs(close - val) <= edge:
        state, note = "AT_VAL", f"At the value-area low ({val:,.1f})."
    elif poc is not None and abs(close - poc) <= edge:
        state, note = "AT_POC", f"At the point of control ({poc:,.1f})."
    else:
        state, note = "INSIDE_VALUE", f"Inside value ({close:,.1f}; VAL {val} - VAH {vah})."
    return dict(state=state, poc=poc, vah=vah, val=val, close=close,
                support=levels.get("support_high"), resistance=levels.get("resistance_low"),
                note=note)


def volume_context(window: list[dict], cfg=DEFAULT) -> dict:
    """Is volume expanding into this move? Described only -- never called institutional."""
    st = B.volume_stats(window, cfg.volume_window)
    r = st["ratio"]
    if r is None:
        return dict(state=UNKNOWN, ratio=None, note="Not enough volume history.")
    if r >= cfg.volume_spike_ratio:
        s, n = VOLUME_SPIKE, f"Volume {r:.2f}x its {cfg.volume_window}-bar average -- a spike."
    elif r >= cfg.volume_expanding_ratio:
        s, n = VOLUME_EXPANDING, f"Volume {r:.2f}x its {cfg.volume_window}-bar average."
    elif r <= cfg.volume_declining_ratio:
        s, n = VOLUME_DECLINING, f"Volume only {r:.2f}x its {cfg.volume_window}-bar average."
    else:
        s, n = VOLUME_NORMAL, f"Volume {r:.2f}x its {cfg.volume_window}-bar average."
    return dict(state=s, ratio=round(r, 3), latest=st["latest"], average=st["average"], note=n)


def volume_confirms(vol: dict, side: str, window: list[dict]) -> bool | None:
    """Does volume support the direction of the latest completed bar?

    Expanding volume on a bar moving the right way confirms; expanding volume on a bar moving
    the wrong way does not."""
    if vol["state"] == UNKNOWN or not window:
        return None
    bar = window[-1]
    if bar["close"] is None or bar["open"] is None:
        return None
    up_bar = bar["close"] >= bar["open"]
    expanding = vol["state"] in (VOLUME_EXPANDING, VOLUME_SPIKE)
    wanted_up = side == "CE"
    return expanding and (up_bar == wanted_up)
