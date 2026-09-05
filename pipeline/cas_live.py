"""Phase 7D: live wiring for today's dual-resolution pre/post-3pm detail.

Makes cas_pretransition_windows/cas_post_transition_minutes/
cas_transition_forecasts populate for TODAY, live, as the session actually
happens -- Phase 7B only ever computed these for already-closed historical
days via scripts/run_cas_windowed_analysis.py.

Zero new Dhan API calls: pipeline/run_snapshot.py's live-mode path already
persists that minute's candles (raw_candles) and option chain
(option_chain_raw/summary) to Postgres every tick. This module reads those
back from the DB -- cheap local reads, not new external fetches.

Recompute-per-call, not incremental: build_pre_transition_windows/
build_post_transition_minutes already handle partial/in-progress data
gracefully (see market_transition/cas_windows.py's tests) -- calling them
fresh every tick with "today's candles so far" naturally produces a
developing view (a window/minute fills in as more candles arrive) and the
idempotent upserts make re-writing the same row every tick correct by
construction. This mirrors this package's established stateless,
recompute-per-call philosophy (live_advisor.py, generate_checkpoint_times-
based backfill) rather than inventing incremental/delta logic.

Gated to only the ~61 minutes/day (14:30-15:31) where there's anything to
compute -- a true no-op the rest of the session. The window extends 16
minutes past the old 15:15 cutoff purely to catch the single 15:30
closing-print checkpoint (market_transition.cas_windows.
CLOSING_SNAPSHOT_TIME) once that candle lands -- ticks in between just
redundantly (but harmlessly) re-write the same 16 native minutes, same
idempotent-recompute-per-call philosophy as the rest of this window.
"""

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, time

import pandas as pd

from analytics.breakout_boxes import compute_atr
from config.instruments import INSTRUMENTS
from config.settings import IST
from db import reader as db_reader
from db import writer as db_writer
from market_transition.cas_forecast import FORECAST_CHECKPOINTS, build_transition_forecast
from market_transition.cas_transition import CAS_EFFECTIVE_DATE, extract_cas_transition_record
from market_transition.cas_windows import PRE_WINDOW_BOUNDARIES, PreTransitionWindow, build_post_transition_minutes, build_pre_transition_windows
from market_transition.expiry_calendar import classify_expiry_day
from market_transition.research import extract_all_records
from market_transition.statistics import run_correlation_study
from option_chain.snapshot_features import classify_option_positioning, compute_snapshot_features

logger = logging.getLogger(__name__)

CAS_LIVE_START = time(14, 30)
CAS_LIVE_END = time(15, 31)  # a minute past CLOSING_SNAPSHOT_TIME (15:30), so a tick exactly at 15:30 still runs
CAS_HISTORY_LIMIT = 10_000
HISTORICAL_LOOKBACK_DAYS = 20


def _split_by_date(candles):
    if candles.empty:
        return {}
    return {d: g.reset_index(drop=True) for d, g in candles.groupby(candles["timestamp"].dt.date)}


def compute_and_persist_windowed_day(
    symbol: str,
    session_date: date,
    day_candles,
    historical_by_date: dict,
    option_lookup_fn,
    events: list,
    bin_size: float,
    expiry_type,
    prior_day_candles,
    old_records: list,
    cas_history: list,
    correlations: list,
) -> tuple[int, int, int]:
    """One day's worth of compute + persist for all three Phase 7B tables --
    shared by the batch orchestrator (scripts/run_cas_windowed_analysis.py)
    and the live hook below, so the "build 6 windows / build N minutes /
    build 7 forecasts, then write each" glue logic exists in exactly one
    place."""
    n_windows = n_minutes = n_forecasts = 0

    pre_windows = build_pre_transition_windows(day_candles, historical_by_date, option_lookup_fn, events, bin_size, session_date)
    for w in pre_windows:
        db_writer.insert_cas_pretransition_window(symbol, session_date, w)
        n_windows += 1

    post_minutes = build_post_transition_minutes(
        day_candles, historical_by_date, option_lookup_fn, pre_windows[-1] if pre_windows else None, bin_size, session_date
    )
    for m in post_minutes:
        db_writer.insert_cas_post_transition_minute(symbol, session_date, m)
        n_minutes += 1

    atr_14 = compute_prior_day_atr_14(historical_by_date)

    for checkpoint in FORECAST_CHECKPOINTS:
        # Leakage-safe pairing: only the pre-window whose own end time is
        # <= this checkpoint may be used (e.g. the 14:59 checkpoint gets
        # the 14:55-14:59 window, but the 14:30 checkpoint gets none yet --
        # passing the FINAL window to every checkpoint would leak later
        # windows' information into earlier forecasts).
        matching_window = _pre_window_for_checkpoint(pre_windows, checkpoint)
        option_bias = _option_bias_at(symbol, session_date, checkpoint)

        forecast = build_transition_forecast(
            checkpoint, symbol, session_date, day_candles, prior_day_candles, historical_by_date,
            old_records, cas_history, correlations, bin_size, expiry_type,
            pre_window=matching_window, option_bias=option_bias, atr_14=atr_14,
        )
        if forecast:
            db_writer.insert_cas_transition_forecast(symbol, session_date, forecast)
            n_forecasts += 1

    return n_windows, n_minutes, n_forecasts


