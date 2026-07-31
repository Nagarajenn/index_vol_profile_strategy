"""Extracts one day's pre-3pm features and 3pm-transition outcome from that
day's (and the prior day's) 1-minute candles. Pure function of the candle
DataFrames passed in -- no DB access here, so it's testable with synthetic
candles and reusable from both the research orchestrator script and any
future ad-hoc analysis.

Window definitions (candle `timestamp` = bar-open time, matching the rest
of this codebase's convention):
  - Pre-window: 14:00-14:59 inclusive. "Developing" values (POC, VWAP,
    profile shape, rotation, market regime) are computed on the full
    session-so-far (session open through the given cutoff), consistent
    with how analytics/volume_profile_intelligence.py already defines
    "developing".
  - Transition window: 15:00-15:01 inclusive -- the move this whole engine
    is trying to explain.
  - Post window: everything after 15:01 through the session's last candle.

A day is skipped (returns None) if there's no candle data in the pre,
transition, or post window -- this deliberately excludes days with a
pipeline outage spanning the window (several are on record in
PROJECT_STATUS.md) rather than fabricating a result from partial data.
"""

from datetime import date, time
from typing import Literal

import pandas as pd

from analytics.volume_profile import compute_volume_profile
from analytics.volume_profile_intelligence import classify_profile_shape, compute_initial_balance, compute_rotation_factor
from analytics.vwap import compute_vwap
from market_transition.market_regime import classify_market_regime
from market_transition.models import DailyTransitionRecord, ExpiryType, PreWindowFeatures, TransitionOutcome

PRE_WINDOW_START = time(14, 0)
PRE_WINDOW_MID = time(14, 30)
PRE_WINDOW_END = time(14, 59)
TRANSITION_START = time(15, 0)
TRANSITION_END = time(15, 1)

# Below this fraction of the pre-window close, a move is treated as "flat"
# noise rather than a genuine directional transition/outcome.
FLAT_MOVE_THRESHOLD_PCT = 0.02


def _time_between(candles: pd.DataFrame, start: time, end: time) -> pd.DataFrame:
    t = candles["timestamp"].dt.time
    return candles[(t >= start) & (t <= end)]


def _session_so_far(candles: pd.DataFrame, cutoff_time: time) -> pd.DataFrame:
    return candles[candles["timestamp"].dt.time <= cutoff_time]


def _direction(move: float, reference_price: float) -> Literal["up", "down", "flat"]:
    if reference_price <= 0 or abs(move) / reference_price * 100 < FLAT_MOVE_THRESHOLD_PCT:
        return "flat"
    return "up" if move > 0 else "down"


def _prior_day_close_vs_poc(prior_day_candles: pd.DataFrame, bin_size: float) -> Literal["above", "below", "at"] | None:
    if prior_day_candles.empty:
        return None
    vp = compute_volume_profile(prior_day_candles, bin_size)
    if vp is None:
        return None
    prior_close = prior_day_candles["close"].iloc[-1]
    if abs(prior_close - vp.poc) / vp.poc * 100 < FLAT_MOVE_THRESHOLD_PCT:
        return "at"
    return "above" if prior_close > vp.poc else "below"


