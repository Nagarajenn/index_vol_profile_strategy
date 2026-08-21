"""Read-only comparison: the shipped 3pm-transition methodology (sharp
14:00-14:59 pre-window / 15:00-15:01 transition moment / 15:01-close
follow-through) vs. a CAS-adjusted re-framing (14:30-14:59 pre-window trend
vs. 15:00-close post-window trend), run side by side over the exact same
raw_candles history -- see market_transition/cas_transition.py for why the
new framing exists and market_transition/research.py's extract_fn
parameter for how both methodologies reuse the identical correlation-study/
scoring pipeline.

Writes NOTHING to any database table -- purely prints a comparison so the
CAS-adjusted framing's findings can be reviewed before any decision is made
about promoting it to replace the live methodology (mti_daily_transitions/
mti_factor_correlations, the Live Advisor, or the dashboard page).

Usage: venv\\Scripts\\python.exe scripts\\run_cas_transition_analysis.py [--symbols SENSEX NIFTY]
"""

import argparse
import sys
from collections import Counter
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: F401 -- truststore bootstrap, must import before any DB/HTTPS call
from config.instruments import INSTRUMENTS
from db import reader as db_reader
from market_transition.cas_transition import extract_cas_transition_record
from market_transition.feature_extraction import extract_daily_transition_record
from market_transition.research import run_research
from market_transition.statistics import run_correlation_study

CAS_EFFECTIVE_DATE = date(2026, 8, 3)


def _outcome_distribution(records) -> Counter:
    return Counter(r.outcome.outcome for r in records)


def _print_distribution(label: str, dist: Counter, total: int) -> None:
    if total == 0:
        print(f"  {label}: no days")
        return
    parts = [f"{k}={v} ({v / total * 100:.0f}%)" for k, v in sorted(dist.items())]
    print(f"  {label} (n={total}): " + ", ".join(parts))


def _significant_count(correlations) -> int:
    return sum(1 for c in correlations if c.confidence_label in ("Strong", "Moderate"))


def analyze_symbol(symbol: str) -> None:
    bin_size = INSTRUMENTS[symbol]["volume_profile_bin_size"]
    candles = db_reader.load_raw_candles(symbol)
    print(f"\n=== {symbol} ({len(candles)} raw candles loaded) ===")

    old_records, _, _ = run_research(symbol, candles, bin_size, extract_fn=extract_daily_transition_record)
    new_records, _, _ = run_research(symbol, candles, bin_size, extract_fn=extract_cas_transition_record)

    old_pre = [r for r in old_records if r.session_date < CAS_EFFECTIVE_DATE]
    old_post = [r for r in old_records if r.session_date >= CAS_EFFECTIVE_DATE]
    new_pre = [r for r in new_records if r.session_date < CAS_EFFECTIVE_DATE]
    new_post = [r for r in new_records if r.session_date >= CAS_EFFECTIVE_DATE]

    print(f"Old methodology: {len(old_records)} days total ({len(old_pre)} pre-CAS, {len(old_post)} post-CAS)")
    print(f"New methodology: {len(new_records)} days total ({len(new_pre)} pre-CAS, {len(new_post)} post-CAS)")

    print("\nOutcome distribution -- pre-CAS days (old methodology, the historical baseline):")
    _print_distribution("old/pre-CAS", _outcome_distribution(old_pre), len(old_pre))

    print("\nOutcome distribution -- post-CAS days, old vs new methodology:")
    _print_distribution("old/post-CAS", _outcome_distribution(old_post), len(old_post))
    _print_distribution("new/post-CAS", _outcome_distribution(new_post), len(new_post))

    if len(old_post) >= 10:
        old_post_corr = run_correlation_study(old_post)
        print(f"\nCorrelation study, post-CAS days only, old windows:  {_significant_count(old_post_corr)}/{len(old_post_corr)} factor/target pairs reached Strong/Moderate confidence")
    else:
        print(f"\nToo few post-CAS days ({len(old_post)}) for a separate correlation study yet.")

    if len(new_post) >= 10:
        new_post_corr = run_correlation_study(new_post)
        print(f"Correlation study, post-CAS days only, new (CAS) windows: {_significant_count(new_post_corr)}/{len(new_post_corr)} factor/target pairs reached Strong/Moderate confidence")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", nargs="*", default=list(INSTRUMENTS.keys()))
    args = parser.parse_args()

    for symbol in args.symbols:
        analyze_symbol(symbol)


if __name__ == "__main__":
    main()
