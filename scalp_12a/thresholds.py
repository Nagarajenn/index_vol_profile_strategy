"""Causal event thresholds.

Thresholds for session D are percentiles of the same symbol's futures moves
on HR days strictly BEFORE D. Nothing from D itself (or later) is used, so a
shadow run and a later replay of D produce identical thresholds.
"""

from scalp_12a.config import ScalpConfig
from scalp_12a.models import SessionBars, Thresholds


def percentile(values: list[float], p: float) -> float | None:
    """Linear-interpolated percentile (numpy 'linear' method); None when empty."""
    if not values:
        return None
    s = sorted(values)
    if len(s) == 1:
        return s[0]
    pos = (len(s) - 1) * p / 100.0
    lo = int(pos)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def move_distribution(session: SessionBars, lag_bars: int) -> list[float]:
    """|futures(i) - futures(i - lag)| over the session, forward-filled."""
    filled = [session.fut_ffill(i) for i in range(len(session))]
    out = []
    for i in range(lag_bars, len(filled)):
        a, b = filled[i], filled[i - lag_bars]
        if a is not None and b is not None:
            out.append(abs(a - b))
    return out


def build_thresholds(prior_sessions: list[SessionBars], config: ScalpConfig) -> Thresholds:
    days = tuple(sorted(str(s.trading_date) for s in prior_sessions))
    if len(prior_sessions) < config.min_history_days:
        return Thresholds(None, None, None, days, False)
    b30 = 30 // config.bar_seconds
    b180 = 180 // config.bar_seconds
    d30 = [v for s in prior_sessions for v in move_distribution(s, b30)]
    d180 = [v for s in prior_sessions for v in move_distribution(s, b180)]
    thr30 = percentile(d30, config.event_percentile)
    weak = percentile(d30, config.weak_percentile)
    thr180 = percentile(d180, config.continuation_percentile)
    ok = bool(thr30 and weak and thr180)
    return Thresholds(thr30, weak, thr180, days, ok)
