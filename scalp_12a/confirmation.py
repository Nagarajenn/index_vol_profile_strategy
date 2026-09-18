"""Event confirmation: displacement + option response + persistence (+ not extended).

Structural 1-minute information (VWAP, POC, trend, PCR, CAS, bias) is
recorded as CONTEXT by the engine and is never a veto here.
"""

from scalp_12a.config import ScalpConfig
from scalp_12a.events import step_consistency
from scalp_12a.models import Event, Selection, SessionBars, Thresholds
from scalp_12a.taxonomy import (
    CONTINUATION_EVENT, MOVE_ALREADY_EXTENDED, NO_CONFIRMATION, OPTION_NOT_RESPONDING, WEAK, WEAK_MOMENTUM,
)


def confirm(session: SessionBars, event: Event, selection: Selection, i: int, thr: Thresholds,
            config: ScalpConfig) -> tuple[list[str], dict]:
    reasons: list[str] = []
    detail: dict = {}

    detail["displacement_ok"] = event.strength != WEAK
    if event.strength == WEAK:
        reasons.append(WEAK_MOMENTUM)

    resp = selection.response_pct if selection else None
    detail["option_response_pct"] = resp
    detail["option_response_ok"] = resp is not None and resp >= config.min_option_response_pct
    if selection and selection.leg and not detail["option_response_ok"]:
        reasons.append(OPTION_NOT_RESPONDING)

    cons = step_consistency(session, i, config.persistence_window_bars, event.direction)
    needed = config.persistence_min_bars / config.persistence_window_bars
    detail["persistence"] = cons
    detail["persistence_ok"] = cons is not None and cons >= needed
    if not detail["persistence_ok"]:
        reasons.append(NO_CONFIRMATION)

    if event.event_type == CONTINUATION_EVENT:
        limit = 2.0 * thr.thr180_event
    else:
        limit = config.extension_multiple * thr.thr30_event
    prior = event.r300 - event.displacement if event.r300 is not None else None
    detail["prior_extension"] = prior
    detail["extension_limit"] = limit
    detail["extended"] = prior is not None and prior * event.direction >= limit
    if detail["extended"]:
        reasons.append(MOVE_ALREADY_EXTENDED)
    return reasons, detail
