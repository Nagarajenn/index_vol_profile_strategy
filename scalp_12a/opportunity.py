"""Opportunity remaining at detection (research measurement only).

Answers: when 12A *detected* an event, how much of the move was still ahead,
and how much was left by the time a realistic order could fill?

Measured on the futures (the price reference that stays live in Mode B) and
on the chosen option. It reads bars AFTER detection, so it is outcome
measurement only -- it never feeds a decision, and it is not part of the
config hash.

Timing classes (descriptive research labels, NOT trading rules):
* DETECTED_EARLY     -- at the realistic entry, >= EARLY_REMAINING_FRACTION of the
                        event's total favourable futures move was still ahead;
* DETECTED_LATE      -- a follow-through existed, but most of the move had already
                        happened before the entry could fill;
* NO_FOLLOW_THROUGH  -- no further favourable futures move after the entry (the move
                        was over by the time it could be traded);
* UNKNOWN            -- not enough data (e.g. live, horizon still open).
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

from scalp_12a.config import ScalpConfig
from scalp_12a.models import Event, SessionBars

EARLY_REMAINING_FRACTION = 0.5
DETECTED_EARLY = "DETECTED_EARLY"
DETECTED_LATE = "DETECTED_LATE"
NO_FOLLOW_THROUGH = "NO_FOLLOW_THROUGH"
UNKNOWN = "UNKNOWN"


@dataclass
class Opportunity:
    event_start_ts: datetime | None
    event_start_fut: float | None
    detection_bar_end_ts: datetime
    detection_fut: float | None
    detection_option_mid: float | None
    detection_option_ask: float | None
    entry_ts: datetime | None
    entry_fut: float | None
    entry_ask: float | None
    realized_at_detection: float | None     # favourable futures points from event start to detection
    realized_at_entry: float | None         # ... to the realistic entry
    fut_mfe_after_detection: float | None   # further favourable points after detection (horizon)
    fut_mae_after_detection: float | None   # adverse points after detection (<= 0)
    t_fut_mfe_after_detection_s: float | None
    t_fut_mae_after_detection_s: float | None
    remaining_after_entry: float | None     # favourable points still available after the entry
    total_move: float | None                # event start -> best favourable extreme in the horizon
    remaining_fraction_at_detection: float | None
    remaining_fraction_at_entry: float | None
    option_move_before_entry_pct: float | None   # option mid, event start -> entry ask
    timing: str
    complete: bool


def measure(session: SessionBars, event: Event, i: int, entry_index: int, key, config: ScalpConfig,
            session_complete: bool = True) -> Opportunity:
    d = event.direction
    b = config.bar_seconds
    lag = (180 if event.event_type == "CONTINUATION_EVENT" else 30) // b
    start_i = max(0, i - lag)
    horizon = max(config.horizons_seconds) // b
    n = len(session)
    last_i = min(n - 1, entry_index + horizon)
    complete = session_complete or (entry_index + horizon) < n

    f_start = session.fut_ffill(start_i)
    f_det = session.fut_ffill(i)
    f_entry = session.fut_ffill(entry_index) if entry_index < n else None
    q_det = session.quote(key, i)
    q_entry = session.quote(key, entry_index) if entry_index < n else None
    q_start = session.quote(key, start_i)

    fav = lambda f, base: None if f is None or base is None else (f - base) * d
    after = [(k, session.fut_ffill(k)) for k in range(i + 1, last_i + 1)]
    after = [(k, f) for k, f in after if f is not None]
    mfe = mae = t_mfe = t_mae = None
    if after and f_det is not None:
        best = max(after, key=lambda kf: fav(kf[1], f_det))
        worst = min(after, key=lambda kf: fav(kf[1], f_det))
        mfe, mae = max(0.0, fav(best[1], f_det)), min(0.0, fav(worst[1], f_det))
        t_mfe = (best[0] - i) * b if mfe > 0 else None
        t_mae = (worst[0] - i) * b if mae < 0 else None

    rem_entry = None
    after_entry = [session.fut_ffill(k) for k in range(entry_index + 1, last_i + 1)] if entry_index < n else []
    after_entry = [f for f in after_entry if f is not None]
    if after_entry and f_entry is not None:
        rem_entry = max(0.0, max(fav(f, f_entry) for f in after_entry))

    real_det, real_entry = fav(f_det, f_start), fav(f_entry, f_start)
    total = None
    if real_det is not None and mfe is not None:
        total = max(real_det, real_det + mfe)
    frac_det = (mfe / total) if (total and total > 0 and mfe is not None) else None
    frac_entry = (rem_entry / total) if (total and total > 0 and rem_entry is not None) else None

    opt_before = None
    if q_start and q_start.mid and q_entry and q_entry.valid:
        opt_before = (q_entry.ask - q_start.mid) / q_start.mid * 100.0

    if not complete or rem_entry is None or total is None:
        timing = UNKNOWN
    elif rem_entry <= 0:
        timing = NO_FOLLOW_THROUGH
    elif frac_entry is not None and frac_entry >= EARLY_REMAINING_FRACTION:
        timing = DETECTED_EARLY
    else:
        timing = DETECTED_LATE

    return Opportunity(
        event_start_ts=session.times[start_i], event_start_fut=f_start,
        detection_bar_end_ts=session.times[i] + timedelta(seconds=b), detection_fut=f_det,
        detection_option_mid=q_det.mid if q_det else None, detection_option_ask=q_det.ask if q_det else None,
        entry_ts=session.times[entry_index] if entry_index < n else None, entry_fut=f_entry,
        entry_ask=q_entry.ask if q_entry and q_entry.valid else None,
        realized_at_detection=real_det, realized_at_entry=real_entry,
        fut_mfe_after_detection=mfe, fut_mae_after_detection=mae,
        t_fut_mfe_after_detection_s=t_mfe, t_fut_mae_after_detection_s=t_mae,
        remaining_after_entry=rem_entry, total_move=total,
        remaining_fraction_at_detection=frac_det, remaining_fraction_at_entry=frac_entry,
        option_move_before_entry_pct=opt_before, timing=timing, complete=complete)
