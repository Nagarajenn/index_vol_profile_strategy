from datetime import date, datetime

import pandas as pd

from db.connection import fetch_all, fetch_one


def get_last_candle_timestamp(symbol: str) -> datetime | None:
    row = fetch_one("SELECT max(timestamp) FROM raw_candles WHERE symbol = %s", (symbol,))
    return row[0] if row and row[0] is not None else None


_CANDLE_COLUMNS = ["timestamp", "open", "high", "low", "close", "volume"]


def load_raw_candles(symbol: str, start_date: date | None = None, end_date: date | None = None) -> pd.DataFrame:
    """1-minute OHLCV candles for `symbol`, ascending by timestamp -- used by
    market_transition/ (feature extraction over multi-day history) rather
    than the levels_snapshots checkpoint cadence, since that module needs
    full session data at arbitrary intraday cutoffs, not 5-min checkpoints.
    """
    conditions = ["symbol = %s"]
    params: list = [symbol]
    if start_date:
        conditions.append("timestamp::date >= %s")
        params.append(start_date)
    if end_date:
        conditions.append("timestamp::date <= %s")
        params.append(end_date)

    sql = f"SELECT {', '.join(_CANDLE_COLUMNS)} FROM raw_candles WHERE {' AND '.join(conditions)} ORDER BY timestamp"
    rows = fetch_all(sql, params)
    return pd.DataFrame(rows, columns=_CANDLE_COLUMNS)


def get_last_chart_row(symbol: str, mode: str, session_date: date) -> dict | None:
    """Most recent row for `symbol`/`mode` on `session_date` that actually
    has a chart -- the baseline should_render_chart() compares against.
    Must be scoped to session_date: without it, the first live tick of a
    new session would compare against yesterday's stale chart row.
    """
    row = fetch_one(
        """
        SELECT as_of, trend_label, today_poc
        FROM levels_snapshots
        WHERE symbol = %s AND mode = %s AND chart_path IS NOT NULL AND as_of::date = %s
        ORDER BY as_of DESC LIMIT 1
        """,
        (symbol, mode, session_date),
    )
    if row is None:
        return None
    return {"as_of": row[0], "trend_label": row[1], "today_poc": row[2]}


def has_classified_event(news_item_id: int) -> bool:
    row = fetch_one("SELECT 1 FROM classified_events WHERE news_item_id = %s", (news_item_id,))
    return row is not None


def list_classified_events_between(start: datetime, end: datetime, relevant_only: bool = True) -> list[dict]:
    """Classified events with classified_at in [start, end] -- gated on
    classified_at, never published_at (a news item can publish well before
    it's actually classified; joining on classified_at is what keeps a
    point-in-time read honest about what was actually known by that time).
    Used by market_transition/cas_windows.py to build a per-checkpoint
    trailing news-risk reading without re-querying per checkpoint -- callers
    fetch once for the whole day and filter in memory."""
    condition = "WHERE ce.is_relevant = true AND " if relevant_only else "WHERE "
    rows = fetch_all(
        f"""
        SELECT ce.severity, ce.risk_level, ce.sentiment, ce.classified_at
        FROM classified_events ce
        {condition} ce.classified_at BETWEEN %s AND %s
        ORDER BY ce.classified_at
        """,
        (start, end),
    )
    return [{"severity": r[0], "risk_level": r[1], "sentiment": r[2], "classified_at": r[3]} for r in rows]


def list_recent_classified_events(limit: int = 20, relevant_only: bool = True) -> list[dict]:
    condition = "WHERE ce.is_relevant = true" if relevant_only else ""
    rows = fetch_all(
        f"""
        SELECT
            n.source, n.title, n.link, n.published_at,
            ce.is_relevant, ce.category, ce.severity, ce.confidence, ce.sentiment,
            ce.expected_duration, ce.volatility_impact, ce.reversal_probability,
            ce.affected_sectors, ce.affected_indices,
            ce.expected_direction_nifty, ce.expected_direction_sensex, ce.expected_direction_banknifty,
            ce.recommended_action, ce.risk_level, ce.rationale, ce.classified_at
        FROM classified_events ce
        JOIN news_items n ON n.id = ce.news_item_id
        {condition}
        ORDER BY ce.classified_at DESC
        LIMIT %s
        """,
        (limit,),
    )
    columns = [
        "source", "title", "link", "published_at",
        "is_relevant", "category", "severity", "confidence", "sentiment",
        "expected_duration", "volatility_impact", "reversal_probability",
        "affected_sectors", "affected_indices",
        "expected_direction_nifty", "expected_direction_sensex", "expected_direction_banknifty",
        "recommended_action", "risk_level", "rationale", "classified_at",
    ]
    return [dict(zip(columns, row)) for row in rows]


