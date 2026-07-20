import json
from dataclasses import asdict
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd
from psycopg.types.json import Jsonb

from analytics.levels import LevelsResult
from db import reader
from db.connection import execute, executemany
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
