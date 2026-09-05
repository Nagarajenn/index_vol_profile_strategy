"""Phase 9A: Option Chain Snapshot derivation. For every day that has
option_chain_raw data, derives the 8 fixed daily checkpoints
(09:20/11:00/13:00/14:00/14:30/15:00/15:15/15:30) entirely from data
already captured by the live loop -- NO new Dhan API calls. For each
checkpoint: selects the nearest option_chain_raw row at/before that time,
computes the derived-feature set (option_chain/snapshot_features.py),
diffs against that SAME day's immediately-prior checkpoint for the
build-up/unwinding/change fields, classifies positioning, and persists to
option_chain_snapshot + option_chain_snapshot_detail.

Re-runnable/idempotent like every other script in this project.

Usage: venv\\Scripts\\python.exe scripts\\run_option_snapshot_features.py [--symbols SENSEX NIFTY]
"""

import argparse
import logging
import sys
from datetime import datetime, timedelta, time as dt_time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: F401 -- truststore bootstrap, must import before any DB/HTTPS call
from config.settings import IST
from db import reader as db_reader
from db import writer as db_writer
from market_transition.expiry_calendar import classify_expiry_day
from option_chain.snapshot_features import classify_option_positioning, compute_snapshot_features, extract_atm_window

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

CHECKPOINTS: list[tuple[str, dt_time]] = [
    ("09:20", dt_time(9, 20)), ("11:00", dt_time(11, 0)), ("13:00", dt_time(13, 0)), ("14:00", dt_time(14, 0)),
    ("14:30", dt_time(14, 30)), ("15:00", dt_time(15, 0)), ("15:15", dt_time(15, 15)), ("15:30", dt_time(15, 30)),
]

GOOD_TOLERANCE_MIN = 2
DEGRADED_TOLERANCE_MIN = 15
MIN_STRIKES_EACH_SIDE_FOR_GOOD = 5  # ATM +/- 5 -- fewer than this on either side is DEGRADED, not GOOD


def _data_quality(target: dt_time, actual_fetched_at: datetime, n_ce: int, n_pe: int) -> str:
    actual_time = actual_fetched_at.astimezone(IST).time() if actual_fetched_at.tzinfo else actual_fetched_at.time()
    gap_minutes = abs((datetime.combine(datetime.today(), actual_time) - datetime.combine(datetime.today(), target)).total_seconds()) / 60
    if gap_minutes <= GOOD_TOLERANCE_MIN and n_ce >= MIN_STRIKES_EACH_SIDE_FOR_GOOD and n_pe >= MIN_STRIKES_EACH_SIDE_FOR_GOOD:
        return "GOOD"
    if gap_minutes <= DEGRADED_TOLERANCE_MIN:
        return "DEGRADED"
    return "INSUFFICIENT"


def run_symbol(symbol: str) -> tuple[int, int]:
    dates = db_reader.list_option_chain_raw_dates(symbol)
    n_snapshots = n_details = 0

    for session_date in dates:
        prior_features = None
        for label, target_time in CHECKPOINTS:
            row = db_reader.get_option_chain_raw_near(symbol, session_date, at_or_before=target_time.strftime("%H:%M:%S"))
            if row is None:
                prior_features = None  # a gap breaks the change-vs-prior chain honestly, not silently
                continue

            raw_payload = row["raw_payload"]
            features = compute_snapshot_features(raw_payload, prior=prior_features)
            if features is None:
                prior_features = None
                continue

            details = extract_atm_window(raw_payload)
            n_ce = sum(1 for d in details if d.leg == "CE")
            n_pe = sum(1 for d in details if d.leg == "PE")
            quality = _data_quality(target_time, row["fetched_at"], n_ce, n_pe)
            classification = classify_option_positioning(features)

            expiry_type = classify_expiry_day(symbol, session_date)
            db_writer.insert_option_chain_snapshot(
                symbol, session_date, label, row["fetched_at"], row["expiry"], expiry_type,
                features, classification, quality, row["fetched_at"],
            )
            db_writer.insert_option_chain_snapshot_detail(symbol, session_date, label, details)
            n_snapshots += 1
            n_details += len(details)
            prior_features = features

    return n_snapshots, n_details


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", nargs="+", default=["SENSEX", "NIFTY"])
    args = parser.parse_args()

    for symbol in args.symbols:
        n_snapshots, n_details = run_symbol(symbol)
        logger.info("%s: wrote %d option snapshots, %d strike-detail rows", symbol, n_snapshots, n_details)


if __name__ == "__main__":
    main()