def list_product_requirements(limit: int = 50) -> list[dict]:
    rows = fetch_all(
        """
        SELECT id, title, submitted_at, requirement_text, status, notes, updated_at
        FROM product_requirements
        ORDER BY submitted_at DESC
        LIMIT %s
        """,
        (limit,),
    )
    columns = ["id", "title", "submitted_at", "requirement_text", "status", "notes", "updated_at"]
    return [dict(zip(columns, row)) for row in rows]


_BACKTEST_COLUMNS = [
    "symbol", "as_of", "mode", "close", "trend_label", "trend_score", "confidence_score",
    "confidence_partial_data", "today_poc", "vwap_now", "support_low", "support_high",
    "resistance_low", "resistance_high", "institutional_bias_data",
    "sub_score_trend_alignment", "sub_score_vwap_position", "sub_score_structure_hh_hl",
    "sub_score_trendline_confluence", "sub_score_sr_proximity", "sub_score_breakout_confirmation",
    "sub_score_institutional_bias", "chart_path",
]


def load_levels_for_backtest(symbol: str, start_date: date | None = None, end_date: date | None = None) -> pd.DataFrame:
    """Replaces the old JSON-folder walk in backtest/load_snapshots.py with
    a query. Reconstructs a `confidence_sub_scores` dict column (dropping
    NaN keys) so it's a drop-in for backtest/tune_weights.py, which expects
    one dict of sub-scores per row.
    """
    conditions = ["symbol = %s"]
    params: list = [symbol]
    if start_date:
        conditions.append("as_of::date >= %s")
        params.append(start_date)
    if end_date:
        conditions.append("as_of::date <= %s")
        params.append(end_date)

    sql = f"SELECT {', '.join(_BACKTEST_COLUMNS)} FROM levels_snapshots WHERE {' AND '.join(conditions)} ORDER BY as_of"
    rows = fetch_all(sql, params)
    df = pd.DataFrame(rows, columns=_BACKTEST_COLUMNS)
    if df.empty:
        return df

    sub_cols = [c for c in _BACKTEST_COLUMNS if c.startswith("sub_score_")]
    df["confidence_sub_scores"] = df[sub_cols].apply(
        lambda r: {c.replace("sub_score_", ""): v for c, v in r.items() if pd.notna(v)}, axis=1
    )
    df = df.drop(columns=sub_cols)
    return df


def get_option_summary_near(symbol: str, session_date: date, at_or_before: str = "14:59:00") -> dict | None:
    """Latest option_chain_summary snapshot for `symbol` on `session_date`
    at/before `at_or_before` -- used by scripts/run_cas_intelligence.py to
    build the ~14:59 option-chain context (PCR, institutional bias) for
    each day's CAS Intelligence row."""
    row = fetch_one(
        """
        SELECT fetched_at, spot, atm_strike, pcr, call_oi_change_near_atm, put_oi_change_near_atm,
               total_call_oi, total_put_oi, atm_iv_call, atm_iv_put, max_call_oi_strike, max_put_oi_strike
        FROM option_chain_summary
        WHERE symbol = %s AND fetched_at::date = %s AND fetched_at::time <= %s
        ORDER BY fetched_at DESC LIMIT 1
        """,
        (symbol, session_date, at_or_before),
    )
    if row is None:
        return None
    columns = [
        "fetched_at", "spot", "atm_strike", "pcr", "call_oi_change_near_atm", "put_oi_change_near_atm",
        "total_call_oi", "total_put_oi", "atm_iv_call", "atm_iv_put", "max_call_oi_strike", "max_put_oi_strike",
    ]
    return dict(zip(columns, row))


