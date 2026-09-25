"""The causal bar window, and the swing structure built on it.

Everything in 13B starts here, because this is where the leakage rule is enforced once rather
than repeated in every classifier:

    at signal minute m, the newest COMPLETE 1-minute bar is the one stamped m-1.

A bar stamped 09:30 covers 09:30:00-09:30:59. At 09:30 it is still forming, and its high, low
and close are not yet known. Using it would be reading the future by one minute -- small, but
exactly the kind of error that makes a backtest look better than reality.
"""

from price_action_13b.config import DEFAULT


def _idx(minute: str) -> int:
    h, m = (int(x) for x in minute.split(":"))
    return h * 60 + m


def _key(i: int) -> str:
    return f"{i // 60:02d}:{i % 60:02d}"


def completed_bars(cmap: dict, minute: str, window: int | None = None) -> list[dict]:
    """Completed bars at or before `minute`, oldest first.

    A bar stamped k is complete once minute k+1 has arrived, so the newest usable stamp is
    minute-1."""
    last = _idx(minute) - 1
    keys = sorted(k for k in cmap if _idx(k) <= last)
    if window:
        keys = keys[-window:]
    return [dict(minute=k, **{f: cmap[k].get(f) for f in ("open", "high", "low", "close", "volume")})
            for k in keys]


def swings(bars: list[dict], k: int = 2, min_pct: float = 0.0) -> dict:
    """Fractal pivots: a swing high has k bars with a lower high on each side.

    The last k bars can never be confirmed (their right-hand side has not happened yet), so they
    are excluded. That is the honest version -- a "swing high" that needs future bars to confirm
    is not observable at the signal minute."""
    highs, lows = [], []
    if len(bars) < 2 * k + 1:
        return dict(highs=[], lows=[], last_high=None, last_low=None, prior_high=None,
                    prior_low=None, confirmed_through=None)
    for i in range(k, len(bars) - k):
        window = bars[i - k:i + k + 1]
        h, l = bars[i]["high"], bars[i]["low"]
        if h is None or l is None:
            continue
        if all(b["high"] is not None and b["high"] <= h for b in window) and \
                any(b["high"] < h for b in window if b is not bars[i]):
            if not min_pct or not highs or abs(h - highs[-1]["price"]) / h * 100 >= min_pct:
                highs.append(dict(minute=bars[i]["minute"], price=h))
        if all(b["low"] is not None and b["low"] >= l for b in window) and \
                any(b["low"] > l for b in window if b is not bars[i]):
            if not min_pct or not lows or abs(l - lows[-1]["price"]) / l * 100 >= min_pct:
                lows.append(dict(minute=bars[i]["minute"], price=l))
    return dict(highs=highs, lows=lows,
                last_high=highs[-1] if highs else None,
                last_low=lows[-1] if lows else None,
                prior_high=highs[-2] if len(highs) > 1 else None,
                prior_low=lows[-2] if len(lows) > 1 else None,
                confirmed_through=bars[len(bars) - k - 1]["minute"] if len(bars) > k else None)


def atr(bars: list[dict], period: int = 14) -> float | None:
    """Average true range over completed bars. None when there is not enough history."""
    if len(bars) < period + 1:
        return None
    trs = []
    for prev, cur in zip(bars[-period - 1:-1], bars[-period:]):
        if None in (cur["high"], cur["low"], prev["close"]):
            continue
        trs.append(max(cur["high"] - cur["low"], abs(cur["high"] - prev["close"]),
                       abs(cur["low"] - prev["close"])))
    return sum(trs) / len(trs) if trs else None


def recent_extreme(bars: list[dict], lookback: int, kind: str) -> dict | None:
    """The highest high or lowest low over the last `lookback` completed bars."""
    window = [b for b in bars[-lookback:] if b["high"] is not None and b["low"] is not None]
    if not window:
        return None
    if kind == "high":
        b = max(window, key=lambda x: x["high"])
        return dict(minute=b["minute"], price=b["high"])
    b = min(window, key=lambda x: x["low"])
    return dict(minute=b["minute"], price=b["low"])


def body_and_wick(bar: dict, level: float, side: str) -> tuple:
    """(body, wick_beyond_level). Used to tell a genuine break from a wick through a level."""
    if None in (bar.get("open"), bar.get("close"), bar.get("high"), bar.get("low")):
        return None, None
    body = abs(bar["close"] - bar["open"])
    if side == "up":
        wick = max(bar["high"] - max(bar["open"], bar["close"]), 0.0)
        beyond = max(bar["high"] - level, 0.0)
    else:
        wick = max(min(bar["open"], bar["close"]) - bar["low"], 0.0)
        beyond = max(level - bar["low"], 0.0)
    return body, min(wick, beyond)


def volume_stats(bars: list[dict], window: int = DEFAULT.volume_window) -> dict:
    """Latest completed bar's volume against its own trailing average."""
    vols = [b["volume"] for b in bars if isinstance(b.get("volume"), (int, float))]
    if len(vols) < 3:
        return dict(latest=None, average=None, ratio=None)
    latest = vols[-1]
    prior = vols[-window - 1:-1] if len(vols) > window else vols[:-1]
    avg = sum(prior) / len(prior) if prior else None
    return dict(latest=latest, average=avg, ratio=(latest / avg) if avg else None)
