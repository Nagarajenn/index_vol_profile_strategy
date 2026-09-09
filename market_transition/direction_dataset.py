"""Milestone 11A research dataset builder -- 2:59pm decision-side features
(<=14:59:00) and 3:00-3:15pm actual outcomes (>=15:00:00), kept as two
physically separate build functions so a stray column can't cross the
15:00 boundary by accident (mirrors the discipline already proven by
market_transition/cas_forecast.py's leakage-safe checkpoint clamp and
tests/test_cas_forecast_no_leakage.py's truncate-vs-extended check).

Reuses, unmodified:
  - analytics.vwap.compute_vwap / analytics.volume_profile.compute_volume_profile
    for the underlying half (same functions Milestone 10's scratchpad
    m10_underlying_features.py called).
  - option_chain.snapshot_features.compute_snapshot_features (Milestone 9)
    for the options half.

Nothing in this module touches the database -- callers (scripts/
run_milestone11a.py) supply already-fetched candles and an
`option_lookup_fn` (a thin wrapper the caller builds over
db.reader.get_option_chain_raw_near, whose own SQL already filters
`fetched_at::time <= at_or_before` -- leakage safety is enforced at the
query itself, not just in this module).
"""

from dataclasses import asdict
from datetime import date, time
from typing import Callable

import pandas as pd

from analytics.vwap import compute_vwap
from analytics.volume_profile import compute_volume_profile
from market_transition.expiry_calendar import ExpiryType
from option_chain.snapshot_features import OptionSnapshotFeatures, compute_snapshot_features

# The exact 8 checkpoints Milestone 10's scratchpad reconstruction used --
# carried forward unchanged, not redefined, per "do not change the
# underlying/option feature definitions."
CHECKPOINTS: list[time] = [
    time(14, 30), time(14, 40), time(14, 45), time(14, 50),
    time(14, 55), time(14, 57), time(14, 58), time(14, 59),
]
DECISION_CUTOFF = time(14, 59)

# The last-10-minute option trajectory (Task 6.4) -- captured for later
# incremental-feature work, NOT used by the frozen Milestone 11A baseline.
TRAJECTORY_MINUTES: list[time] = [time(14, m) for m in range(50, 60)]

TRAJECTORY_FIELDS = ("pcr_oi", "iv_skew", "atm_straddle_value", "call_put_volume_imbalance")

# Snapshot considered too stale to trust for a checkpoint if the nearest
# option_chain_raw row at/before that checkpoint is more than this many
# seconds earlier (mirrors Milestone 9's GOOD/DEGRADED read).
MAX_SNAPSHOT_AGE_SEC = 180

OptionLookupFn = Callable[[str], dict | None]
"""Given an 'HH:MM:SS' cutoff string, returns {'fetched_at','expiry','spot',
'raw_payload'} for the latest option_chain_raw row at/before that time (the
exact shape of db.reader.get_option_chain_raw_near's return value), or None
if nothing exists that early in the day."""


def _cp_key(t: time) -> str:
    return t.strftime("%H%M")


def _momentum(cum: pd.DataFrame, n: int) -> float | None:
    sub = cum.tail(n + 1)
    if len(sub) < 2:
        return None
    return float(sub["close"].iloc[-1] - sub["close"].iloc[0])


