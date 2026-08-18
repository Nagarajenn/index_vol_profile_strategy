"""Top-level orchestrator -- the only module callers (batch backfill, the
live loop, tests) should import from. Three public entry points, mirroring
analytics.volume_intelligence.engine.compute_volume_intelligence's "single
public entry point per concern" shape:

- compute_market_features_row: everything backfillable over the full price
  history (~4 months as of this milestone) -- wraps VWAP, Volume Profile
  Intelligence, the Volume Intelligence Engine, the existing trend/
  confidence decision engine (via a single analytics.levels.compute_levels
  call), market regime, expiry calendar, and news.
- compute_option_features_row: option-chain-derived features, only
  backfillable over the much shorter live-pipeline era (~1 month).
- compute_forward_outcomes_row: the strict future-only labeling pass, run
  later once enough future candles actually exist for a given minute.

None of these compute anything themselves beyond simple composition --
every actual formula lives in, and is credited to, the module that owns it.
"""

from datetime import date, datetime

import pandas as pd

from analytics.levels import compute_levels
from analytics.vwap import compute_vwap
from market_intelligence.models import ClassifiedEvent
from market_transition.expiry_calendar import ExpiryType
from option_chain.summary import OptionChainSummary

from .decision_features import compute_decision_feature_set
from .expiry_features import compute_expiry_feature_set
from .labeling import compute_forward_outcome_row
from .models import DataQualityFlags, ForwardOutcomeRow, MarketFeatureRow, OptionFeatureRow
from .news_features import compute_news_feature_set
from .option_features import DEFAULT_LADDER_WIDTH, compute_option_feature_row
from .price_features import compute_price_volatility_features
from .regime_features import compute_regime_feature_set
from .structure_features import compute_structure_feature_set
from .versioning import FEATURE_VERSION
from .volume_intelligence_features import compute_volume_intelligence_feature_set
from .volume_profile_features import compute_volume_profile_feature_set
from .vwap_features import compute_vwap_features

# Below this many candles so far this session, rolling-window features
# (realized_vol_20m, RVOL baselines, etc.) are still filling in -- flagged,
# not withheld; every sub-module already degrades to None gracefully on its
# own, this is just a single, row-level "read the numbers with more caution"
# signal for a consumer that doesn't want to inspect every sub-field.
WARMUP_MIN_CANDLES = 20


def compute_market_features_row(
    symbol: str,
    today_candles: pd.DataFrame,
    historical_by_date: dict[date, pd.DataFrame],
    instrument_meta: dict,
    prior_day_candles_1min: pd.DataFrame | None = None,
    prior_day_ohlc: dict | None = None,
    prior_day_close: float | None = None,
    option_summary: OptionChainSummary | None = None,
    scoring_weights: dict | None = None,
    expiry_calendar: dict[date, ExpiryType] | None = None,
    news_events: list[ClassifiedEvent] | None = None,
    feature_version: str = FEATURE_VERSION,
) -> MarketFeatureRow:
    """`today_candles` must already be truncated to the desired cutoff T
    (see quant_features.cutoff.truncate_candles) and must be non-empty;
    `historical_by_date` must already be filtered to strictly-prior trading
    days (see quant_features.cutoff.historical_by_date_before).

    Calls analytics.levels.compute_levels() once and extracts structure/
    decision features from its result, so this row can never drift from
    what the live decision engine actually computed for the same inputs.
    """
    close = float(today_candles["close"].iloc[-1])
    as_of = today_candles["timestamp"].iloc[-1]
    as_of = as_of.to_pydatetime() if hasattr(as_of, "to_pydatetime") else as_of
    session_date = as_of.date()

    levels = compute_levels(
        symbol=symbol,
        day_candles_1min=today_candles,
        instrument_meta=instrument_meta,
        prior_day_candles_1min=prior_day_candles_1min,
        prior_day_ohlc=prior_day_ohlc,
        option_summary=option_summary,
        scoring_weights=scoring_weights,
    )

    price = compute_price_volatility_features(today_candles, prior_day_close)
    vwap_series = compute_vwap(today_candles)
    vwap = compute_vwap_features(vwap_series, close, price.atr_14)

    volume_profile = compute_volume_profile_feature_set(
        today_candles, historical_by_date, instrument_meta["volume_profile_bin_size"], close
    )
    volume_intelligence = compute_volume_intelligence_feature_set(symbol, today_candles, historical_by_date, expiry_calendar)

    structure = compute_structure_feature_set(levels)
    decision = compute_decision_feature_set(levels)
    regime = compute_regime_feature_set(today_candles, historical_by_date, levels.trend)
    expiry = compute_expiry_feature_set(symbol, session_date, today_candles, expiry_calendar)
    news = compute_news_feature_set(symbol, news_events or [], as_of)

    data_quality = DataQualityFlags()
    if len(today_candles) < WARMUP_MIN_CANDLES:
        data_quality.warmup_incomplete = True
        data_quality.notes.append(f"only {len(today_candles)} candle(s) so far this session")
    if not historical_by_date:
        data_quality.baseline_thin = True
        data_quality.notes.append("no historical trading days supplied -- baseline-dependent features unavailable")
    if option_summary is None:
        data_quality.option_data_unavailable = True
    if not news_events:
        data_quality.news_data_unavailable = True

    return MarketFeatureRow(
        symbol=symbol,
        timestamp=as_of,
        feature_version=feature_version,
        price=price,
        vwap=vwap,
        volume_profile=volume_profile,
        volume_intelligence=volume_intelligence,
        structure=structure,
        decision=decision,
        regime=regime,
        expiry=expiry,
        news=news,
        data_quality=data_quality,
    )


def compute_option_features_row(
    symbol: str,
    timestamp: datetime,
    current_chain: dict | None,
    previous_chain: dict | None,
    atm_window_strikes: int,
    ladder_width: int = DEFAULT_LADDER_WIDTH,
    feature_version: str = FEATURE_VERSION,
) -> OptionFeatureRow:
    """`current_chain`/`previous_chain` are option_chain_raw.raw_payload
    dicts (None if no snapshot exists at/before `timestamp`) -- see
    option_features.py for the full contract."""
    return compute_option_feature_row(
        symbol, timestamp, feature_version, current_chain, previous_chain, atm_window_strikes, ladder_width
    )


def compute_forward_outcomes_row(
    symbol: str,
    timestamp: datetime,
    today_candles: pd.DataFrame,
    t_index: int,
    atr_at_t: float | None,
    feature_version: str = FEATURE_VERSION,
) -> ForwardOutcomeRow:
    """Run this LATER than compute_market_features_row for the same
    (symbol, timestamp) -- only once enough future candles genuinely exist
    (see labeling.py). `atr_at_t` should be the atr_14 value already
    computed and stored for this row by compute_market_features_row, not
    recomputed here."""
    return compute_forward_outcome_row(symbol, timestamp, feature_version, today_candles, t_index, atr_at_t)
