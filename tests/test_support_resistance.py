import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from analytics.support_resistance import (
    Candidate,
    cluster_zones,
    nearest_support_resistance,
    round_number_candidates,
)


def test_cluster_zones_groups_nearby_prices():
    candidates = [
        Candidate(77000, "prior_day_low"),
        Candidate(77020, "swing_low"),
        Candidate(77500, "today_poc"),
        Candidate(77550, "swing_high"),
        Candidate(78000, "round_number"),
    ]
    zones = cluster_zones(candidates, tolerance_pct=0.001)

    assert len(zones) == 3
    assert zones[0].low <= 77000 and zones[0].high >= 77020
    assert zones[1].low <= 77500 and zones[1].high >= 77550
    # the lone 78000 candidate becomes a zero-width zone, padded so it's never a single point
    assert zones[2].high > zones[2].low


def test_nearest_support_resistance_picks_closest_zones():
    candidates = [
        Candidate(77000, "prior_day_low"),
        Candidate(77020, "swing_low"),
        Candidate(77500, "today_poc"),
        Candidate(77550, "swing_high"),
        Candidate(78000, "round_number"),
    ]
    zones = cluster_zones(candidates, tolerance_pct=0.001)

    support, resistance = nearest_support_resistance(zones, current_price=77300)

    assert support is not None and support.high <= 77300
    assert resistance is not None and resistance.low >= 77300
    assert resistance.low == pytest.approx(77500, abs=1)


def test_no_resistance_when_price_above_all_zones():
    zones = cluster_zones([Candidate(100, "x"), Candidate(101, "y")], tolerance_pct=0.01)
    support, resistance = nearest_support_resistance(zones, current_price=1000)
    assert resistance is None
    assert support is not None


def test_round_number_candidates_within_range():
    candidates = round_number_candidates(current_price=100, step=10, range_pct=0.03)
    prices = [c.price for c in candidates]
    assert prices == [100]
