"""Opportunity remaining at detection: early vs late vs no follow-through."""

import pytest

from scalp_12a.config import ScalpConfig
from scalp_12a.engine import evaluate_session
from scalp_12a.models import Event
from scalp_12a.opportunity import DETECTED_EARLY, DETECTED_LATE, NO_FOLLOW_THROUGH, UNKNOWN, measure
from scalp_12a import taxonomy as T
from tests.scalp12a_factory import flat_then, make_session, thresholds

CFG = ScalpConfig()


def _event(i, origin):
    return Event(i, T.MOMENTUM_EVENT, T.STRONG, 1, None, 15.0, None, None, None, 15.0, origin)


def test_detected_early_when_most_of_the_move_is_still_ahead():
    # +15 in 30 s (bars 64..70) then a long run: +60 more
    path = [23400.0] * 64 + [23400.0 + 2.5 * k for k in range(1, 7)] + [23415.0 + 1.5 * k for k in range(1, 41)] + [23475.0] * 60
    s = make_session(path)
    o = measure(s, _event(69, 23400.0), 69, 71, ("CE", 0), CFG)
    assert o.timing == DETECTED_EARLY
    assert o.remaining_fraction_at_entry > 0.5 and o.fut_mfe_after_detection > 50
    assert o.detection_bar_end_ts == s.times[69].replace() + (s.times[1] - s.times[0])
    assert o.t_fut_mfe_after_detection_s > 0 and o.fut_mae_after_detection == 0.0


def test_detected_late_when_most_of_the_move_already_happened():
    # +40 already done at detection, only +5 more afterwards
    path = [23400.0] * 64 + [23400.0 + 8.0 * k for k in range(1, 6)] + [23440.0 + 1.0 * k for k in range(1, 6)] + [23445.0] * 80
    s = make_session(path)
    o = measure(s, _event(68, 23400.0), 68, 70, ("CE", 0), CFG)      # bar 68 = last bar of the +40 run
    assert o.timing == DETECTED_LATE
    assert o.realized_at_detection == pytest.approx(40.0) and o.remaining_fraction_at_entry < 0.5


def test_no_follow_through_when_move_is_over_at_entry():
    path = [23400.0] * 64 + [23400.0 + 3.0 * k for k in range(1, 6)] + [23415.0 - 0.5 * k for k in range(1, 81)]
    s = make_session(path)
    o = measure(s, _event(68, 23400.0), 68, 70, ("CE", 0), CFG)
    assert o.timing == NO_FOLLOW_THROUGH and o.remaining_after_entry == 0.0 and o.fut_mae_after_detection < 0


def test_unknown_while_live_horizon_is_open():
    path = [23400.0] * 64 + [23400.0 + 2.5 * k for k in range(1, 7)] + [23416.0] * 5
    s = make_session(path)
    assert measure(s, _event(69, 23400.0), 69, 71, ("CE", 0), CFG, session_complete=False).timing == UNKNOWN


def test_every_candidate_carries_the_measurement_including_rejected_ones():
    s = make_session(flat_then(250, [2.5] * 6))                      # Mode B: never tradeable in v1
    c = [c for c in evaluate_session(s, thresholds(), CFG).candidates if c.event.strength == T.STRONG][0]
    assert not c.would_trade and c.opportunity is not None and c.opportunity.timing != UNKNOWN


def test_measurement_does_not_change_decisions_or_hash():
    assert CFG.config_hash() == "994667c6d552111e"
