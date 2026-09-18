"""Versioned configuration for the 12A-scalp-v1 research strategy.

12A is an EXPERIMENT that runs beside the frozen 11d-paper-v1 CONTROL. It
shares no configuration, account, hash or code path with 11D.

Every threshold below is labelled with its evidence status:

* ``RESEARCH_1MIN``  -- a candidate range established by the chronological
  1-minute research (scripts/run_scalp12a_research.py, train days only).
  Used as a provisional starting value for the 5-second engine; 1-minute
  evidence does NOT validate 5-second behaviour.
* ``PROVISIONAL_5S`` -- a 5-second parameter with no validated basis yet.
  The HR history (4 days at build time) is far too short to lock it.
  Recorded so shadow results are reproducible, never presented as tuned.
* ``POLICY``         -- a risk/account policy choice, not a market estimate.
* ``EVIDENCE_VETO``  -- a hard rule backed by the 11D->12A gap analysis.

Any change to a value here must bump CONFIG_VERSION; the hash is stamped on
every shadow candidate so results under different settings are never pooled.
"""

import hashlib
import json
from dataclasses import asdict, dataclass

STRATEGY_VERSION = "12A-scalp-v1"
ENGINE_VERSION = "engine-v1"
CONFIG_VERSION = "config-v1"


@dataclass(frozen=True)
class ScalpConfig:
    # ---- market modes (IST) -------------------------------------- POLICY
    mode_a_start: str = "15:00:00"            # underlying + options + futures
    mode_b_start: str = "15:15:00"            # index frozen: futures/options only
    mode_b_end: str = "15:30:00"
    session_exit_by: str = "15:29:55"
    mode_b_tradeable: bool = False            # v1: Mode B is research/shadow only

    # ---- expiry-day vetoes ---------------------------------- EVIDENCE_VETO
    # Gap analysis: all five 180 s dips of -27% .. -93% were expiry-day contracts,
    # four of them at/after 15:15. HARD NO TRADE; do not remove without new evidence.
    expiry_close_veto_start: str = "15:15:00"
    # Expiry-day high-risk transition zone (research only, no entries, positions flat).
    # The brief named ~15:14-15:15; the 1-minute research (train+test, 13 expiry symbol-days)
    # shows the tail already widening from 15:10: ATM 3-min MAE median -9.7% / p10 -32%
    # vs -2.5% / -6.6% on non-expiry days. The zone therefore starts at 15:10 (more conservative).
    expiry_transition_zone_start: str = "15:10:00"
    expiry_forced_exit: str = "15:10:00"      # a Mode A position on expiry day never enters the zone

    # ---- event detection ----------------------------------- PROVISIONAL_5S
    bar_seconds: int = 5
    event_percentile: float = 95.0            # |30 s futures move| vs PRIOR days' distribution
    weak_percentile: float = 85.0             # near-miss band -> WEAK_MOMENTUM (recorded, rejected)
    continuation_percentile: float = 95.0     # |180 s futures move| for slow grinds
    continuation_consistency: float = 0.60    # share of 5 s steps in the event direction
    reversal_prior_min_multiple: float = 1.0  # prior 180 s move >= this x thr30, opposite sign
    min_history_days: int = 2                 # prior HR days needed for causal thresholds
    cooldown_seconds: int = 60                # one candidate per symbol per 60 s
    # EXECUTION REALISM: HR bars reach the DB ~3.3 s (median, max ~4.5 s) after the bar ends.
    # A live observer polling every 5 s sees bar i during bar i+1 at the earliest, so the first
    # quote that is guaranteed to exist AFTER detection is the close of bar i+2.
    entry_delay_bars: int = 2
    futures_stale_seconds: int = 30

    # ---- confirmation -------------------------------------- PROVISIONAL_5S
    min_option_response_pct: float = 1.0      # selected leg mid move in event direction over the trigger window
    persistence_window_bars: int = 3
    persistence_min_bars: int = 2             # >= 2 of last 3 futures steps in direction
    extension_multiple: float = 3.0           # 300 s move >= 3 x thr30 before a momentum event -> extended

    # ---- option selection ------------------------------------------ mixed
    atm_window_strikes: int = 5               # POLICY: candidate universe ATM +/- 5
    max_itm_steps: int = 2                    # RESEARCH_1MIN: ITM1-2 had the smallest MAE in train AND test
    max_otm_steps: int = 1                    # RESEARCH_1MIN: OTM2 worst exit/MAE in both periods (cheap != better)
    max_spread_pct: float = 1.0               # RESEARCH_1MIN: ATM/near spreads 0.15-0.45% in the window
    max_quote_age_s: float = 10.0             # PROVISIONAL_5S
    min_premium: float = 20.0                 # RESEARCH_1MIN: below this, tick size dominates the move
    max_premium: float = 600.0                # POLICY

    # ---- pre-entry risk ------------------------------------------- mixed
    starting_capital: float = 15_000.0        # POLICY (separate 12A account, never 11D's)
    max_rupee_loss_per_trade: float = 300.0   # POLICY: 2% of capital
    max_capital_per_trade: float = 6_000.0    # POLICY
    max_daily_loss: float = 900.0             # POLICY: 6% of capital
    max_trades_per_day: int = 6               # POLICY: across both symbols
    max_concurrent_positions: int = 1         # POLICY
    lot_size_units: int = 1                   # POLICY: same unit convention as 11D, not exchange lots
    # RESEARCH_1MIN risk RANGES, not an edge: the 1-minute target/stop/hold grid found NO
    # positive cell on the train days. Stop 5% ~ p10 of random 2-min MAE (-4.5..-6.2%);
    # target 5% ~ upper tail of 2-min MFE; hold 120 s because MAE deepens beyond 2 min for
    # events and random alike and median time-to-MFE was 2 min (1-min granularity).
    stop_pct: float = 5.0
    target_pct: float = 5.0
    max_hold_seconds: int = 120
    stop_spread_multiple: float = 3.0         # stop must clear 3 x entry spread

    # ---- proactive exits ----------------------------------- PROVISIONAL_5S
    no_progress_seconds: int = 30             # bid never above entry ask within 30 s -> momentum failure
    fade_activation_pct: float = 2.0          # after a >= 2% peak gain ...
    fade_giveback_frac: float = 0.5           # ... giving back 50% of it -> momentum fade
    trail_activation_pct: float = 3.0         # after +3%, stop tightens to lock ...
    trail_lock_frac: float = 0.4              # ... 40% of the peak gain (stops only tighten)
    event_retrace_frac: float = 0.6           # futures retrace 60% of the event displacement
    divergence_frac: float = 0.5              # futures +50% of displacement further while option below entry
    exit_spread_multiple: float = 2.5
    exit_spread_floor_pct: float = 1.5
    stale_quote_bars: int = 3

    # ---- counterfactual horizons ------------------------------ research
    horizons_seconds: tuple[int, ...] = (15, 30, 60, 120, 180, 300)

    symbols: tuple[str, ...] = ("NIFTY", "SENSEX")

    def config_hash(self) -> str:
        payload = {
            "strategy_version": STRATEGY_VERSION,
            "engine_version": ENGINE_VERSION,
            "config_version": CONFIG_VERSION,
            "config": asdict(self),
        }
        blob = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
        return hashlib.sha256(blob).hexdigest()[:16]


DEFAULT_CONFIG = ScalpConfig()
