"""Additive, parallel re-analysis of the 3pm transition under NSE's Closing
Auction Session (CAS) framework, effective 2026-08-03 (F&O close extended
15:30->15:40; the derivative closing-price VWAP window is now 15:10-15:40 --
see config/settings.py's SESSION_CLOSE comment). feature_extraction.py's
original design -- a sharp "15:00-15:01 transition moment" followed by
15:01-close continuous-trading follow-through -- predates this: for every
session after 2026-08-03, a large part of what used to be free continuous
trading is now inside the CAS/VWAP-averaging window, so a single 2-minute
pivot point is a less meaningful place to draw the "before vs after" line.

This module re-frames the same continuation/reversal/neutral question as a
TREND comparison between two windows instead of a point-to-point move:
  - Pre-window:  14:31-14:59 (the trend heading into 3pm, baselined against
    the 14:31 price)
  - Post-window: 15:00-15:39 (the trend across the new post-3pm regime,
    CAS mechanics included -- explicitly capped at 15:39 rather than "the
    session's last candle": a handful of days carry a stray zero-volume
    candle timestamped after the real 15:40 close (Dhan echoing the last
    traded price once the session has actually ended), which would
    otherwise corrupt market_close if picked up as "the last candle").

Deliberately reuses every existing building block unmodified:
market_transition.feature_extraction.compute_pre_window_features (via its
new pre_window_start parameter), market_transition.statistics.
run_correlation_study, and market_transition.scoring.score_day never need
to know which window definition produced the records they're given -- they
only ever read DailyTransitionRecord.outcome.outcome/.outcome_magnitude.

Entirely additive: does NOT touch mti_daily_transitions/
mti_factor_correlations (the tables the live dashboard and Live Advisor
read) or any live-facing code path. This is a side-by-side research
comparison over the same already-collected raw_candles history -- see
scripts/run_cas_transition_analysis.py -- not a replacement, until/unless
its findings are deliberately promoted later.
"""

from datetime import date, time

import pandas as pd

from market_transition.feature_extraction import _direction, _time_between, compute_pre_window_features
from market_transition.models import DailyTransitionRecord, ExpiryType, TransitionOutcome

CAS_PRE_WINDOW_START = time(14, 31)
CAS_PRE_WINDOW_END = time(14, 59)
CAS_POST_WINDOW_START = time(15, 0)
CAS_POST_WINDOW_END = time(15, 39)


def window_volume(today_candles: pd.DataFrame, start: time, end: time) -> float | None:
    """Total traded volume in [start, end] -- a separate, deliberately
    small helper (not threaded through TransitionOutcome, which is shared
    with the original, unmodified pipeline) so callers can compare how
    much volume traded pre-3pm vs post-3pm alongside the direction/outcome
    call above."""
    window = _time_between(today_candles, start, end)
    if window.empty:
        return None
    return float(window["volume"].sum())


def extract_cas_transition_record(
    symbol: str,
    session_date: date,
    today_candles: pd.DataFrame,
    prior_day_candles: pd.DataFrame | None,
    historical_by_date: dict[date, pd.DataFrame],
    bin_size: float,
    expiry_type: ExpiryType | None,
) -> DailyTransitionRecord | None:
    """Same call signature as feature_extraction.extract_daily_transition_record
    (so market_transition.research.run_research's extract_fn parameter can
    swap between the two), just with the CAS-adjusted windows above. A day
    is skipped (returns None) if there's no candle data in either window --
    same "exclude, don't fabricate" discipline as the original."""
    if today_candles.empty:
        return None

    pre_window = _time_between(today_candles, CAS_PRE_WINDOW_START, CAS_PRE_WINDOW_END)
    post_window = _time_between(today_candles, CAS_POST_WINDOW_START, CAS_POST_WINDOW_END)
    if pre_window.empty or post_window.empty:
        return None

    features = compute_pre_window_features(
        today_candles,
        prior_day_candles,
        historical_by_date,
        bin_size,
        expiry_type,
        session_date,
        pre_window_end=CAS_PRE_WINDOW_END,
        pre_window_start=CAS_PRE_WINDOW_START,
    )
    if features is None:
        return None

    baseline_1431 = float(pre_window["close"].iloc[0])
    close_1459 = float(pre_window["close"].iloc[-1])
    market_close = float(post_window["close"].iloc[-1])

    pre_trend_move = close_1459 - baseline_1431
    pre_trend_direction = _direction(pre_trend_move, baseline_1431)
    post_trend_move = market_close - close_1459

    if pre_trend_direction == "flat":
        outcome = "neutral"
    else:
        post_direction = _direction(post_trend_move, close_1459)
        if post_direction == "flat":
            outcome = "neutral"
        elif post_direction == pre_trend_direction:
            outcome = "continuation"
        else:
            outcome = "reversal"

    # Field names kept identical to TransitionOutcome's original shape so
    # statistics.py/scoring.py need zero changes -- close_1459 stays the
    # pivot close, transition_move/post_transition_move now describe the
    # pre-3pm and post-3pm TREND windows rather than a 2-minute point move.
    outcome_record = TransitionOutcome(
        close_1459=close_1459,
        close_1501=float(post_window["close"].iloc[0]),
        market_close=market_close,
        transition_move=pre_trend_move,
        transition_direction=pre_trend_direction,
        post_transition_move=post_trend_move,
        outcome=outcome,
        outcome_magnitude=abs(post_trend_move),
    )

    return DailyTransitionRecord(symbol=symbol, session_date=session_date, features=features, outcome=outcome_record)
