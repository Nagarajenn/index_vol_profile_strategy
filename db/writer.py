import json
from dataclasses import asdict
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd
from psycopg.types.json import Jsonb

from analytics.levels import LevelsResult
from db import reader
from db.connection import execute, executemany, fetch_one
from option_chain.summary import OptionChainSummary

RAW_CANDLE_OVERLAP_MINUTES = 5  # re-upsert a small trailing window in case Dhan revises the still-forming last bar


def _json_default(obj):
    if isinstance(obj, pd.Timestamp):
        return obj.isoformat()
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


def _jsonb(obj) -> Jsonb:
    return Jsonb(obj, dumps=lambda o: json.dumps(o, default=_json_default))


def insert_raw_candles(df: pd.DataFrame, symbol: str) -> int:
    """Upserts only rows newer than what's already stored (minus a small
    overlap buffer) -- a live poll re-fetches ~8 days of lookback context
    every call, but almost none of it is new.
    """
    if df.empty:
        return 0

    last_ts = reader.get_last_candle_timestamp(symbol)
    if last_ts is not None:
        cutoff = last_ts - timedelta(minutes=RAW_CANDLE_OVERLAP_MINUTES)
        df = df[df["timestamp"] > cutoff]
    if df.empty:
        return 0

    sql = """
        INSERT INTO raw_candles (symbol, timestamp, open, high, low, close, volume, open_interest)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (symbol, timestamp) DO UPDATE SET
            open = EXCLUDED.open, high = EXCLUDED.high, low = EXCLUDED.low,
            close = EXCLUDED.close, volume = EXCLUDED.volume, open_interest = EXCLUDED.open_interest
        WHERE raw_candles.close IS DISTINCT FROM EXCLUDED.close
           OR raw_candles.volume IS DISTINCT FROM EXCLUDED.volume
    """
    rows = [
        (
            symbol,
            row.timestamp.to_pydatetime(),
            row.open, row.high, row.low, row.close, row.volume,
            getattr(row, "open_interest", None),
        )
        for row in df.itertuples(index=False)
    ]
    executemany(sql, rows)
    return len(rows)


def insert_daily_candles(df: pd.DataFrame, symbol: str) -> int:
    if df.empty:
        return 0
    sql = """
        INSERT INTO raw_daily_candles (symbol, date, open, high, low, close, volume)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (symbol, date) DO UPDATE SET
            open = EXCLUDED.open, high = EXCLUDED.high, low = EXCLUDED.low,
            close = EXCLUDED.close, volume = EXCLUDED.volume
    """
    rows = [
        (symbol, row.timestamp.date(), row.open, row.high, row.low, row.close, row.volume)
        for row in df.itertuples(index=False)
    ]
    executemany(sql, rows)
    return len(rows)


def insert_option_chain(
    symbol: str,
    expiry: str,
    fetched_at: datetime,
    spot: float,
    raw_payload: dict,
    summary: OptionChainSummary | None,
) -> None:
    expiry_date = date.fromisoformat(expiry)
    execute(
        """
        INSERT INTO option_chain_raw (symbol, expiry, fetched_at, spot, raw_payload)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (symbol, expiry, fetched_at) DO NOTHING
        """,
        (symbol, expiry_date, fetched_at, spot, _jsonb(raw_payload)),
    )
    if summary is not None:
        execute(
            """
            INSERT INTO option_chain_summary (
                symbol, expiry, fetched_at, spot, atm_strike, pcr,
                call_oi_change_near_atm, put_oi_change_near_atm,
                total_call_oi, total_put_oi, atm_iv_call, atm_iv_put,
                max_call_oi_strike, max_put_oi_strike
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (symbol, expiry, fetched_at) DO NOTHING
            """,
            (
                symbol, expiry_date, fetched_at, spot, summary.atm_strike, summary.pcr,
                summary.call_oi_change_near_atm, summary.put_oi_change_near_atm,
                summary.total_call_oi, summary.total_put_oi, summary.atm_iv_call, summary.atm_iv_put,
                summary.max_call_oi_strike, summary.max_put_oi_strike,
            ),
        )


