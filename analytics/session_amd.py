"""Session AMD (Accumulation / Manipulation / Distribution) structure --
the ICT-style session model: an early consolidation range (Accumulation),
a stop-hunt/liquidity-sweep move outside that range that fails and
reverses (Manipulation), then the real directional move that follows
(Distribution).

Live-compute-only, pure functions over candle DataFrames -- no DB table,
no pipeline change, mirrors analytics/volume_intelligence/engine.py's and
analytics/volume_profile_intelligence.py's architecture exactly. Reuses
compute_initial_balance() (the accumulation-range mechanism) and
compute_buy_sell_dominance()/attach_buy_sell_columns() (the Chaikin-style
buy/sell proxy already used everywhere in this codebase) unmodified --
the only genuinely new piece here is the manipulation (sweep) detector.

Explicitly a documented, deterministic heuristic synthesis -- not a claim
of matching any single canonical/proprietary ICT definition, same framing
already used for Profile Shape/Opening Type/Volume Character elsewhere in
this codebase. Explicitly NOT wired into the strategy engine
(analytics/confidence_score.py, analytics/trend_classifier.py,
decision/decision_card.py) -- informational only.

Only ONE accumulation-range-anchored-at-session-open AMD cycle is
detected per day (not a rolling/multi-cycle re-anchoring detector) --
matches the classic single-session ICT framing this was scoped to.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Literal

import pandas as pd

from analytics.volume_intelligence.pressure import compute_buy_sell_dominance
from analytics.volume_intelligence.proxy import attach_buy_sell_columns
from analytics.volume_profile_intelligence import InitialBalance, compute_initial_balance

# ICT's opening-range accumulation is tighter than classic Market Profile's
# 60-min Initial Balance (DEFAULT_INITIAL_BALANCE_MINUTES in
# volume_profile_intelligence.py) -- a deliberately separate, documented
# starting default, not silently borrowed from that unrelated concept.
DEFAULT_ACCUMULATION_MINUTES = 30

# Minimum break beyond the range, as a fraction of the range's own width,
# to filter ordinary noise from a genuine test of the level.
SWEEP_MARGIN_PCT = 0.10

# Grace period for price to close back inside the range and count as a
# sweep; beyond this without reversing, it's classified as a genuine
# Breakout instead of a manipulation.
SWEEP_REVERSAL_WINDOW_MINUTES = 15

SweepDirection = Literal["swept_high", "swept_low"]
DistributionDirection = Literal["up", "down"]
DistributionStatus = Literal["Confirmed", "Developing", "Failed"]
CurrentPhase = Literal[
    "Accumulating",
    "Range Established -- Awaiting Move",
    "Testing Range",
    "Distribution",
    "Breakout (not manipulation)",
    "No Clear Setup",
]


@dataclass
class AccumulationRange:
    high: float
    low: float
    range: float
    start_time: datetime
    end_time: datetime
    is_complete: bool  # False while the session hasn't yet reached end_time


@dataclass
class ManipulationSweep:
    direction: SweepDirection
    extreme_price: float
    breakout_time: datetime
    reversal_time: datetime
    candles_to_reverse: int
    expected_distribution_direction: DistributionDirection  # opposite the sweep


@dataclass
class DistributionPhase:
    direction: DistributionDirection
    started_at: datetime
    net_move_points: float
    net_move_pct: float
    dominant_side_confirms: bool | None  # None when there's no dominance reading available yet
    status: DistributionStatus


@dataclass
class SessionAmdPhases:
    symbol: str
    as_of: datetime | None
    accumulation: AccumulationRange | None = None
    sweeps: list[ManipulationSweep] = field(default_factory=list)
    latest_sweep: ManipulationSweep | None = None
    distribution: DistributionPhase | None = None
    current_phase: CurrentPhase = "Accumulating"
    narrative: str = ""


def _find_sweeps(
    today_candles: pd.DataFrame, acc: AccumulationRange, session_start: pd.Timestamp,
) -> tuple[list[ManipulationSweep], bool]:
    """Scans candles strictly after the accumulation window for qualifying
    sweep events. Returns (sweeps, breakout_without_reversal) -- the second
    flag is True when price broke the range and never reversed within the
    grace window (a genuine Breakout, not a manipulation)."""
    after = today_candles[today_candles["timestamp"] > acc.end_time].reset_index(drop=True)
    if after.empty:
        return [], False

    margin = SWEEP_MARGIN_PCT * acc.range if acc.range > 0 else 0.0
    high_trigger = acc.high + margin
    low_trigger = acc.low - margin

    sweeps: list[ManipulationSweep] = []
    breakout_pending = False
    i = 0
    n = len(after)
    while i < n:
        row = after.iloc[i]
        direction: SweepDirection | None = None
        extreme = None
        if row["high"] >= high_trigger:
            direction, extreme = "swept_high", float(row["high"])
        elif row["low"] <= low_trigger:
            direction, extreme = "swept_low", float(row["low"])

        if direction is None:
            i += 1
            continue

        breakout_time = row["timestamp"]
        deadline = breakout_time + timedelta(minutes=SWEEP_REVERSAL_WINDOW_MINUTES)
        window = after[(after["timestamp"] >= breakout_time) & (after["timestamp"] <= deadline)]

        reversed_row = None
        for _, w_row in window.iterrows():
            # A further, more extreme breach (even on the eventual reversal
            # candle itself -- a long-wick spike-and-reverse) still extends
            # the tracked extreme, so it's checked before the inside-range
            # break below, not after.
            if direction == "swept_high" and w_row["high"] > extreme:
                extreme = float(w_row["high"])
            elif direction == "swept_low" and w_row["low"] < extreme:
                extreme = float(w_row["low"])
            if acc.low <= w_row["close"] <= acc.high:
                reversed_row = w_row
                break

        if reversed_row is not None:
            candles_to_reverse = int(window[window["timestamp"] <= reversed_row["timestamp"]].shape[0])
            sweeps.append(
                ManipulationSweep(
                    direction=direction, extreme_price=extreme,
                    breakout_time=breakout_time, reversal_time=reversed_row["timestamp"],
                    candles_to_reverse=candles_to_reverse,
                    expected_distribution_direction="down" if direction == "swept_high" else "up",
                )
            )
            # resume scanning after the reversal candle -- a later, separate
            # test of the range can still register as its own sweep.
            resume_ts = reversed_row["timestamp"]
            i = after[after["timestamp"] > resume_ts].index.min()
            i = int(i) if pd.notna(i) else n
            continue

        # No reversal within the grace window.
        if breakout_time + timedelta(minutes=SWEEP_REVERSAL_WINDOW_MINUTES) <= today_candles["timestamp"].iloc[-1]:
            # The grace window has fully elapsed with no close back inside
            # the range -- a genuine breakout, not a manipulation.
            breakout_pending = True
            break
        # Still inside the grace window as of "now" (live, in-progress) --
        # ambiguous; stop scanning, "Testing Range" is reported by the caller.
        break

    return sweeps, breakout_pending


def _build_distribution(
    sweep: ManipulationSweep, today_candles: pd.DataFrame, enriched: pd.DataFrame,
) -> DistributionPhase:
    since = today_candles[today_candles["timestamp"] >= sweep.reversal_time]
    start_price = float(since["close"].iloc[0]) if not since.empty else sweep.extreme_price
    last_price = float(since["close"].iloc[-1]) if not since.empty else start_price
    net_move = last_price - start_price
    net_move_pct = (net_move / start_price * 100) if start_price else 0.0

    dominant_side_confirms: bool | None = None
    since_enriched = enriched[enriched["timestamp"] >= sweep.reversal_time]
    if not since_enriched.empty:
        dominance = compute_buy_sell_dominance(since_enriched, window_minutes=len(since_enriched))
        if dominance.dominant_side != "balanced":
            expected_side = "buy" if sweep.expected_distribution_direction == "up" else "sell"
            dominant_side_confirms = dominance.dominant_side == expected_side

    # Failed: price has re-crossed back past the sweep's own extreme,
    # invalidating the setup (the "manipulation" turned out to just be
    # noise, or the sweep continued through in its original direction).
    beyond_extreme = (
        (sweep.direction == "swept_high" and last_price >= sweep.extreme_price)
        or (sweep.direction == "swept_low" and last_price <= sweep.extreme_price)
    )
    if beyond_extreme:
        status: DistributionStatus = "Failed"
    elif (sweep.expected_distribution_direction == "up" and net_move > 0) or (
        sweep.expected_distribution_direction == "down" and net_move < 0
    ):
        status = "Confirmed"
    else:
        status = "Developing"

    return DistributionPhase(
        direction=sweep.expected_distribution_direction, started_at=sweep.reversal_time,
        net_move_points=net_move, net_move_pct=net_move_pct,
        dominant_side_confirms=dominant_side_confirms, status=status,
    )


def _narrative(result: SessionAmdPhases) -> str:
    acc = result.accumulation
    if acc is None:
        return "Not enough data yet to establish today's accumulation range."
    if result.current_phase == "Accumulating":
        return f"Still building the accumulation range ({acc.low:.0f}-{acc.high:.0f} so far)."
    if result.current_phase == "Range Established -- Awaiting Move":
        return f"Accumulation range {acc.low:.0f}-{acc.high:.0f} established -- no test of either side yet."
    if result.current_phase == "Testing Range":
        return f"Price is testing beyond the {acc.low:.0f}-{acc.high:.0f} accumulation range -- not yet confirmed as a sweep or a breakout."
    if result.current_phase == "Breakout (not manipulation)":
        return f"Range {acc.low:.0f}-{acc.high:.0f} broke without reversing back inside -- a genuine breakout, not a liquidity sweep."
    if result.current_phase == "No Clear Setup":
        return f"Multiple conflicting tests of the {acc.low:.0f}-{acc.high:.0f} range today -- no clean single AMD read."
    if result.current_phase == "Distribution" and result.latest_sweep and result.distribution:
        s, d = result.latest_sweep, result.distribution
        side = "below" if s.direction == "swept_low" else "above"
        confirm = ""
        if d.dominant_side_confirms is True:
            confirm = ", buy/sell dominance confirms"
        elif d.dominant_side_confirms is False:
            confirm = ", dominance hasn't confirmed yet"
        return (
            f"Accumulation range {acc.low:.0f}-{acc.high:.0f} was swept {side} at {s.breakout_time:%H:%M}, "
            f"reversed by {s.reversal_time:%H:%M} -- Distribution {d.direction.capitalize()} {d.status.lower()} "
            f"({d.net_move_points:+.0f} pts so far{confirm})."
        )
    return "No clear AMD setup today."


def compute_session_amd_phases(
    symbol: str, today_candles: pd.DataFrame, accumulation_minutes: int = DEFAULT_ACCUMULATION_MINUTES,
) -> SessionAmdPhases:
    """`today_candles` is today's session-so-far 1-min OHLCV, ascending by
    time. Recomputed fresh on every call -- no caching, no incremental
    state, matches this codebase's established stateless philosophy."""
    if today_candles.empty:
        return SessionAmdPhases(symbol=symbol, as_of=None, narrative="No candles yet today.")

    as_of = today_candles["timestamp"].iloc[-1].to_pydatetime()
    session_start = today_candles["timestamp"].iloc[0]

    ib = compute_initial_balance(today_candles, ib_minutes=accumulation_minutes)
    if ib is None:
        return SessionAmdPhases(symbol=symbol, as_of=as_of, narrative="Not enough data yet to establish today's accumulation range.")

    acc = AccumulationRange(
        high=ib.ib_high, low=ib.ib_low, range=ib.ib_range,
        start_time=session_start.to_pydatetime(), end_time=ib.end_time.to_pydatetime(),
        is_complete=ib.is_complete,
    )

    if not acc.is_complete:
        result = SessionAmdPhases(symbol=symbol, as_of=as_of, accumulation=acc, current_phase="Accumulating")
        result.narrative = _narrative(result)
        return result

    sweeps, breakout_pending = _find_sweeps(today_candles, acc, session_start)

    if len(sweeps) > 1:
        current_phase: CurrentPhase = "No Clear Setup"
    elif len(sweeps) == 1:
        current_phase = "Distribution"
    elif breakout_pending:
        current_phase = "Breakout (not manipulation)"
    else:
        after = today_candles[today_candles["timestamp"] > acc.end_time]
        margin = SWEEP_MARGIN_PCT * acc.range if acc.range > 0 else 0.0
        being_tested = not after.empty and (
            (after["high"].max() >= acc.high + margin) or (after["low"].min() <= acc.low - margin)
        )
        current_phase = "Testing Range" if being_tested else "Range Established -- Awaiting Move"

    latest_sweep = sweeps[-1] if sweeps else None
    distribution = None
    if latest_sweep is not None and current_phase == "Distribution":
        enriched = attach_buy_sell_columns(today_candles)
        distribution = _build_distribution(latest_sweep, today_candles, enriched)

    result = SessionAmdPhases(
        symbol=symbol, as_of=as_of, accumulation=acc, sweeps=sweeps, latest_sweep=latest_sweep,
        distribution=distribution, current_phase=current_phase,
    )
    result.narrative = _narrative(result)
    return result
