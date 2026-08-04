"""Top-level orchestrator: compute_volume_intelligence() ties every module
in this package together into one VolumeIntelligence snapshot, computed
fresh on every call -- no caching, no DB writes, mirrors
analytics/volume_profile_intelligence.py's compute_volume_profile_intelligence()
shape (minus bin_size -- this package has no price-binning concept).
"""

from datetime import date

import pandas as pd

from market_transition.expiry_calendar import ExpiryType

from .baselines import compute_all_baseline_readings
from .character import classify_volume_character, compute_volume_trend
from .forecast import compute_next_interval_forecast
from .institutional import compute_institutional_participation
from .models import VolumeIntelligence
from .narrative import build_narrative
from .patterns import compute_absorption, compute_exhaustion
from .pressure import compute_buy_sell_dominance, compute_cumulative_pressure, compute_volume_momentum
from .proxy import attach_buy_sell_columns
from .rvol import compute_rvol, compute_volume_acceleration, compute_volume_dryup, compute_volume_spike
from .similarity import compute_historical_similarity


def compute_volume_intelligence(
    symbol: str,
    today_candles: pd.DataFrame,
    historical_by_date: dict[date, pd.DataFrame],
    expiry_calendar: dict[date, ExpiryType] | None = None,
) -> VolumeIntelligence:
    """`today_candles` is today's session-so-far 1-min OHLCV.
    `historical_by_date` is prior trading days' full 1-min OHLCV, keyed by
    date (ideally covering ~60 trading days so the last_20_days/
    monthly_expiry_day baselines have enough sample size -- see
    backend/app/services/volume_intelligence_service.py's
    HISTORY_LOOKBACK_DAYS). Every downstream module degrades gracefully on
    thin/missing data (returns None or a safe-default label) rather than
    raising, so this never needs its own try/except scaffolding.
    """
    if today_candles.empty:
        return VolumeIntelligence(symbol=symbol, as_of=None)

    enriched = attach_buy_sell_columns(today_candles)
    today_date = enriched["timestamp"].iloc[-1].date()
    elapsed_minutes = float((enriched["timestamp"].iloc[-1] - enriched["timestamp"].iloc[0]).total_seconds() / 60)

    baseline_readings = compute_all_baseline_readings(symbol, today_date, historical_by_date, elapsed_minutes, expiry_calendar)
    baseline_20d = baseline_readings.get("last_20_days")

    rvol = compute_rvol(enriched, baseline_readings)
    acceleration = compute_volume_acceleration(enriched)
    spike = compute_volume_spike(enriched, baseline_20d)
    dryup = compute_volume_dryup(enriched, baseline_20d)

    dominance = compute_buy_sell_dominance(enriched)
    cumulative_pressure = compute_cumulative_pressure(enriched)
    momentum = compute_volume_momentum(enriched)

    institutional = compute_institutional_participation(rvol, dominance, enriched)

    absorption = compute_absorption(enriched, spike)
    exhaustion = compute_exhaustion(enriched, spike)

    trend = compute_volume_trend(enriched)
    character = classify_volume_character(enriched, trend, dominance, absorption, exhaustion)

    similarity = compute_historical_similarity(enriched, historical_by_date, baseline_20d)

    forecast = compute_next_interval_forecast(trend, momentum, character, institutional, similarity, enriched)

    narrative = build_narrative(
        rvol, dominance, trend, character, spike, dryup, absorption, exhaustion, institutional, similarity, forecast, enriched
    )

    return VolumeIntelligence(
        symbol=symbol,
        as_of=enriched["timestamp"].iloc[-1].to_pydatetime(),
        rvol=rvol,
        acceleration=acceleration,
        dominance=dominance,
        cumulative_pressure=cumulative_pressure,
        momentum=momentum,
        institutional=institutional,
        spike=spike,
        dryup=dryup,
        absorption=absorption,
        exhaustion=exhaustion,
        trend=trend,
        character=character,
        similarity=similarity,
        forecast=forecast,
        narrative=narrative,
    )