_LEVELS_COLUMNS = [
    "symbol", "as_of", "mode", "close", "vwap_now",
    "today_poc", "today_vah", "today_val", "today_total_volume",
    "yesterday_poc", "yesterday_vah", "yesterday_val",
    "support_low", "support_high", "resistance_low", "resistance_high",
    "trend_label", "trend_score",
    "institutional_bias_label", "institutional_bias_score", "institutional_bias_data",
    "confidence_score",
    "sub_score_trend_alignment", "sub_score_vwap_position", "sub_score_structure_hh_hl",
    "sub_score_trendline_confluence", "sub_score_sr_proximity", "sub_score_breakout_confirmation",
    "sub_score_institutional_bias",
    "confidence_weights_used", "confidence_partial_data",
    "action_text",
    "today_vp_bins", "swings", "trendlines", "breakout_boxes",
]


def insert_levels_snapshot(levels: LevelsResult, card: dict, mode: str) -> None:
    """Upserts every levels_snapshots column EXCEPT chart_path/chart_triggered_by.
    Charts are now event-driven (rare), so a full-column upsert would
    silently null out a previously-recorded chart_path on the next recompute
    of the same as_of -- use record_chart() for that instead.
    """
    sub = (levels.confidence.sub_scores if levels.confidence else {}) or {}

    values = {
        "symbol": levels.symbol,
        "as_of": levels.as_of,
        "mode": mode,
        "close": levels.close,
        "vwap_now": levels.vwap_now,
        "today_poc": levels.today_vp.poc if levels.today_vp else None,
        "today_vah": levels.today_vp.vah if levels.today_vp else None,
        "today_val": levels.today_vp.val if levels.today_vp else None,
        "today_total_volume": levels.today_vp.total_volume if levels.today_vp else None,
        "yesterday_poc": levels.yesterday_vp.poc if levels.yesterday_vp else None,
        "yesterday_vah": levels.yesterday_vp.vah if levels.yesterday_vp else None,
        "yesterday_val": levels.yesterday_vp.val if levels.yesterday_vp else None,
        "support_low": levels.support.low if levels.support else None,
        "support_high": levels.support.high if levels.support else None,
        "resistance_low": levels.resistance.low if levels.resistance else None,
        "resistance_high": levels.resistance.high if levels.resistance else None,
        "trend_label": levels.trend.label if levels.trend else None,
        "trend_score": levels.trend.score if levels.trend else None,
        "institutional_bias_label": levels.institutional_bias.label if levels.institutional_bias else None,
        "institutional_bias_score": levels.institutional_bias.score if levels.institutional_bias else None,
        "institutional_bias_data": card.get("institutional_bias_data"),
        "confidence_score": levels.confidence.score if levels.confidence else None,
        "sub_score_trend_alignment": sub.get("trend_alignment"),
        "sub_score_vwap_position": sub.get("vwap_position"),
        "sub_score_structure_hh_hl": sub.get("structure_hh_hl"),
        "sub_score_trendline_confluence": sub.get("trendline_confluence"),
        "sub_score_sr_proximity": sub.get("sr_proximity"),
        "sub_score_breakout_confirmation": sub.get("breakout_confirmation"),
        "sub_score_institutional_bias": sub.get("institutional_bias"),
        "confidence_weights_used": _jsonb(levels.confidence.weights_used if levels.confidence else {}),
        "confidence_partial_data": levels.confidence.partial_data if levels.confidence else None,
        "action_text": card.get("action"),
        "today_vp_bins": _jsonb(levels.today_vp.bins if levels.today_vp else {}),
        "swings": _jsonb([asdict(s) for s in levels.swings]),
        "trendlines": _jsonb([asdict(t) for t in levels.trendlines]),
        "breakout_boxes": _jsonb([asdict(b) for b in levels.breakout_boxes]),
    }

    col_list = ", ".join(_LEVELS_COLUMNS)
    placeholders = ", ".join(f"%({c})s" for c in _LEVELS_COLUMNS)
    update_list = ", ".join(f"{c} = EXCLUDED.{c}" for c in _LEVELS_COLUMNS if c not in ("symbol", "as_of"))

    sql = f"""
        INSERT INTO levels_snapshots ({col_list})
        VALUES ({placeholders})
        ON CONFLICT (symbol, as_of) DO UPDATE SET {update_list}
    """
    execute(sql, values)


def record_chart(symbol: str, as_of: datetime, chart_path: str, trigger: str) -> None:
    execute(
        "UPDATE levels_snapshots SET chart_path = %s, chart_triggered_by = %s WHERE symbol = %s AND as_of = %s",
        (chart_path, trigger, symbol, as_of),
    )


