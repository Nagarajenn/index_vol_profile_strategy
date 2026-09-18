"""Counterfactual opportunity capture (research only; never alters a decision).

For EVERY candidate -- traded or rejected -- record what a realistic entry
(ASK of the bar after detection) would have experienced on the BID over the
following horizons.
"""

from scalp_12a.config import ScalpConfig
from scalp_12a.models import Counterfactual, SessionBars


def track(session: SessionBars, key, entry_index: int, direction: int, config: ScalpConfig,
          session_complete: bool = True) -> Counterfactual | None:
    q0 = session.quote(key, entry_index)
    if q0 is None or not q0.valid:
        return None
    ask = q0.ask
    t0 = session.times[entry_index]
    max_h = max(config.horizons_seconds)
    path = []  # (elapsed_s, bid, index)
    reached_end = False
    for k in range(entry_index + 1, len(session)):
        el = (session.times[k] - t0).total_seconds()
        if el > max_h:
            reached_end = True
            break
        q = session.quote(key, k)
        if q is not None and q.valid:
            path.append((el, q.bid, k))
    complete = reached_end or session_complete

    def pct(b):
        return (b - ask) / ask * 100.0

    mfe = mae = t_mfe = t_mae = None
    if path:
        hi = max(path, key=lambda p: p[1])
        lo = min(path, key=lambda p: p[1])
        mfe, t_mfe = pct(hi[1]), hi[0]
        mae, t_mae = pct(lo[1]), lo[0]
    h_exit, h_mfe, h_mae = {}, {}, {}
    for h in config.horizons_seconds:
        within = [p for p in path if p[0] <= h]
        h_exit[h] = pct(within[-1][1]) if within else None
        h_mfe[h] = max(pct(p[1]) for p in within) if within else None
        h_mae[h] = min(pct(p[1]) for p in within) if within else None
    und = None
    if path:
        a, b = session.fut_ffill(path[-1][2]), session.fut_ffill(entry_index)
        if a is not None and b is not None:
            und = (a - b) * direction
    return Counterfactual(entry_index, t0, ask, q0.spread_pct, mfe, mae, t_mfe, t_mae, h_exit, h_mfe, h_mae,
                          und, complete)
