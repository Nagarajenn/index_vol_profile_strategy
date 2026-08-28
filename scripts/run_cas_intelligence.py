"""CAS Intelligence: computes and persists the CAS-adjusted 3pm-transition
comparison (see market_transition/cas_transition.py) for every post-CAS
trading day, alongside the same day's outcome under the original
methodology and the option-chain context at ~14:59. Writes to
mti_cas_daily_transitions -- entirely separate from mti_daily_transitions/
mti_factor_correlations (the original engine, still the source of truth
for the Live Advisor and the existing dashboard page).

Re-runnable/idempotent -- upserts, so running this again after a new
trading day closes just adds that day (and refreshes prior days' option
context/data-quality flags if candle data was corrected since).

Usage: venv\\Scripts\\python.exe scripts\\run_cas_intelligence.py [--symbols SENSEX NIFTY]
"""

import argparse
import logging
import sys
import time as time_module
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: F401 -- truststore bootstrap, must import before any DB/HTTPS call
from analytics.breakout_boxes import compute_atr
from analytics.institutional_bias import classify_institutional_bias
from config.instruments import INSTRUMENTS
from db import reader as db_reader
from db import writer as db_writer
from market_transition.cas_statistics import run_cas_correlation_study
from market_transition.cas_transition import CAS_EFFECTIVE_DATE, build_cas_daily_transition, extract_cas_transition_record
from market_transition.feature_extraction import extract_daily_transition_record
from market_transition.research import extract_all_records
from option_chain.summary import OptionChainSummary

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def _option_context(symbol: str, session_date) -> dict | None:
    row = db_reader.get_option_summary_near(symbol, session_date)
    if row is None:
        return None
    summary = OptionChainSummary(
        expiry="", spot=row["spot"], atm_strike=row["atm_strike"], pcr=row["pcr"],
        call_oi_change_near_atm=row["call_oi_change_near_atm"], put_oi_change_near_atm=row["put_oi_change_near_atm"],
        total_call_oi=row["total_call_oi"], total_put_oi=row["total_put_oi"],
        atm_iv_call=row["atm_iv_call"], atm_iv_put=row["atm_iv_put"],
        max_call_oi_strike=row["max_call_oi_strike"], max_put_oi_strike=row["max_put_oi_strike"],
    )
    bias = classify_institutional_bias(summary, current_price=row["spot"])
    return {"pcr": row["pcr"], "bias_label": bias.label, "bias_score": bias.score}


def _split_by_date(candles):
    if candles.empty:
        return {}
    return {d: g.reset_index(drop=True) for d, g in candles.groupby(candles["timestamp"].dt.date)}


def _daily_atr_by_date(candles, period: int = 14) -> dict:
    """Resamples the already-loaded 1-min history into daily OHLC bars and
    computes a rolling ATR(14) per day -- used to volatility-normalize each
    day's transition magnitude (see cas_transition.classify_transition_magnitude).
    Computed once per symbol from the same candles already in memory, no new
    DB read. Each day's row in the returned dict is that day's own ATR
    (i.e. including that day's own range) -- callers use the *prior*
    trading day's value so the normalization never looks ahead."""
    if candles.empty:
        return {}
    daily = candles.assign(session_date=candles["timestamp"].dt.date)
    bars = daily.groupby("session_date").agg(open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last"))
    atr = compute_atr(bars, period=period)
    return atr.to_dict()


def run_symbol(symbol: str) -> tuple[int, int]:
    bin_size = INSTRUMENTS[symbol]["volume_profile_bin_size"]
    candles = db_reader.load_raw_candles(symbol)
    by_date = _split_by_date(candles)

    old_records = extract_all_records(symbol, candles, bin_size, extract_fn=extract_daily_transition_record)
    old_by_date = {r.session_date: r for r in old_records}
    atr_by_date = _daily_atr_by_date(candles)

    written = 0
    cas_rows = []
    for session_date, day_candles in sorted(by_date.items()):
        if session_date < CAS_EFFECTIVE_DATE:
            continue

        prior_dates = sorted(d for d in by_date if d < session_date)
        prior_day_candles = by_date[prior_dates[-1]] if prior_dates else None
        window_start = max(0, len(prior_dates) - 20)
        historical_by_date = {d: by_date[d] for d in prior_dates[window_start:]}

        old = old_by_date.get(session_date)
        expiry_type = old.features.expiry_type if old else None
        # Prior trading day's ATR, never today's own (still-forming) bar --
        # so the magnitude normalization never looks ahead.
        atr_14 = atr_by_date.get(prior_dates[-1]) if prior_dates else None

        record = build_cas_daily_transition(
            symbol,
            session_date,
            day_candles,
            prior_day_candles,
            historical_by_date,
            bin_size,
            expiry_type,
            old_outcome=old.outcome.outcome if old else None,
            old_outcome_magnitude=old.outcome.outcome_magnitude if old else None,
            option_context=_option_context(symbol, session_date),
            atr_14=atr_14,
        )
        if record is None:
            continue

        db_writer.insert_cas_daily_transition(record)
        cas_rows.append(record)
        written += 1
        if record.data_quality_flag:
            logger.warning("%s %s: %s", symbol, session_date, record.data_quality_flag)

    # Correlation study: reuses the SAME CAS-windowed records the loop above
    # was built from (recomputed once more here rather than threaded out of
    # the loop -- this script already recomputes old_records/per-day records
    # independently, and a once-daily run has no real cost pressure).
    cas_records = extract_all_records(symbol, candles, bin_size, extract_fn=extract_cas_transition_record)
    cas_records = [r for r in cas_records if r.session_date >= CAS_EFFECTIVE_DATE]
    correlations = run_cas_correlation_study(cas_records, cas_rows)
    for c in correlations:
        db_writer.insert_cas_factor_correlation(symbol, c)

    return written, len(correlations)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", nargs="*", default=list(INSTRUMENTS.keys()))
    args = parser.parse_args()

    for symbol in args.symbols:
        t0 = time_module.monotonic()
        written, n_correlations = run_symbol(symbol)
        print(f"{symbol}: wrote {written} CAS Intelligence rows and {n_correlations} factor correlations in {time_module.monotonic() - t0:.1f}s")


if __name__ == "__main__":
    main()