def insert_news_item(item) -> int:
    """Upserts on (source, guid) -- returns the row id either way, so the
    caller can insert-or-fetch without a separate lookup. `item` is a
    market_intelligence.models.NewsItem.
    """
    row = fetch_one(
        """
        INSERT INTO news_items (source, title, link, guid, published_at, summary)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (source, guid) DO UPDATE SET title = EXCLUDED.title
        RETURNING id
        """,
        (item.source, item.title, item.link, item.guid or item.link, item.published_at, item.summary),
    )
    return row[0]


def news_item_exists(source: str, guid: str) -> bool:
    row = fetch_one("SELECT 1 FROM news_items WHERE source = %s AND guid = %s", (source, guid))
    return row is not None


def insert_classified_event(news_item_id: int, event) -> None:
    """`event` is a market_intelligence.models.ClassifiedEvent."""
    execute(
        """
        INSERT INTO classified_events (
            news_item_id, is_relevant, category, severity, confidence, sentiment,
            expected_duration, volatility_impact, reversal_probability,
            affected_sectors, affected_indices,
            expected_direction_nifty, expected_direction_sensex, expected_direction_banknifty,
            recommended_action, risk_level, rationale, model, classified_at
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (news_item_id) DO UPDATE SET
            is_relevant = EXCLUDED.is_relevant, category = EXCLUDED.category,
            severity = EXCLUDED.severity, confidence = EXCLUDED.confidence,
            sentiment = EXCLUDED.sentiment, expected_duration = EXCLUDED.expected_duration,
            volatility_impact = EXCLUDED.volatility_impact,
            reversal_probability = EXCLUDED.reversal_probability,
            affected_sectors = EXCLUDED.affected_sectors, affected_indices = EXCLUDED.affected_indices,
            expected_direction_nifty = EXCLUDED.expected_direction_nifty,
            expected_direction_sensex = EXCLUDED.expected_direction_sensex,
            expected_direction_banknifty = EXCLUDED.expected_direction_banknifty,
            recommended_action = EXCLUDED.recommended_action, risk_level = EXCLUDED.risk_level,
            rationale = EXCLUDED.rationale, model = EXCLUDED.model, classified_at = EXCLUDED.classified_at
        """,
        (
            news_item_id, event.is_relevant, event.category.value, event.severity, event.confidence,
            event.sentiment.value, event.expected_duration.value, event.volatility_impact.value,
            event.reversal_probability, _jsonb(event.affected_sectors), _jsonb(event.affected_indices),
            event.expected_direction_nifty.value, event.expected_direction_sensex.value,
            event.expected_direction_banknifty.value, event.recommended_action, event.risk_level.value,
            event.rationale, event.model, event.classified_at,
        ),
    )


def insert_product_requirement(
    title: str, requirement_text: str, status: str = "submitted", notes: str | None = None
) -> int:
    """Durable audit-trail record of a feature requirement as submitted --
    not part of the trading data model, purely history-maintenance so "what
    was asked for and when" survives independent of chat history.
    """
    row = fetch_one(
        """
        INSERT INTO product_requirements (title, requirement_text, status, notes)
        VALUES (%s, %s, %s, %s)
        RETURNING id
        """,
        (title, requirement_text, status, notes),
    )
    return row[0]


