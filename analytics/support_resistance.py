import math
from dataclasses import dataclass, field

from analytics.swings import SwingPoint
from analytics.volume_profile import VolumeProfileResult


@dataclass
class Candidate:
    price: float
    kind: str


@dataclass
class Zone:
    low: float
    high: float
    strength: int
    members: list = field(default_factory=list)


def round_number_candidates(current_price: float, step: float, range_pct: float = 0.03) -> list[Candidate]:
    lo = current_price * (1 - range_pct)
    hi = current_price * (1 + range_pct)
    start = math.floor(lo / step) * step
    out = []
    level = start
    while level <= hi:
        if lo <= level <= hi:
            out.append(Candidate(price=level, kind="round_number"))
        level += step
    return out


def build_candidates(
    current_price: float,
    round_number_step: float,
    prior_day_high: float | None = None,
    prior_day_low: float | None = None,
    prior_day_close: float | None = None,
    today_vp: VolumeProfileResult | None = None,
    yesterday_vp: VolumeProfileResult | None = None,
    confirmed_swings: list[SwingPoint] | None = None,
) -> list[Candidate]:
    candidates: list[Candidate] = []

    if prior_day_high is not None:
        candidates.append(Candidate(prior_day_high, "prior_day_high"))
    if prior_day_low is not None:
        candidates.append(Candidate(prior_day_low, "prior_day_low"))
    if prior_day_close is not None:
        candidates.append(Candidate(prior_day_close, "prior_day_close"))

    if today_vp is not None:
        candidates.append(Candidate(today_vp.vah, "today_vah"))
        candidates.append(Candidate(today_vp.val, "today_val"))
        candidates.append(Candidate(today_vp.poc, "today_poc"))

    if yesterday_vp is not None:
        candidates.append(Candidate(yesterday_vp.vah, "yesterday_vah"))
        candidates.append(Candidate(yesterday_vp.val, "yesterday_val"))
        candidates.append(Candidate(yesterday_vp.poc, "yesterday_poc"))

    for s in confirmed_swings or []:
        candidates.append(Candidate(s.price, f"swing_{s.kind}"))

    candidates.extend(round_number_candidates(current_price, round_number_step))
    return candidates


def cluster_zones(candidates: list[Candidate], tolerance_pct: float) -> list[Zone]:
    if not candidates:
        return []

    # Anchor each group to its lowest member (not a running mean): comparing
    # against a drifting mean lets a chain of small pairwise gaps "walk" the
    # zone arbitrarily wide (e.g. 20 points apart, 15 times over = 300pt
    # zone even though tolerance_pct alone implies ~100pt). Anchoring caps
    # every zone's total width at roughly tolerance_pct of its base price.
    sorted_c = sorted(candidates, key=lambda c: c.price)
    groups: list[list[Candidate]] = [[sorted_c[0]]]

    for c in sorted_c[1:]:
        anchor = groups[-1][0].price
        if anchor > 0 and (c.price - anchor) <= tolerance_pct * anchor:
            groups[-1].append(c)
        else:
            groups.append([c])

    zones = []
    for members in groups:
        prices = [m.price for m in members]
        lo, hi = min(prices), max(prices)
        mid = (lo + hi) / 2
        min_width = 0.0005 * mid
        if hi - lo < min_width:
            lo, hi = mid - min_width / 2, mid + min_width / 2
        strength = len({m.kind for m in members})
        zones.append(Zone(low=lo, high=hi, strength=strength, members=members))
    return zones


def nearest_support_resistance(zones: list[Zone], current_price: float) -> tuple[Zone | None, Zone | None]:
    """Returns (support_zone, resistance_zone) nearest to current_price."""
    above = [z for z in zones if z.low > current_price]
    below = [z for z in zones if z.high < current_price]
    resistance = min(above, key=lambda z: z.low) if above else None
    support = max(below, key=lambda z: z.high) if below else None
    return support, resistance