def _pre_window_for_checkpoint(pre_windows: list[PreTransitionWindow], checkpoint: time) -> PreTransitionWindow | None:
    """The latest pre-transition window whose own end time is <= `checkpoint`
    -- None for the 14:30 checkpoint itself, since no 5-min window has
    closed yet at that instant."""
    match = None
    for w, (_, w_end) in zip(pre_windows, PRE_WINDOW_BOUNDARIES):
        if w_end <= checkpoint:
            match = w
        else:
            break
    return match


def _option_bias_at(symbol: str, session_date: date, checkpoint: time) -> str | None:
    """Fresh option-chain classification at/before `checkpoint` -- a
    separate ad-hoc read, not tied to Phase 9A's 8 fixed daily checkpoints
    (14:59 specifically isn't one of them)."""
    row = db_reader.get_option_chain_raw_near(symbol, session_date, at_or_before=checkpoint.strftime("%H:%M:%S"))
    if row is None:
        return None
    features = compute_snapshot_features(row["raw_payload"])
    return classify_option_positioning(features) if features else None


def compute_prior_day_atr_14(historical_by_date: dict) -> float | None:
    """Daily-bar ATR(14) as of the most recent day in `historical_by_date`
    (all strictly-past days) -- the same "prior day's own ATR, never
    today's" discipline Phase 7A's magnitude-tier classification already
    uses, just recomputed here since the raw atr_14 value itself isn't
    persisted anywhere retrievable at this granularity."""
    if not historical_by_date:
        return None
    daily_rows = []
    for d, df in sorted(historical_by_date.items()):
        if df.empty:
            continue
        daily_rows.append({"date": d, "high": df["high"].max(), "low": df["low"].min(), "close": df["close"].iloc[-1]})
    if len(daily_rows) < 2:
        return None
    daily_df = pd.DataFrame(daily_rows)
    atr_series = compute_atr(daily_df)
    value = atr_series.iloc[-1]
    return float(value) if pd.notna(value) else None


@dataclass
class _LiveCasContext:
    """Cached once per (symbol, trading day) -- old_records/correlations/
    cas_history/historical_by_date are stable across a single session and
    expensive to recompute (a correlation study over ~4 months of history);
    recomputing them on every one of the ~45 live ticks in the window would
    be wasteful. No explicit invalidation needed since live_loop is itself
    a fresh process each trading morning."""

    session_date: date
    bin_size: float
    expiry_type: object
    historical_by_date: dict
    prior_day_candles: object
    old_records: list
    cas_history: list
    correlations: list
    events: list
    written_forecast_checkpoints: set = field(default_factory=set)


_contexts: dict[str, _LiveCasContext] = {}


def _build_context(symbol: str, session_date: date) -> _LiveCasContext:
    bin_size = INSTRUMENTS[symbol]["volume_profile_bin_size"]
    candles = db_reader.load_raw_candles(symbol)
    by_date = _split_by_date(candles)

    prior_dates = sorted(d for d in by_date if d < session_date)
    prior_day_candles = by_date[prior_dates[-1]] if prior_dates else None
    window_start = max(0, len(prior_dates) - HISTORICAL_LOOKBACK_DAYS)
    historical_by_date = {d: by_date[d] for d in prior_dates[window_start:]}

    old_records = extract_all_records(symbol, candles, bin_size, extract_fn=extract_cas_transition_record)
    old_records = [r for r in old_records if r.session_date != session_date]  # today can't have a record of itself yet
    correlations = run_correlation_study(old_records)
    cas_history = db_reader.load_cas_daily_transitions(symbol, limit=CAS_HISTORY_LIMIT)

    events = db_reader.list_classified_events_between(
        datetime.combine(session_date, datetime.min.time(), tzinfo=IST) - timedelta(hours=1),
        datetime.combine(session_date, datetime.min.time(), tzinfo=IST) + timedelta(hours=16),
    )

    # today's own CAS record doesn't exist yet (extract_cas_transition_record
    # needs a completed post-window) -- ask the expiry calendar directly
    # rather than the batch script's "borrow it from today's own old record"
    # shortcut, which only works for already-closed days.
    expiry_type = classify_expiry_day(symbol, session_date)

    return _LiveCasContext(
        session_date=session_date, bin_size=bin_size, expiry_type=expiry_type,
        historical_by_date=historical_by_date, prior_day_candles=prior_day_candles,
        old_records=old_records, cas_history=cas_history, correlations=correlations, events=events,
    )


