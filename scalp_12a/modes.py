"""Market-mode classification and the evidence-backed expiry-day vetoes."""

from datetime import datetime, time

from scalp_12a.config import ScalpConfig
from scalp_12a.taxonomy import (
    EXPIRY_DAY_CLOSE_VETO, EXPIRY_TRANSITION_ZONE, MODE_A, MODE_B, MODE_B_RESEARCH_ONLY, MODE_CLOSED, MODE_PRE,
    TIME_WINDOW_CLOSED,
)


def _t(s: str) -> time:
    return time.fromisoformat(s)


def market_mode(ts: datetime, config: ScalpConfig) -> str:
    t = ts.time()
    if t < _t(config.mode_a_start):
        return MODE_PRE
    if t < _t(config.mode_b_start):
        return MODE_A
    if t < _t(config.mode_b_end):
        return MODE_B
    return MODE_CLOSED


def window_vetoes(ts: datetime, is_expiry_day: bool, config: ScalpConfig) -> list[str]:
    """Time/mode reasons that forbid a v1 entry at ``ts`` (bar decision time)."""
    reasons = []
    t = ts.time()
    mode = market_mode(ts, config)
    if mode in (MODE_PRE, MODE_CLOSED):
        reasons.append(TIME_WINDOW_CLOSED)
    if is_expiry_day and t >= _t(config.expiry_close_veto_start):
        reasons.append(EXPIRY_DAY_CLOSE_VETO)
    elif is_expiry_day and t >= _t(config.expiry_transition_zone_start):
        reasons.append(EXPIRY_TRANSITION_ZONE)
    if mode == MODE_B and not config.mode_b_tradeable:
        reasons.append(MODE_B_RESEARCH_ONLY)
    return reasons


def forced_exit_time(is_expiry_day: bool, config: ScalpConfig) -> time:
    """Latest time a position may remain open."""
    return _t(config.expiry_forced_exit) if is_expiry_day else _t(config.session_exit_by)