def build_underlying_checkpoint_features(day_candles: pd.DataFrame, bin_size: float) -> dict:
    """One flattened row of underlying features per checkpoint in
    CHECKPOINTS, keyed `under_{HHMM}_{field}`. `day_candles` may contain
    rows at or after 15:00 -- every checkpoint filters `day_candles` down
    to `time <= checkpoint` itself before computing anything, so passing a
    full day's candles (rather than a pre-truncated slice) cannot leak;
    this is asserted directly by
    tests/test_direction_dataset_no_leakage.py."""
    out: dict = {}
    if day_candles.empty:
        return out
    day_candles = day_candles.copy()
    day_candles["time"] = day_candles["timestamp"].dt.time

    vwap_series = compute_vwap(day_candles)

    for cp in CHECKPOINTS:
        key = _cp_key(cp)
        cum = day_candles[day_candles["time"] <= cp]
        if cum.empty:
            continue
        close = float(cum["close"].iloc[-1])
        session_high = float(cum["high"].max())
        session_low = float(cum["low"].min())
        vwap_now = float(vwap_series.loc[cum.index[-1]])

        vp = compute_volume_profile(cum, bin_size)
        poc = vp.poc if vp else None
        vah = vp.vah if vp else None
        val = vp.val if vp else None

        cutoff_15ago = (pd.Timestamp.combine(cum["timestamp"].iloc[-1].normalize(), cp) - pd.Timedelta(minutes=15)).time()
        cum_15ago = day_candles[day_candles["time"] <= cutoff_15ago]
        poc_15ago = None
        if len(cum_15ago) >= 5:
            vp_15 = compute_volume_profile(cum_15ago, bin_size)
            poc_15ago = vp_15.poc if vp_15 else None

        cum_vol = float(cum["volume"].sum())
        vol_last15 = float(cum.tail(15)["volume"].sum())
        vol_pct_last15 = (vol_last15 / cum_vol * 100) if cum_vol else None

        last15 = cum.tail(15)
        prior15 = cum.tail(30).head(15) if len(cum) >= 30 else pd.DataFrame()
        range_last15 = float(last15["high"].max() - last15["low"].min()) if len(last15) else None
        range_prior15 = float(prior15["high"].max() - prior15["low"].min()) if len(prior15) else None
        compression_ratio = (range_last15 / range_prior15) if (range_last15 and range_prior15) else None

        fields = dict(
            close=close,
            mom_1min=_momentum(cum, 1), mom_3min=_momentum(cum, 3), mom_5min=_momentum(cum, 5),
            mom_10min=_momentum(cum, 10), mom_15min=_momentum(cum, 15),
            dist_from_session_high=close - session_high, dist_from_session_low=close - session_low,
            vwap=vwap_now, dist_from_vwap=close - vwap_now, above_vwap=close > vwap_now,
            poc=poc, vah=vah, val=val,
            poc_migration_15min=(poc - poc_15ago) if (poc is not None and poc_15ago is not None) else None,
            price_vs_poc=(close - poc) if poc is not None else None,
            cum_volume=cum_vol, vol_pct_last15min=vol_pct_last15,
            range_last15=range_last15, range_prior15=range_prior15, compression_ratio=compression_ratio,
        )
        for f, v in fields.items():
            out[f"under_{key}_{f}"] = v
    return out


def build_option_checkpoint_features(session_date: date, option_lookup_fn: OptionLookupFn) -> dict:
    """One flattened row per checkpoint in CHECKPOINTS, keyed
    `opt_{HHMM}_{field}`, plus `opt_{HHMM}_available` / `opt_{HHMM}_stale`
    data-quality flags. `option_lookup_fn` is always called with a
    checkpoint time <= DECISION_CUTOFF -- CHECKPOINTS itself never contains
    a time later than 14:59, so this function cannot ask for post-cutoff
    option data even if it wanted to."""
    out: dict = {}
    prior: OptionSnapshotFeatures | None = None
    for cp in CHECKPOINTS:
        key = _cp_key(cp)
        row = option_lookup_fn(cp.strftime("%H:%M:%S"))
        if row is None or not row.get("raw_payload"):
            out[f"opt_{key}_available"] = False
            continue
        features = compute_snapshot_features(row["raw_payload"], prior=prior)
        if features is None:
            out[f"opt_{key}_available"] = False
            continue
        out[f"opt_{key}_available"] = True
        fetched_at = row.get("fetched_at")
        if fetched_at is not None:
            cp_dt = pd.Timestamp.combine(pd.Timestamp(session_date), cp).tz_localize(fetched_at.tzinfo or "Asia/Kolkata")
            age_sec = (cp_dt - fetched_at).total_seconds()
            out[f"opt_{key}_snapshot_age_sec"] = age_sec
            out[f"opt_{key}_stale"] = age_sec > MAX_SNAPSHOT_AGE_SEC
        for f, v in asdict(features).items():
            out[f"opt_{key}_{f}"] = v
        prior = features
    return out


def build_option_trajectory(option_lookup_fn: OptionLookupFn) -> dict:
    """Last-10-minute (14:50-14:59) 1-minute option trajectory, keyed
    `traj_{HHMM}_{field}`. Captured only for later incremental-feature
    work (Milestone 11B+) -- the frozen Milestone 11A baseline in
    market_transition/direction_baseline.py never reads a `traj_*` column."""
    out: dict = {}
    prior: OptionSnapshotFeatures | None = None
    for cp in TRAJECTORY_MINUTES:
        key = _cp_key(cp)
        row = option_lookup_fn(cp.strftime("%H:%M:%S"))
        if row is None or not row.get("raw_payload"):
            continue
        features = compute_snapshot_features(row["raw_payload"], prior=prior)
        if features is None:
            continue
        d = asdict(features)
        for f in TRAJECTORY_FIELDS:
            out[f"traj_{key}_{f}"] = d.get(f)
        prior = features
    return out


