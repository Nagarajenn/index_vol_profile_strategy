"""Orchestrates the full research run for one symbol: load all candle
history from the DB, extract one DailyTransitionRecord per trading day,
run the correlation study across all of them, then score every day using
that study. Pure of DB writes -- returns data structures the caller (the
CLI script) persists, so this stays unit-testable without a live database.
"""

from datetime import date

import pandas as pd

from market_transition.expiry_calendar import build_expiry_calendar
from market_transition.feature_extraction import extract_daily_transition_record
from market_transition.models import DailyTransitionRecord, DailyTransitionScore, FactorCorrelationResult
from market_transition.scoring import score_day
from market_transition.statistics import run_correlation_study

REGIME_HISTORY_LOOKBACK_DAYS = 20


def _split_by_session_date(candles: pd.DataFrame) -> dict[date, pd.DataFrame]:
    if candles.empty:
        return {}
    grouped = {}
    for d, group in candles.groupby(candles["timestamp"].dt.date):
        grouped[d] = group.reset_index(drop=True)
    return grouped


def extract_all_records(symbol: str, candles: pd.DataFrame, bin_size: float) -> list[DailyTransitionRecord]:
    """`candles` must be all available 1-min OHLCV history for `symbol`,
    ascending by timestamp (e.g. from db.reader.load_raw_candles)."""
    by_date = _split_by_session_date(candles)
    trading_dates = sorted(by_date)
    if not trading_dates:
        return []

    expiry_cal = build_expiry_calendar(symbol, trading_dates[0], trading_dates[-1])

    records: list[DailyTransitionRecord] = []
    for i, d in enumerate(trading_dates):
        today_candles = by_date[d]
        prior_day_candles = by_date[trading_dates[i - 1]] if i > 0 else None
        window_start = max(0, i - REGIME_HISTORY_LOOKBACK_DAYS)
        historical_by_date = {dd: by_date[dd] for dd in trading_dates[window_start:i]}

        record = extract_daily_transition_record(
            symbol=symbol,
            session_date=d,
            today_candles=today_candles,
            prior_day_candles=prior_day_candles,
            historical_by_date=historical_by_date,
            bin_size=bin_size,
            expiry_type=expiry_cal.get(d),
        )
        if record is not None:
            records.append(record)
    return records


def run_research(symbol: str, candles: pd.DataFrame, bin_size: float) -> tuple[list[DailyTransitionRecord], list[FactorCorrelationResult], list[DailyTransitionScore]]:
    records = extract_all_records(symbol, candles, bin_size)
    if not records:
        return [], [], []

    correlations = run_correlation_study(records)
    scores = [score_day(r, records, correlations) for r in records]
    return records, correlations, scores
