import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import IST
from pipeline.live_loop import _next_boundary


def test_next_boundary_rounds_up_within_hour():
    now = datetime(2026, 7, 17, 10, 3, 12, tzinfo=IST)
    assert _next_boundary(now, 5) == datetime(2026, 7, 17, 10, 5, tzinfo=IST)


def test_next_boundary_exactly_on_boundary_goes_to_next_one():
    now = datetime(2026, 7, 17, 10, 5, 0, tzinfo=IST)
    assert _next_boundary(now, 5) == datetime(2026, 7, 17, 10, 10, tzinfo=IST)


def test_next_boundary_rolls_over_hour():
    now = datetime(2026, 7, 17, 10, 58, 0, tzinfo=IST)
    assert _next_boundary(now, 5) == datetime(2026, 7, 17, 11, 0, tzinfo=IST)
