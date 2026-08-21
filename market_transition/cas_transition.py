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

Volume is a separate story (confirmed 2026-08-21 across multiple post-CAS
days/symbols): Dhan's 1-minute feed keeps reporting genuine, moving prices
all the way through 15:39, but its per-minute VOLUME field freezes at a
single value starting exactly at 15:15 -- the documented start of NSE's
Closing Auction Session -- and stays frozen through session close. So
price-based direction/outcome calls use the full 15:00-15:39 post-window,
but volume is only ever summed through 15:14 (POST_VOLUME_RELIABLE_END)
and reported as "pre-auction volume" -- it does not, and cannot yet, claim
to cover the full post-window the way the price side does.

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

from dataclasses import dataclass
from datetime import date, time

import pandas as pd

from market_transition.feature_extraction import _direction, _time_between, compute_pre_window_features
from market_transition.models import DailyTransitionRecord, ExpiryType, TransitionOutcome

CAS_EFFECTIVE_DATE = date(2026, 8, 3)  # NSE's Closing Auction Session framework start date

CAS_PRE_WINDOW_START = time(14, 31)
CAS_PRE_WINDOW_END = time(14, 59)
CAS_POST_WINDOW_START = time(15, 0)
CAS_POST_WINDOW_END = time(15, 39)

# NSE's Closing Auction Session starts at 15:15; Dhan's 1-min volume field
# is not reliable from that point through close (see module docstring), so
# post-window volume is only ever summed through this cutoff.
POST_VOLUME_RELIABLE_END = time(15, 14)

# >= this many consecutive candles sharing an identical (close, volume) pair
# within a RELIABLE window (pre-window, or post-window through 15:14) flags
# a day's data as suspect -- discovered 2026-08-21: 3 NIFTY days had 10-13
# minutes frozen at one value well before the auction even started (a
# stuck/duplicated Dhan fetch, not the expected post-15:15 volume freeze),
# inflating volume by 10-50x and potentially corrupting the direction call
# too. Deliberately never checked against 15:15-15:39, which is *always*
# volume-frozen post-CAS and would trip this on every single day for no
# useful signal.
STUCK_CANDLE_MIN_RUN = 5


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


@dataclass
class CasDailyTransition:
    """One persisted row: the CAS-adjusted call for one symbol/session_date,
    the same day's outcome under the original (unmodified) methodology for
    side-by-side comparison, and the option-chain context at ~14:59."""

    symbol: str
    session_date: date
    close_1431: float | None
    close_1459: float | None
    close_1539: float | None
    pre_direction: str | None
    post_direction: str | None
    conclusion: str
    outcome_magnitude: float
    pre_window_volume: float | None
    post_window_pre_auction_volume: float | None
    volume_ratio: float | None
    pre_window_points_move: float | None
    post_window_points_move: float | None
    pcr_1459: float | None
    institutional_bias_label_1459: str | None
    institutional_bias_score_1459: int | None
    expiry_type: str | None
    day_of_week: int
    old_methodology_outcome: str | None
    old_methodology_outcome_magnitude: float | None
    data_quality_flag: str | None = None


def _points_move(window: pd.DataFrame, direction: str, baseline: float) -> float | None:
    """Points gained toward `direction` using the best print actually
    reached in `window` (its high for "up", its low for "down"), not just
    the window's close-to-close net move -- answers "how far did it
    actually run in its own direction" rather than "where did it end up"."""
    if window.empty:
        return None
    if direction == "up":
        return float(window["high"].max() - baseline)
    if direction == "down":
        return float(baseline - window["low"].min())
    return 0.0


def _has_stuck_candles(window: pd.DataFrame, min_run: int = STUCK_CANDLE_MIN_RUN) -> bool:
    if window.empty or len(window) < min_run:
        return False
    same_as_prev = (window["close"] == window["close"].shift()) & (window["volume"] == window["volume"].shift())
    run_id = (~same_as_prev).cumsum()
    run_length = same_as_prev.groupby(run_id).cumsum() + 1
    return bool((run_length >= min_run).any())


def build_cas_daily_transition(
    symbol: str,
    session_date: date,
    today_candles: pd.DataFrame,
    prior_day_candles: pd.DataFrame | None,
    historical_by_date: dict[date, pd.DataFrame],
    bin_size: float,
    expiry_type: ExpiryType | None,
    old_outcome: str | None = None,
    old_outcome_magnitude: float | None = None,
    option_context: dict | None = None,
) -> CasDailyTransition | None:
    """`option_context`, if supplied, is {"pcr": float|None, "bias_label":
    str, "bias_score": int|None} -- already resolved by the caller from an
    option_chain_summary snapshot near 14:59 (this module has no DB access
    of its own, same discipline as the rest of market_transition/)."""
    record = extract_cas_transition_record(
        symbol, session_date, today_candles, prior_day_candles, historical_by_date, bin_size, expiry_type
    )
    if record is None:
        return None

    pre_window = _time_between(today_candles, CAS_PRE_WINDOW_START, CAS_PRE_WINDOW_END)
    post_window = _time_between(today_candles, CAS_POST_WINDOW_START, CAS_POST_WINDOW_END)
    post_reliable_window = _time_between(today_candles, CAS_POST_WINDOW_START, POST_VOLUME_RELIABLE_END)
    pre_vol = window_volume(today_candles, CAS_PRE_WINDOW_START, CAS_PRE_WINDOW_END)
    post_vol = window_volume(today_candles, CAS_POST_WINDOW_START, POST_VOLUME_RELIABLE_END)
    vol_ratio = (post_vol / pre_vol) if (pre_vol and post_vol) else None

    post_direction = _direction(record.outcome.post_transition_move, record.outcome.close_1459)

    baseline_1431 = float(pre_window["close"].iloc[0]) if not pre_window.empty else None
    pre_points_move = (
        _points_move(pre_window, record.outcome.transition_direction, baseline_1431) if baseline_1431 is not None else None
    )
    # Price stays reliable through 15:39 (only volume freezes at 15:15), so
    # the post-window points move uses the FULL post_window, not the
    # volume-reliable-only slice.
    post_points_move = _points_move(post_window, post_direction, record.outcome.close_1459)

    quality_flag = (
        "stuck_candle_run_detected" if (_has_stuck_candles(pre_window) or _has_stuck_candles(post_reliable_window)) else None
    )

    return CasDailyTransition(
        symbol=symbol,
        session_date=session_date,
        close_1431=baseline_1431,
        close_1459=record.outcome.close_1459,
        close_1539=record.outcome.market_close,
        pre_direction=record.outcome.transition_direction,
        post_direction=post_direction,
        conclusion=record.outcome.outcome,
        outcome_magnitude=record.outcome.outcome_magnitude,
        pre_window_volume=pre_vol,
        post_window_pre_auction_volume=post_vol,
        volume_ratio=vol_ratio,
        pre_window_points_move=pre_points_move,
        post_window_points_move=post_points_move,
        pcr_1459=(option_context or {}).get("pcr"),
        institutional_bias_label_1459=(option_context or {}).get("bias_label"),
        institutional_bias_score_1459=(option_context or {}).get("bias_score"),
        expiry_type=expiry_type,
        day_of_week=session_date.weekday(),
        old_methodology_outcome=old_outcome,
        old_methodology_outcome_magnitude=old_outcome_magnitude,
        data_quality_flag=quality_flag,
    )
