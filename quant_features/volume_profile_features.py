"""Flattens analytics.volume_profile_intelligence.compute_volume_profile_intelligence
(called unmodified) into a single feature row. Reuses its `developing` list's
final entry for today's POC/VAH/VAL rather than calling
analytics.volume_profile.compute_volume_profile a second time --
compute_developing_levels() always appends a final full-session-so-far point
equal to what a direct call would produce.
"""

from datetime import date

import pandas as pd

from analytics.volume_profile_intelligence import compute_volume_profile_intelligence

from .models import VolumeProfileFeatureSet


def compute_volume_profile_feature_set(
    today_candles: pd.DataFrame,
    historical_by_date: dict[date, pd.DataFrame],
    bin_size: float,
    close: float,
) -> VolumeProfileFeatureSet:
    """`today_candles` must already be truncated to T; `historical_by_date`
    must already be filtered to strictly-prior trading days (see
    quant_features.cutoff)."""
    vpi = compute_volume_profile_intelligence(today_candles, historical_by_date, bin_size)

    today_poc = today_vah = today_val = poc_migration_intraday = None
    if vpi.developing:
        last_point = vpi.developing[-1]
        today_poc, today_vah, today_val = last_point.poc, last_point.vah, last_point.val
        if len(vpi.developing) >= 2:
            poc_migration_intraday = vpi.developing[-1].poc - vpi.developing[0].poc

    poc_distance_pct = (close - today_poc) / today_poc if today_poc else None

    is_inside_initial_balance = None
    if vpi.initial_balance is not None:
        is_inside_initial_balance = bool(vpi.initial_balance.ib_low <= close <= vpi.initial_balance.ib_high)

    return VolumeProfileFeatureSet(
        today_poc=today_poc,
        today_vah=today_vah,
        today_val=today_val,
        poc_distance_pct=poc_distance_pct,
        profile_shape=vpi.profile_shape.shape if vpi.profile_shape else None,
        opening_type=vpi.opening_type.type if vpi.opening_type else None,
        rotation_label=vpi.rotation_factor.label if vpi.rotation_factor else None,
        volume_pace_pct=vpi.volume_pace.pace_pct if vpi.volume_pace else None,
        is_inside_initial_balance=is_inside_initial_balance,
        poc_migration_intraday=poc_migration_intraday,
    )
