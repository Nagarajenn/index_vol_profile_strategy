"""Event detector (futures-led; works in Mode A and Mode B).

Uses ONLY bars 0..i. The index is never used as a price source, because it
is frozen from 15:15 (gap analysis: 155-156 of 156 bars flat).

Shapes:
* MOMENTUM_EVENT     -- a 30 s futures burst beyond the causal threshold;
* REVERSAL_EVENT     -- such a burst opposite to a meaningful prior 3-minute move;
* CONTINUATION_EVENT -- no burst, but a consistent 3-minute grind beyond the
                        180 s threshold (the 09-18 SENSEX -134 type);
* NO_EVENT.
A burst between the weak and event percentiles is returned as a WEAK event
so the rejection (WEAK_MOMENTUM) and its counterfactual are recorded.
"""

from scalp_12a.config import ScalpConfig
from scalp_12a.models import Event, SessionBars, Thresholds
from scalp_12a.taxonomy import CONTINUATION_EVENT, MOMENTUM_EVENT, REVERSAL_EVENT, STRONG, WEAK


def _move(session: SessionBars, i: int, lag: int) -> float | None:
    if i - lag < 0:
        return None
    a, b = session.fut_ffill(i), session.fut_ffill(i - lag)
    return None if a is None or b is None else a - b


def futures_stale(session: SessionBars, i: int, config: ScalpConfig) -> bool:
    limit = config.futures_stale_seconds // config.bar_seconds
    for k in range(i, max(-1, i - limit - 1), -1):
        if session.fut_updated[k]:
            return False
    return True


def step_consistency(session: SessionBars, i: int, bars: int, direction: int) -> float | None:
    steps = []
    for k in range(max(1, i - bars + 1), i + 1):
        a, b = session.fut_ffill(k), session.fut_ffill(k - 1)
        if a is not None and b is not None and a != b:
            steps.append(1 if (a - b) * direction > 0 else 0)
    return sum(steps) / len(steps) if steps else None


def detect_event(session: SessionBars, i: int, thr: Thresholds, config: ScalpConfig) -> Event | None:
    if not thr.sufficient:
        return None
    b = config.bar_seconds
    r15, r30 = _move(session, i, 15 // b), _move(session, i, 30 // b)
    r180, r300 = _move(session, i, 180 // b), _move(session, i, 300 // b)
    r180_prior = None
    if i - 30 // b >= 0:
        r180_prior = _move(session, i - 30 // b, 180 // b)
    if r30 is None:
        return None

    def build(etype, strength, direction, displacement, origin_lag, consistency=None):
        origin = session.fut_ffill(i - origin_lag)
        return Event(i, etype, strength, direction, r15, r30, r180, r180_prior, r300,
                     displacement, origin, consistency)

    if abs(r30) >= thr.thr30_weak:
        direction = 1 if r30 > 0 else -1
        strength = STRONG if abs(r30) >= thr.thr30_event else WEAK
        reversal = (r180_prior is not None and r180_prior * direction < 0
                    and abs(r180_prior) >= config.reversal_prior_min_multiple * thr.thr30_event)
        return build(REVERSAL_EVENT if reversal else MOMENTUM_EVENT, strength, direction, r30, 30 // b)

    if r180 is not None and abs(r180) >= thr.thr180_event:
        direction = 1 if r180 > 0 else -1
        cons = step_consistency(session, i, 180 // b, direction)
        if cons is not None and cons >= config.continuation_consistency:
            return build(CONTINUATION_EVENT, STRONG, direction, r180, 180 // b, cons)
    return None