def get_option_chain_raw_near(symbol: str, session_date: date, at_or_before: str = "15:30:00") -> dict | None:
    """Latest option_chain_raw row (the FULL per-strike payload -- LTP,
    volume, OI, IV, bid/ask, greeks -- not just the narrower
    option_chain_summary fields) for `symbol` on `session_date` at/before
    `at_or_before`. Used by scripts/run_option_snapshot_features.py to
    derive the 8 fixed daily option-chain checkpoints (Phase 9A) from data
    already captured by the live loop -- no new Dhan API calls."""
    row = fetch_one(
        """
        SELECT fetched_at, expiry, spot, raw_payload
        FROM option_chain_raw
        WHERE symbol = %s AND fetched_at::date = %s AND fetched_at::time <= %s
        ORDER BY fetched_at DESC LIMIT 1
        """,
        (symbol, session_date, at_or_before),
    )
    if row is None:
        return None
    columns = ["fetched_at", "expiry", "spot", "raw_payload"]
    return dict(zip(columns, row))


def list_option_chain_raw_dates(symbol: str) -> list[date]:
    """Every distinct session_date `symbol` has at least one option_chain_raw
    row for, ascending. Drives scripts/run_option_snapshot_features.py's
    day loop directly off what was actually captured, rather than a static
    trading-calendar guess -- a day with a genuine capture gap is simply
    absent here, not silently backfilled from a holiday-calendar rule."""
    rows = fetch_all(
        "SELECT DISTINCT fetched_at::date FROM option_chain_raw WHERE symbol = %s ORDER BY 1",
        (symbol,),
    )
    return [r[0] for r in rows]


_CAS_DAILY_COLUMNS = [
    "symbol", "session_date", "close_1431", "close_1459", "close_1539",
    "pre_direction", "post_direction", "conclusion", "outcome_magnitude",
    "pre_window_volume", "post_window_pre_auction_volume", "volume_ratio",
    "pre_window_points_move", "post_window_points_move",
    "pcr_1459", "institutional_bias_label_1459", "institutional_bias_score_1459",
    "expiry_type", "day_of_week", "old_methodology_outcome", "old_methodology_outcome_magnitude",
    "data_quality_flag",
    # Phase 7A additions -- transition_type/magnitude_* (see
    # market_transition/cas_transition.py::classify_transition_type/
    # classify_transition_magnitude). `conclusion` above is untouched.
    "transition_type", "magnitude_pct_return", "magnitude_atr_normalized", "magnitude_tier",
    "computed_at",
]


def load_cas_daily_transitions(symbol: str, limit: int = 60) -> list[dict]:
    """Most recent `limit` CAS Intelligence rows for `symbol`, ascending by
    session_date (chronological, matching how a comparison table reads)."""
    rows = fetch_all(
        f"""
        SELECT {', '.join(_CAS_DAILY_COLUMNS)} FROM mti_cas_daily_transitions
        WHERE symbol = %s ORDER BY session_date DESC LIMIT %s
        """,
        (symbol, limit),
    )
    rows = list(reversed(rows))
    return [dict(zip(_CAS_DAILY_COLUMNS, r)) for r in rows]


# Column order matches market_transition.cas_windows.PreTransitionWindow's
# dataclass fields exactly (minus session_date/symbol, which key the
# lookup) -- lets callers do PreTransitionWindow(**row) directly.
_PRETRANSITION_WINDOW_COLUMNS = [
    "window_index", "window_label", "open", "close", "high", "low", "net_point_change", "pct_change",
    "volume", "rvol_pct", "volume_acceleration_ratio", "buy_volume_estimate", "sell_volume_estimate",
    "dominance_ratio", "dominant_side", "vwap_at_window_end", "price_distance_from_vwap",
    "price_distance_from_vwap_pct", "vwap_slope", "poc_at_window_end", "poc_change_during_window", "poc_slope",
    "vah", "val", "pcr", "pcr_change", "call_oi_change", "put_oi_change", "iv_change", "option_pressure_score",
    "market_regime", "institutional_bias_label", "institutional_bias_score", "news_risk_score", "data_quality_flag",
]


def load_final_pretransition_windows(symbol: str) -> dict[date, dict]:
    """All window_index=6 (14:55-14:59, the final pre-3pm state) rows for
    `symbol`, keyed by session_date -- used by market_transition/
    cas_cohorts.py's per-cohort pre-3pm feature comparison. Empty dict for
    a day that hasn't had scripts/run_cas_windowed_analysis.py run yet."""
    rows = fetch_all(
        f"""
        SELECT session_date, {", ".join(_PRETRANSITION_WINDOW_COLUMNS)}
        FROM cas_pretransition_windows WHERE symbol = %s AND window_index = 6
        """,
        (symbol,),
    )
    return {r[0]: dict(zip(_PRETRANSITION_WINDOW_COLUMNS, r[1:])) for r in rows}