def insert_mti_daily_transition(record, score=None) -> None:
    """`record` is a market_transition.models.DailyTransitionRecord, `score`
    an optional market_transition.models.DailyTransitionScore (None when a
    day couldn't be scored, e.g. too few historical analogs -- the
    feature/outcome columns are still stored so it counts toward future
    correlation studies)."""
    f, o = record.features, record.outcome
    execute(
        """
        INSERT INTO mti_daily_transitions (
            symbol, session_date,
            poc_migration_1400_1459, vwap_distance_1459, vwap_distance_1459_pct,
            volume_slope_1400_1459, realized_range_1400_1459, profile_shape_1459,
            rotation_label_1459, market_regime_1459, is_inside_initial_balance_1459,
            day_of_week, expiry_type, prior_day_profile_shape, prior_day_close_vs_poc,
            close_1459, close_1501, market_close, transition_move, transition_direction,
            post_transition_move, outcome, outcome_magnitude,
            transition_risk_score, probability_continuation, probability_reversal,
            expected_volatility, expected_direction, historical_similarity_score,
            top_contributing_factors, statistical_confidence, explanation, computed_at
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (symbol, session_date) DO UPDATE SET
            poc_migration_1400_1459 = EXCLUDED.poc_migration_1400_1459,
            vwap_distance_1459 = EXCLUDED.vwap_distance_1459,
            vwap_distance_1459_pct = EXCLUDED.vwap_distance_1459_pct,
            volume_slope_1400_1459 = EXCLUDED.volume_slope_1400_1459,
            realized_range_1400_1459 = EXCLUDED.realized_range_1400_1459,
            profile_shape_1459 = EXCLUDED.profile_shape_1459,
            rotation_label_1459 = EXCLUDED.rotation_label_1459,
            market_regime_1459 = EXCLUDED.market_regime_1459,
            is_inside_initial_balance_1459 = EXCLUDED.is_inside_initial_balance_1459,
            day_of_week = EXCLUDED.day_of_week, expiry_type = EXCLUDED.expiry_type,
            prior_day_profile_shape = EXCLUDED.prior_day_profile_shape,
            prior_day_close_vs_poc = EXCLUDED.prior_day_close_vs_poc,
            close_1459 = EXCLUDED.close_1459, close_1501 = EXCLUDED.close_1501,
            market_close = EXCLUDED.market_close, transition_move = EXCLUDED.transition_move,
            transition_direction = EXCLUDED.transition_direction,
            post_transition_move = EXCLUDED.post_transition_move, outcome = EXCLUDED.outcome,
            outcome_magnitude = EXCLUDED.outcome_magnitude,
            transition_risk_score = EXCLUDED.transition_risk_score,
            probability_continuation = EXCLUDED.probability_continuation,
            probability_reversal = EXCLUDED.probability_reversal,
            expected_volatility = EXCLUDED.expected_volatility,
            expected_direction = EXCLUDED.expected_direction,
            historical_similarity_score = EXCLUDED.historical_similarity_score,
            top_contributing_factors = EXCLUDED.top_contributing_factors,
            statistical_confidence = EXCLUDED.statistical_confidence,
            explanation = EXCLUDED.explanation, computed_at = EXCLUDED.computed_at
        """,
        (
            record.symbol, record.session_date,
            f.poc_migration_1400_1459, f.vwap_distance_1459, f.vwap_distance_1459_pct,
            f.volume_slope_1400_1459, f.realized_range_1400_1459, f.profile_shape_1459,
            f.rotation_label_1459, f.market_regime_1459, f.is_inside_initial_balance_1459,
            f.day_of_week, f.expiry_type, f.prior_day_profile_shape, f.prior_day_close_vs_poc,
            o.close_1459, o.close_1501, o.market_close, o.transition_move, o.transition_direction,
            o.post_transition_move, o.outcome, o.outcome_magnitude,
            score.transition_risk_score if score else None,
            score.probability_continuation if score else None,
            score.probability_reversal if score else None,
            score.expected_volatility if score else None,
            score.expected_direction if score else None,
            score.historical_similarity_score if score else None,
            _jsonb([asdict(c) for c in score.top_contributing_factors]) if score else None,
            score.statistical_confidence if score else None,
            score.explanation if score else None,
            score.computed_at if score else None,
        ),
    )


def insert_mti_factor_correlation(symbol: str, result) -> None:
    """`result` is a market_transition.models.FactorCorrelationResult."""
    execute(
        """
        INSERT INTO mti_factor_correlations (
            symbol, factor_name, factor_type, target, n_days, statistic, p_value,
            confidence_label, direction_note, category_breakdown
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (symbol, factor_name, target) DO UPDATE SET
            factor_type = EXCLUDED.factor_type, n_days = EXCLUDED.n_days,
            statistic = EXCLUDED.statistic, p_value = EXCLUDED.p_value,
            confidence_label = EXCLUDED.confidence_label, direction_note = EXCLUDED.direction_note,
            category_breakdown = EXCLUDED.category_breakdown, computed_at = now()
        """,
        (
            symbol, result.factor_name, result.factor_type, result.target, result.n,
            result.statistic, result.p_value, result.confidence_label, result.direction_note,
            _jsonb(result.category_breakdown) if result.category_breakdown else None,
        ),
    )


