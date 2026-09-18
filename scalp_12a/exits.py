"""Proactive exit engine: momentum failure is a first-class exit.

Entry fills at the ASK of bar e (decision bar + entry_delay_bars); every exit
is valued at the BID. Each later bar is checked in a fixed, conservative
order (stop before target). The stop only ever tightens: the trailing rule
may raise it, nothing lowers it (``stop_history`` is non-decreasing).
"""

from scalp_12a.config import ScalpConfig
from scalp_12a.models import Event, ExitResult, RiskPlan, SessionBars
from scalp_12a.modes import forced_exit_time
from scalp_12a.taxonomy import (
    EXIT_EVENT_INVALIDATED, EXIT_EXPIRY_ZONE, EXIT_FUTURES_DIVERGENCE, EXIT_MOMENTUM_FADE, EXIT_MOMENTUM_FAILURE,
    EXIT_NO_DATA, EXIT_SESSION_END, EXIT_SPREAD_EXPANSION, EXIT_STALE_DATA, EXIT_STOP, EXIT_TARGET, EXIT_TIME,
    EXIT_TRAIL, EXIT_UNDERLYING_INVALIDATION,
)

OPEN = "OPEN"   # data ended before any exit condition (live shadow, still running)


def simulate_exit(session: SessionBars, key, entry_index: int, event: Event, plan: RiskPlan,
                  config: ScalpConfig, session_complete: bool = True) -> ExitResult:
    entry_q = session.quote(key, entry_index)
    if entry_q is None or not entry_q.valid:
        return ExitResult(entry_index, 0.0, None, None, EXIT_NO_DATA, None, None, None, None, [])
    ask = entry_q.ask
    entry_spread = entry_q.spread_pct or 0.0
    stop = ask * (1 - plan.stop_pct / 100.0)
    target = ask * (1 + plan.target_pct / 100.0)
    stops = [stop]
    t0 = session.times[entry_index]
    forced = forced_exit_time(session.is_expiry_day, config)
    d = event.direction
    disp = abs(event.displacement)
    entry_fut = session.fut_ffill(entry_index)
    peak, worst = 0.0, 0.0
    last_bid, last_k = None, None
    missing = 0

    def done(k, bid, reason):
        pnl = (bid - ask) / ask * 100.0 if bid is not None else None
        hold = (session.times[k] - t0).total_seconds() if k is not None else None
        return ExitResult(entry_index, ask, k, bid, reason, pnl, hold, peak, worst, stops,
                          session.times[k] if k is not None else None)

    for k in range(entry_index + 1, len(session)):
        ts = session.times[k]
        elapsed = (ts - t0).total_seconds()
        if ts.time() >= forced:
            reason = EXIT_EXPIRY_ZONE if session.is_expiry_day else EXIT_SESSION_END
            q = session.quote(key, k)
            bid = q.bid if q and q.valid else last_bid
            return done(k if q and q.valid else last_k, bid, reason)
        q = session.quote(key, k)
        if q is None or not q.valid:
            missing += 1
            if missing >= config.stale_quote_bars and last_bid is not None:
                return done(last_k, last_bid, EXIT_STALE_DATA)
            continue
        missing = 0
        bid = q.bid
        last_bid, last_k = bid, k
        gain = (bid - ask) / ask * 100.0
        peak, worst = max(peak, gain), min(worst, gain)

        if bid <= stop:
            return done(k, bid, EXIT_TRAIL if stop > stops[0] else EXIT_STOP)
        if bid >= target:
            return done(k, bid, EXIT_TARGET)
        fut = session.fut_ffill(k)
        if fut is not None and (fut - plan.underlying_invalidation) * d <= 0:
            return done(k, bid, EXIT_UNDERLYING_INVALIDATION)
        if fut is not None and entry_fut is not None and disp > 0:
            from_origin = (fut - event.origin_price) * d
            if from_origin <= disp * (1 - config.event_retrace_frac):
                return done(k, bid, EXIT_EVENT_INVALIDATED)
            if (fut - entry_fut) * d >= disp * config.divergence_frac and bid < ask:
                return done(k, bid, EXIT_FUTURES_DIVERGENCE)
        if elapsed >= config.no_progress_seconds and peak <= 0:
            return done(k, bid, EXIT_MOMENTUM_FAILURE)
        if peak >= config.fade_activation_pct and gain <= peak * (1 - config.fade_giveback_frac):
            return done(k, bid, EXIT_MOMENTUM_FADE)
        if q.spread_pct is not None and q.spread_pct >= max(config.exit_spread_multiple * entry_spread,
                                                            config.exit_spread_floor_pct):
            return done(k, bid, EXIT_SPREAD_EXPANSION)
        if elapsed >= plan.max_hold_seconds:
            return done(k, bid, EXIT_TIME)
        if peak >= config.trail_activation_pct:
            new_stop = ask * (1 + config.trail_lock_frac * peak / 100.0)
            if new_stop > stop:          # tighten only
                stop = new_stop
                stops.append(stop)

    if not session_complete:
        return ExitResult(entry_index, ask, None, None, OPEN, None, None, peak, worst, stops)
    return done(last_k, last_bid, EXIT_SESSION_END if last_bid is not None else EXIT_NO_DATA)
