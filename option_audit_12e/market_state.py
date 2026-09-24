"""The underlying's own state AT the signal minute -- causal, from spot prints only.

This is deliberately independent of 12C's evidence. 12C's directional read is one of the things
under audit, so using it here would make the audit circular: we would be checking the signal
against itself.
"""

from option_risk_12b.option_snapshot import shift
from option_audit_12e.config import DEFAULT, RANGE, REVERSING, TRENDING_DOWN, TRENDING_UP, UNKNOWN


def _spot(series, m):
    s = series.get(m)
    return s.get("spot") if s else None


def classify(series: dict, minute: str, cfg=DEFAULT) -> dict:
    """TRENDING_UP / TRENDING_DOWN / RANGE / REVERSING / UNKNOWN, plus the measurements.

    Uses only minutes <= `minute`."""
    now = _spot(series, minute)
    back = _spot(series, shift(minute, -cfg.trend_lookback_min))
    mid = _spot(series, shift(minute, -3))
    if now is None or back in (None, 0):
        return dict(state=UNKNOWN, lookback_pct=None, recent_pct=None,
                    note="No usable underlying prints at or before this minute.")
    lookback = (now - back) / back * 100
    recent = ((now - mid) / mid * 100) if mid else None

    # A retracement against a real trend is reported as REVERSING rather than being averaged
    # into a weaker trend reading -- the two mean different things for an entry.
    if recent is not None and abs(lookback) >= cfg.trend_pct and lookback * recent < 0 \
            and abs(recent) >= cfg.reversal_ratio * abs(lookback):
        return dict(state=REVERSING, lookback_pct=round(lookback, 4), recent_pct=round(recent, 4),
                    note=f"{cfg.trend_lookback_min}-minute move {lookback:+.2f}% is being retraced "
                         f"({recent:+.2f}% in the last 3 minutes).")
    if lookback >= cfg.trend_pct:
        return dict(state=TRENDING_UP, lookback_pct=round(lookback, 4),
                    recent_pct=round(recent, 4) if recent is not None else None,
                    note=f"Underlying up {lookback:+.2f}% over {cfg.trend_lookback_min} minutes.")
    if lookback <= -cfg.trend_pct:
        return dict(state=TRENDING_DOWN, lookback_pct=round(lookback, 4),
                    recent_pct=round(recent, 4) if recent is not None else None,
                    note=f"Underlying down {lookback:+.2f}% over {cfg.trend_lookback_min} minutes.")
    if abs(lookback) <= cfg.range_pct:
        return dict(state=RANGE, lookback_pct=round(lookback, 4),
                    recent_pct=round(recent, 4) if recent is not None else None,
                    note=f"Underlying flat: {lookback:+.2f}% over {cfg.trend_lookback_min} minutes.")
    return dict(state=RANGE, lookback_pct=round(lookback, 4),
                recent_pct=round(recent, 4) if recent is not None else None,
                note=f"No clear trend: {lookback:+.2f}% over {cfg.trend_lookback_min} minutes.")


def premium_extension(series: dict, minute: str, side: str, strike: float | None, window: int = 10) -> dict:
    """Where the premium sits within its own recent range at the signal minute.

    Measured, never used to reject anything (spec 18)."""
    if strike is None:
        return dict(position_in_range=None, window_high=None, window_low=None, note="No strike.")
    vals = []
    for k in range(window + 1):
        m = shift(minute, -k)
        s = series.get(m)
        if not s:
            continue
        lg = (s.get("legs") or {}).get((side, strike))
        if lg and lg.get("mid") is not None:
            vals.append(lg["mid"])
    if len(vals) < 3:
        return dict(position_in_range=None, window_high=None, window_low=None,
                    note="Not enough premium history for a range reading.")
    now, hi, lo = vals[0], max(vals), min(vals)
    pos = ((now - lo) / (hi - lo) * 100) if hi > lo else None
    return dict(position_in_range=round(pos, 1) if pos is not None else None,
                window_high=hi, window_low=lo,
                note=f"Premium sits at {pos:.0f}% of its {window}-minute range." if pos is not None
                     else "Premium range is degenerate this window.")