def insert_cas_daily_transition(record) -> None:
    """`record` is a market_transition.cas_transition.CasDailyTransition."""
    execute(
        """
        INSERT INTO mti_cas_daily_transitions (
            symbol, session_date, close_1431, close_1459, close_1539,
            pre_direction, post_direction, conclusion, outcome_magnitude,
            pre_window_volume, post_window_pre_auction_volume, volume_ratio,
            pre_window_points_move, post_window_points_move,
            pcr_1459, institutional_bias_label_1459, institutional_bias_score_1459,
            expiry_type, day_of_week, old_methodology_outcome, old_methodology_outcome_magnitude,
            data_quality_flag, transition_type, magnitude_pct_return, magnitude_atr_normalized, magnitude_tier
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (symbol, session_date) DO UPDATE SET
            close_1431 = EXCLUDED.close_1431, close_1459 = EXCLUDED.close_1459, close_1539 = EXCLUDED.close_1539,
            pre_direction = EXCLUDED.pre_direction, post_direction = EXCLUDED.post_direction,
            conclusion = EXCLUDED.conclusion, outcome_magnitude = EXCLUDED.outcome_magnitude,
            pre_window_volume = EXCLUDED.pre_window_volume,
            post_window_pre_auction_volume = EXCLUDED.post_window_pre_auction_volume,
            volume_ratio = EXCLUDED.volume_ratio,
            pre_window_points_move = EXCLUDED.pre_window_points_move,
            post_window_points_move = EXCLUDED.post_window_points_move,
            pcr_1459 = EXCLUDED.pcr_1459, institutional_bias_label_1459 = EXCLUDED.institutional_bias_label_1459,
            institutional_bias_score_1459 = EXCLUDED.institutional_bias_score_1459,
            expiry_type = EXCLUDED.expiry_type, day_of_week = EXCLUDED.day_of_week,
            old_methodology_outcome = EXCLUDED.old_methodology_outcome,
            old_methodology_outcome_magnitude = EXCLUDED.old_methodology_outcome_magnitude,
            data_quality_flag = EXCLUDED.data_quality_flag,
            transition_type = EXCLUDED.transition_type,
            magnitude_pct_return = EXCLUDED.magnitude_pct_return,
            magnitude_atr_normalized = EXCLUDED.magnitude_atr_normalized,
            magnitude_tier = EXCLUDED.magnitude_tier,
            computed_at = now()
        """,
        (
            record.symbol, record.session_date, record.close_1431, record.close_1459, record.close_1539,
            record.pre_direction, record.post_direction, record.conclusion, record.outcome_magnitude,
            record.pre_window_volume, record.post_window_pre_auction_volume, record.volume_ratio,
            record.pre_window_points_move, record.post_window_points_move,
            record.pcr_1459, record.institutional_bias_label_1459, record.institutional_bias_score_1459,
            record.expiry_type, record.day_of_week, record.old_methodology_outcome, record.old_methodology_outcome_magnitude,
            record.data_quality_flag, record.transition_type, record.magnitude_pct_return,
            record.magnitude_atr_normalized, record.magnitude_tier,
        ),
    )


def insert_cas_factor_correlation(symbol: str, result) -> None:
    """`result` is a market_transition.models.FactorCorrelationResult, same
    shape insert_mti_factor_correlation writes -- just a different table."""
    execute(
        """
        INSERT INTO mti_cas_factor_correlations (
            symbol, factor_name, factor_type, target, n_days, statistic, p_value,
            confidence_label, direction_note, category_breakdown
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (symbol, factor_name, target) DO UPDATE SET
            factor_type = EXCLUDED.factor_type, n_days = EXCLUDED.n_days,
            statistic = EXCLUDED.statistic, p_value = EXCLUDED.p_value,
            confidence_label = EXCLUDED.confidence_label, direction_note = EXCLUDED.direction_note,
            category_breakdown = EXCLUDED.category_breakdown, computed_at = now()
        """,
        (
            symbol, result.factor_name, result.factor_type, result.target, result.n,
            result.statistic, result.p_value, result.confidence_label, result.direction_note,
            _jsonb(result.category_breakdown) if result.category_breakdown else None,
        ),
    )


# --- Phase 7B: dual-resolution pre/post-3pm transition detail -----------
# (market_transition/cas_windows.py + cas_forecast.py). All three inserts
# build their column/value lists from the dataclass's own field names --
# with this many columns, one source of truth for the field list avoids a
# manual tuple silently drifting out of order from the dataclass.


