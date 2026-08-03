import os
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

DHAN_CLIENT_ID = os.getenv("DHAN_CLIENT_ID")
DHAN_ACCESS_TOKEN = os.getenv("DHAN_ACCESS_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
DB_SCHEMA = os.getenv("DB_SCHEMA", "public")


def require_credentials() -> tuple[str, str]:
    if not DHAN_CLIENT_ID or not DHAN_ACCESS_TOKEN:
        raise RuntimeError(
            "DHAN_CLIENT_ID / DHAN_ACCESS_TOKEN are not set. "
            "Copy .env.example to .env and fill in your Dhan credentials."
        )
    return DHAN_CLIENT_ID, DHAN_ACCESS_TOKEN


def require_database_url() -> str:
    if not DATABASE_URL:
        raise RuntimeError(
            "DATABASE_URL is not set. Create the database/role yourself, then add "
            "DATABASE_URL=postgresql://user:password@host:port/dbname to .env."
        )
    return DATABASE_URL


IST = ZoneInfo("Asia/Kolkata")

SESSION_OPEN = "09:15"
# NSE extended the F&O session close from 15:30 to 15:40 effective 2026-08-03
# (new Closing Auction Session framework for the cash/equity segment runs
# 15:15-15:35; the VWAP window used for derivative closing prices is now
# 15:10-15:40). Since SENSEX/NIFTY options are the actual instruments this
# tool supports, the F&O close is the one that governs when the pipeline
# should keep collecting live data.
SESSION_CLOSE = "15:40"

SNAPSHOT_ROOT = PROJECT_ROOT / "vol_pro_snapshot_training"
CACHE_DIR = PROJECT_ROOT / "data" / "cache"
LOG_DIR = PROJECT_ROOT / "logs"

for _d in (SNAPSHOT_ROOT, CACHE_DIR, LOG_DIR):
    _d.mkdir(parents=True, exist_ok=True)

SCRIP_MASTER_URL = "https://images.dhan.co/api-data/api-scrip-master.csv"
SCRIP_MASTER_CACHE = CACHE_DIR / "scrip_master.csv"
SCRIP_MASTER_MAX_AGE_HOURS = 20  # index security IDs rarely change; daily refresh is plenty

DEFAULT_CHART_INTERVAL_MIN = 5
VOLUME_PROFILE_SOURCE_INTERVAL_MIN = 1
LIVE_LOOP_INTERVAL_MIN = 1  # live poll/compute/write cadence (finest Dhan's REST candle API supports)
BACKFILL_CHECKPOINT_INTERVAL_MIN = 5  # kept independent of LIVE_LOOP_INTERVAL_MIN -- do not let backfill silently inherit the live cadence
BACKFILL_LOOKBACK_DAYS = 60
BACKFILL_CHART_CHECKPOINTS = ["10:00", "12:00", "14:00", "15:25"]
CHART_BACKSTOP_MINUTES = 15  # force a chart render if no trend/POC event has fired in this long