def extract_daily_transition_record(
    symbol: str,
    session_date: date,
    today_candles: pd.DataFrame,
    prior_day_candles: pd.DataFrame | None,
    historical_by_date: dict[date, pd.DataFrame],
    bin_size: float,
    expiry_type: ExpiryType | None,
) -> DailyTransitionRecord | None:
    if today_candles.empty:
        return None

    pre_window = _time_between(today_candles, PRE_WINDOW_START, PRE_WINDOW_END)
    transition_window = _time_between(today_candles, TRANSITION_START, TRANSITION_END)
    post_window = today_candles[today_candles["timestamp"].dt.time > TRANSITION_END]

    if pre_window.empty or transition_window.empty or post_window.empty:
        return None

    session_at_1400 = _session_so_far(today_candles, PRE_WINDOW_START)
    session_at_1459 = _session_so_far(today_candles, PRE_WINDOW_END)
    if session_at_1400.empty or session_at_1459.empty:
        return None

    vp_1400 = compute_volume_profile(session_at_1400, bin_size)
    vp_1459 = compute_volume_profile(session_at_1459, bin_size)
    poc_migration = (vp_1459.poc - vp_1400.poc) if (vp_1400 and vp_1459) else None

    vwap_series = compute_vwap(session_at_1459)
    vwap_1459 = float(vwap_series.iloc[-1]) if not vwap_series.empty else None
    close_1459 = float(pre_window["close"].iloc[-1])
    vwap_distance = (close_1459 - vwap_1459) if vwap_1459 is not None else None
    vwap_distance_pct = (vwap_distance / vwap_1459 * 100) if (vwap_distance is not None and vwap_1459) else None

    first_half = pre_window[pre_window["timestamp"].dt.time < PRE_WINDOW_MID]
    second_half = pre_window[pre_window["timestamp"].dt.time >= PRE_WINDOW_MID]
    volume_slope = None
    if not first_half.empty and not second_half.empty:
        first_avg = first_half["volume"].mean()
        second_avg = second_half["volume"].mean()
        if first_avg > 0:
            volume_slope = (second_avg - first_avg) / first_avg

    realized_range = float(pre_window["high"].max() - pre_window["low"].min())

    profile_shape = classify_profile_shape(vp_1459.bins, vp_1459.poc, bin_size) if vp_1459 else None
    rotation = compute_rotation_factor(session_at_1459)
    regime = classify_market_regime(session_at_1459, historical_by_date)

    ib = compute_initial_balance(session_at_1459)
    is_inside_ib = (ib.ib_low <= close_1459 <= ib.ib_high) if ib else None

    prior_shape = None
    prior_close_vs_poc = None
    if prior_day_candles is not None and not prior_day_candles.empty:
        prior_vp = compute_volume_profile(prior_day_candles, bin_size)
        if prior_vp is not None:
            prior_shape = classify_profile_shape(prior_vp.bins, prior_vp.poc, bin_size).shape
        prior_close_vs_poc = _prior_day_close_vs_poc(prior_day_candles, bin_size)

    features = PreWindowFeatures(
        poc_migration_1400_1459=poc_migration,
        vwap_distance_1459=vwap_distance,
        vwap_distance_1459_pct=vwap_distance_pct,
        volume_slope_1400_1459=volume_slope,
        realized_range_1400_1459=realized_range,
        profile_shape_1459=profile_shape.shape if profile_shape else None,
        rotation_label_1459=rotation.label if rotation else None,
        market_regime_1459=regime,
        is_inside_initial_balance_1459=is_inside_ib,
        day_of_week=session_date.weekday(),
        expiry_type=expiry_type,
        prior_day_profile_shape=prior_shape,
        prior_day_close_vs_poc=prior_close_vs_poc,
    )

    close_1501 = float(transition_window["close"].iloc[-1])
    market_close = float(post_window["close"].iloc[-1])
    transition_move = close_1501 - close_1459
    transition_direction = _direction(transition_move, close_1459)
    post_transition_move = market_close - close_1501

    if transition_direction == "flat":
        outcome: Literal["continuation", "reversal", "neutral"] = "neutral"
    else:
        post_direction = _direction(post_transition_move, close_1501)
        if post_direction == "flat":
            outcome = "neutral"
        elif post_direction == transition_direction:
            outcome = "continuation"
        else:
            outcome = "reversal"

    outcome_record = TransitionOutcome(
        close_1459=close_1459,
        close_1501=close_1501,
        market_close=market_close,
        transition_move=transition_move,
        transition_direction=transition_direction,
        post_transition_move=post_transition_move,
        outcome=outcome,
        outcome_magnitude=abs(post_transition_move),
    )

    return DailyTransitionRecord(symbol=symbol, session_date=session_date, features=features, outcome=outcome_record)
