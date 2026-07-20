"""One-time migration: import the existing JSON snapshot archive
(vol_pro_snapshot_training/) into Postgres, plus the matching 60-day raw
candle history per symbol (raw candles weren't part of the old JSON output).

Usage: venv\\Scripts\\python.exe db\\migrate_json_to_db.py

Safe to re-run: every insert uses ON CONFLICT DO NOTHING, and each folder is
imported in its own transaction, so an interrupted run can just be restarted
-- already-imported rows are cheap no-ops rather than needing checkpoint/
resume tracking.
"""
import json
import logging
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from psycopg.types.json import Jsonb

from config.instruments import INSTRUMENTS
from config.settings import BACKFILL_LOOKBACK_DAYS, SNAPSHOT_ROOT
from db import writer as db_writer
from db.connection import get_connection
from dhan_client.client import fetch_daily_candles, fetch_intraday_candles

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

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
    "chart_path", "chart_triggered_by",
]


def _row_from_json(levels_json: dict, card_json: dict, meta_json: dict, chart_path: str | None) -> dict:
    today_vp = levels_json.get("today_volume_profile") or {}
    yesterday_vp = levels_json.get("yesterday_volume_profile") or {}
    support = levels_json.get("support") or {}
    resistance = levels_json.get("resistance") or {}
    trend = levels_json.get("trend") or {}
    bias = levels_json.get("institutional_bias") or {}
    confidence = levels_json.get("confidence") or {}
    sub = confidence.get("sub_scores") or {}

    return {
        "symbol": levels_json["symbol"],
        "as_of": datetime.fromisoformat(levels_json["as_of"]),
        "mode": meta_json.get("mode", "backfill"),
        "close": levels_json["close"],
        "vwap_now": levels_json.get("vwap_now"),
        "today_poc": today_vp.get("poc"),
        "today_vah": today_vp.get("vah"),
        "today_val": today_vp.get("val"),
        "today_total_volume": today_vp.get("total_volume"),
        "yesterday_poc": yesterday_vp.get("poc"),
        "yesterday_vah": yesterday_vp.get("vah"),
        "yesterday_val": yesterday_vp.get("val"),
        "support_low": support.get("low"),
        "support_high": support.get("high"),
        "resistance_low": resistance.get("low"),
        "resistance_high": resistance.get("high"),
        "trend_label": trend.get("label"),
        "trend_score": trend.get("score"),
        "institutional_bias_label": bias.get("label"),
        "institutional_bias_score": bias.get("score"),
        "institutional_bias_data": card_json.get("institutional_bias_data"),
        "confidence_score": confidence.get("score"),
        "sub_score_trend_alignment": sub.get("trend_alignment"),
        "sub_score_vwap_position": sub.get("vwap_position"),
        "sub_score_structure_hh_hl": sub.get("structure_hh_hl"),
        "sub_score_trendline_confluence": sub.get("trendline_confluence"),
        "sub_score_sr_proximity": sub.get("sr_proximity"),
        "sub_score_breakout_confirmation": sub.get("breakout_confirmation"),
        "sub_score_institutional_bias": sub.get("institutional_bias"),
        "confidence_weights_used": Jsonb(confidence.get("weights_used") or {}),
        "confidence_partial_data": confidence.get("partial_data"),
        "action_text": card_json.get("action"),
        "today_vp_bins": Jsonb(today_vp.get("bins") or {}),
        "swings": Jsonb(levels_json.get("swings") or []),
        "trendlines": Jsonb(levels_json.get("trendlines") or []),
        "breakout_boxes": Jsonb(levels_json.get("breakout_boxes") or []),
        "chart_path": chart_path,
        "chart_triggered_by": "backfill_checkpoint" if chart_path else None,
    }


def _insert_folder_row(conn, row: dict) -> None:
    col_list = ", ".join(_LEVELS_COLUMNS)
    placeholders = ", ".join(f"%({c})s" for c in _LEVELS_COLUMNS)
    sql = f"""
        INSERT INTO levels_snapshots ({col_list})
        VALUES ({placeholders})
        ON CONFLICT (symbol, as_of) DO NOTHING
    """
    with conn.cursor() as cur:
        cur.execute(sql, row)


def migrate_symbol_snapshots(symbol: str, root: Path = SNAPSHOT_ROOT) -> tuple[int, int]:
    symbol_dir = root / symbol
    if not symbol_dir.exists():
        logger.warning("No snapshot folder for %s at %s", symbol, symbol_dir)
        return 0, 0

    conn = get_connection()
    imported = 0
    skipped = 0

    for date_dir in sorted(p for p in symbol_dir.iterdir() if p.is_dir()):
        for time_dir in sorted(p for p in date_dir.iterdir() if p.is_dir()):
            levels_path = time_dir / "levels.json"
            card_path = time_dir / "decision_card.json"
            meta_path = time_dir / "meta.json"
            if not (levels_path.exists() and card_path.exists()):
                skipped += 1
                continue

            levels_json = json.loads(levels_path.read_text(encoding="utf-8"))
            card_json = json.loads(card_path.read_text(encoding="utf-8"))
            meta_json = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
            chart_path = str(time_dir / "chart.png") if (time_dir / "chart.png").exists() else None

            row = _row_from_json(levels_json, card_json, meta_json, chart_path)
            try:
                with conn.transaction():
                    _insert_folder_row(conn, row)
                imported += 1
            except Exception:
                logger.exception("Failed to import %s", time_dir)
                skipped += 1

        logger.info("Migrated %s %s", symbol, date_dir.name)

    return imported, skipped


def migrate_symbol_raw_candles(symbol: str, lookback_days: int = BACKFILL_LOOKBACK_DAYS) -> None:
    end_date = date.today()
    start_date = end_date - timedelta(days=int(lookback_days * 1.6) + 5)
    candles_1min = fetch_intraday_candles(symbol, start_date, end_date, interval=1)
    daily = fetch_daily_candles(symbol, start_date, end_date)
    n_candles = db_writer.insert_raw_candles(candles_1min, symbol)
    n_daily = db_writer.insert_daily_candles(daily, symbol)
    logger.info("%s: persisted raw candles (%d 1-min rows, %d daily rows)", symbol, n_candles, n_daily)


def main():
    for symbol in INSTRUMENTS:
        imported, skipped = migrate_symbol_snapshots(symbol)
        print(f"{symbol}: imported {imported} levels_snapshots rows, skipped {skipped}")
        migrate_symbol_raw_candles(symbol)


if __name__ == "__main__":
    main()