def build_decision_state(
    symbol: str, session_date: date, option_at_1459: dict | None, expiry_calendar: dict[date, ExpiryType] | None,
) -> dict:
    """Symbol/date identity plus expiry/day-of-week context, all derived
    from information available at or before 14:59 (the option row passed
    in must itself be the <=14:59 lookup -- callers pass the same row
    already fetched for the 14:59 checkpoint, no separate query)."""
    out: dict = dict(symbol=symbol, session_date=session_date, day_of_week=session_date.strftime("%A"))
    if expiry_calendar is not None:
        out["expiry_type"] = expiry_calendar.get(session_date)
    if option_at_1459 and option_at_1459.get("raw_payload"):
        payload = option_at_1459["raw_payload"]
        out["spot"] = payload.get("last_price")
        expiry = option_at_1459.get("expiry")
        out["expiry"] = expiry
        if expiry is not None:
            out["days_to_expiry"] = (expiry - session_date).days
        features = compute_snapshot_features(payload)
        if features is not None:
            out["atm_strike"] = features.atm_strike
    return out


def build_pre_cutoff_features(
    symbol: str, session_date: date, day_candles: pd.DataFrame, option_lookup_fn: OptionLookupFn,
    bin_size: float, expiry_calendar: dict[date, ExpiryType] | None = None,
) -> dict | None:
    """The full <=14:59 decision-side row: decision state + underlying
    checkpoints + option checkpoints + last-10-minute option trajectory.
    Returns None only when there is no underlying candle data at all for
    the day (mirrors this codebase's existing "no data -> None" convention,
    e.g. cas_forecast.build_transition_forecast)."""
    if day_candles.empty:
        return None
    option_at_1459 = option_lookup_fn(DECISION_CUTOFF.strftime("%H:%M:%S"))
    row: dict = {}
    row.update(build_decision_state(symbol, session_date, option_at_1459, expiry_calendar))
    row.update(build_underlying_checkpoint_features(day_candles, bin_size))
    row.update(build_option_checkpoint_features(session_date, option_lookup_fn))
    row.update(build_option_trajectory(option_lookup_fn))
    return row


ACTUAL_OUTCOME_FIELDS = ("direction", "point_move", "pct_move", "mfe", "mae")


def build_post_cutoff_outcomes(actual_outcome_by_horizon: dict[int, dict]) -> dict:
    """The full >=15:00 outcome row, keyed `actual_{h}m_{field}` (e.g.
    `actual_15m_direction`) -- deliberately never `direction_15m` (the
    pandas rsuffix-collision naming bug from Milestone 10's
    m10_core_analysis.py, which this explicit-prefix naming makes
    structurally impossible to repeat). Takes ONLY the already-fetched
    transition_actual_outcome rows -- no candle or option data at all, so
    this function has no path by which pre-cutoff data could leak in."""
    out: dict = {}
    for horizon, data in actual_outcome_by_horizon.items():
        for f in ACTUAL_OUTCOME_FIELDS:
            out[f"actual_{horizon}m_{f}"] = data.get(f)
    return out


def merge_pre_post(pre: dict, post: dict) -> dict:
    """Merge with a hard assertion that no key collides -- pre- and
    post-cutoff column namespaces (`under_`/`opt_`/`traj_`/decision-state
    keys vs. `actual_*`) are disjoint by construction; a collision would
    mean something is wrong with the naming scheme, not something to
    silently overwrite."""
    overlap = set(pre) & set(post)
    if overlap:
        raise ValueError(f"pre/post-cutoff column collision: {sorted(overlap)}")
    merged = dict(pre)
    merged.update(post)
    return merged


REQUIRED_BASELINE_FIELDS = ("opt_1459_pcr_oi", "opt_1459_call_put_volume_imbalance", "opt_1459_atm_straddle_change")


def is_baseline_usable(row: dict) -> bool:
    """True only when every field the frozen Model B baseline needs is
    present, non-null, AND fresh as of 14:59 (opt_1459_stale is not True).

    get_option_chain_raw_near falls back to the latest snapshot at/before
    14:59 no matter how much earlier in the day it is -- a day with no
    real 14:30-15:15 capture (a genuine gap, not a leakage risk since the
    stale row is still <=14:59) would otherwise silently score using,
    say, a 12:47pm option state relabeled as "opt_1459". Requiring
    freshness here is what actually implements "do not fabricate missing
    option data": a stale snapshot is treated as missing, not imputed."""
    if any(row.get(f) is None for f in REQUIRED_BASELINE_FIELDS):
        return False
    return row.get("opt_1459_stale") is not True