def _insert_from_dataclass(table: str, record, extra_cols: dict, conflict_cols: tuple[str, ...]) -> None:
    """extra_cols are columns not on the dataclass itself (symbol,
    session_date, and whichever index/label column keys the row)."""
    field_names = list(record.__dataclass_fields__.keys())
    columns = list(extra_cols.keys()) + field_names
    values = list(extra_cols.values()) + [getattr(record, f) for f in field_names]
    placeholders = ",".join(["%s"] * len(columns))
    update_cols = [c for c in columns if c not in conflict_cols]
    update_clause = ", ".join(f"{c} = EXCLUDED.{c}" for c in update_cols) + ", computed_at = now()"
    execute(
        f"""
        INSERT INTO {table} ({",".join(columns)}) VALUES ({placeholders})
        ON CONFLICT ({",".join(conflict_cols)}) DO UPDATE SET {update_clause}
        """,
        tuple(values),
    )


def insert_cas_pretransition_window(symbol: str, session_date: date, window) -> None:
    """`window` is a market_transition.cas_windows.PreTransitionWindow."""
    _insert_from_dataclass(
        "cas_pretransition_windows", window,
        extra_cols={"symbol": symbol, "session_date": session_date},
        conflict_cols=("symbol", "session_date", "window_index"),
    )


def insert_cas_post_transition_minute(symbol: str, session_date: date, minute) -> None:
    """`minute` is a market_transition.cas_windows.PostTransitionMinute."""
    _insert_from_dataclass(
        "cas_post_transition_minutes", minute,
        extra_cols={"symbol": symbol, "session_date": session_date},
        conflict_cols=("symbol", "session_date", "minute_offset"),
    )


def insert_cas_transition_forecast(symbol: str, session_date: date, forecast) -> None:
    """`forecast` is a market_transition.cas_forecast.TransitionForecast."""
    field_names = [f for f in forecast.__dataclass_fields__.keys() if f != "top_contributing_factors"]
    columns = ["symbol", "session_date"] + field_names + ["top_contributing_factors"]
    values = [symbol, session_date] + [getattr(forecast, f) for f in field_names] + [
        _jsonb([asdict(c) for c in forecast.top_contributing_factors]) if forecast.top_contributing_factors else None
    ]
    placeholders = ",".join(["%s"] * len(columns))
    conflict_cols = ("symbol", "session_date", "checkpoint_time")
    update_cols = [c for c in columns if c not in conflict_cols]
    update_clause = ", ".join(f"{c} = EXCLUDED.{c}" for c in update_cols) + ", computed_at = now()"
    execute(
        f"""
        INSERT INTO cas_transition_forecasts ({",".join(columns)}) VALUES ({placeholders})
        ON CONFLICT ({",".join(conflict_cols)}) DO UPDATE SET {update_clause}
        """,
        tuple(values),
    )


# --- Phase 7C: historical cohorts + pre-3pm warning-indicator stats -----
# (market_transition/cas_cohorts.py).


def insert_cas_cohort_feature_stat(symbol: str, stat) -> None:
    """`stat` is a market_transition.cas_cohorts.CohortFeatureStat."""
    _insert_from_dataclass(
        "mti_cas_cohort_analysis", stat,
        extra_cols={"symbol": symbol},
        conflict_cols=("symbol", "cohort", "feature_name"),
    )


def insert_cas_cohort_categorical(symbol: str, breakdown) -> None:
    """`breakdown` is a market_transition.cas_cohorts.CohortCategoricalBreakdown."""
    execute(
        """
        INSERT INTO mti_cas_cohort_categorical (symbol, cohort, feature_name, n, category_counts, full_sample_category_counts)
        VALUES (%s,%s,%s,%s,%s,%s)
        ON CONFLICT (symbol, cohort, feature_name) DO UPDATE SET
            n = EXCLUDED.n, category_counts = EXCLUDED.category_counts,
            full_sample_category_counts = EXCLUDED.full_sample_category_counts, computed_at = now()
        """,
        (
            symbol, breakdown.cohort, breakdown.feature_name, breakdown.n,
            _jsonb(breakdown.category_counts), _jsonb(breakdown.full_sample_category_counts),
        ),
    )