def _get_context(symbol: str, session_date: date) -> _LiveCasContext:
    ctx = _contexts.get(symbol)
    if ctx is None or ctx.session_date != session_date:
        ctx = _build_context(symbol, session_date)
        _contexts[symbol] = ctx
    return ctx


def maybe_update(symbol: str, now: datetime) -> None:
    """Called once per live tick from pipeline/live_loop.py, right after
    run_snapshot -- a true no-op outside [14:30, 15:31]."""
    now_time = now.time()
    if not (CAS_LIVE_START <= now_time <= CAS_LIVE_END):
        return

    session_date = now.date()
    ctx = _get_context(symbol, session_date)

    today_candles = db_reader.load_raw_candles(symbol, start_date=session_date, end_date=session_date)
    if today_candles.empty:
        return

    def option_lookup(at_time, _symbol=symbol, _session_date=session_date):
        return db_reader.get_option_summary_near(_symbol, _session_date, at_or_before=at_time.strftime("%H:%M:%S"))

    # Computed unconditionally (cheap, same recompute-per-call philosophy
    # as everywhere else) so the forecast loop below always has the day's
    # pre-transition windows available for its leakage-safe pre_window
    # pairing, even on a tick after 14:59 (e.g. a late-starting process
    # catching up on earlier checkpoints all at once).
    windows = build_pre_transition_windows(today_candles, ctx.historical_by_date, option_lookup, ctx.events, ctx.bin_size, session_date)

    n_windows = n_minutes = 0
    if now_time <= time(14, 59):
        for w in windows:
            db_writer.insert_cas_pretransition_window(symbol, session_date, w)
            n_windows += 1

    if now_time >= time(15, 0):
        # The last pre-transition window (14:55-14:59), needed to seed the
        # first post-transition minute's price_change baseline -- re-fetch
        # rather than recompute, since it was already written above earlier
        # today.
        pre_windows_rows = db_reader.load_final_pretransition_windows(symbol)
        prior_window = None
        raw_row = pre_windows_rows.get(session_date)
        if raw_row is not None:
            prior_window = PreTransitionWindow(**raw_row)

        minutes = build_post_transition_minutes(today_candles, ctx.historical_by_date, option_lookup, prior_window, ctx.bin_size, session_date)
        for m in minutes:
            db_writer.insert_cas_post_transition_minute(symbol, session_date, m)
            n_minutes += 1

    atr_14 = compute_prior_day_atr_14(ctx.historical_by_date)

    n_forecasts = 0
    for checkpoint in FORECAST_CHECKPOINTS:
        if checkpoint <= now_time and checkpoint not in ctx.written_forecast_checkpoints:
            matching_window = _pre_window_for_checkpoint(windows, checkpoint)
            option_bias = _option_bias_at(symbol, session_date, checkpoint)
            forecast = build_transition_forecast(
                checkpoint, symbol, session_date, today_candles, ctx.prior_day_candles, ctx.historical_by_date,
                ctx.old_records, ctx.cas_history, ctx.correlations, ctx.bin_size, ctx.expiry_type,
                pre_window=matching_window, option_bias=option_bias, atr_14=atr_14,
            )
            if forecast:
                db_writer.insert_cas_transition_forecast(symbol, session_date, forecast)
                ctx.written_forecast_checkpoints.add(checkpoint)
                n_forecasts += 1

    if n_windows or n_minutes or n_forecasts:
        logger.info("%s CAS-live update at %s: %d windows, %d minutes, %d forecasts", symbol, now_time, n_windows, n_minutes, n_forecasts)
