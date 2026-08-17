"""Pure dataclasses for the Quant Feature Store & Forward Outcome Engine. No
DB/pipeline/network dependency -- mirrors market_transition/models.py's and
analytics/volume_intelligence/models.py's "define the entire output
vocabulary as dataclasses + Literal types up front" pattern.

This package does not redesign or duplicate any existing analytics module
(Volume Profile Intelligence, VWAP, Volume Intelligence, Option Chain
Intelligence, Market Intelligence, Market Transition Intelligence, the
trend/confidence decision engine). It wraps and flattens their existing
outputs into versioned, leakage-safe rows suitable for backtesting/
threshold-tuning/a future ML step. See quant_features/cutoff.py for the
mechanical "never look past T" guard every feature function relies on.
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Literal

# Reused labels/types from existing modules are re-declared here (not
# imported) only where a Literal is needed for this package's own dataclass
# fields -- the actual classification logic still lives in, and is called
# from, the original module.
MarketRegime3Way = Literal["Trending", "Range-Bound", "Volatile"]  # market_transition.market_regime, reused as-is

# NEW derived taxonomy -- no 13-category regime classifier exists anywhere
# else in this codebase today. Built from the same primitives market_regime
# already exposes (compute_volatility_pace_pct, compute_rotation_factor) plus
# trend_classifier's direction/structure votes -- see regime_features.py.
MarketRegimeExpanded = Literal[
    "Strong Uptrend",
    "Uptrend",
    "Weak Uptrend",
    "Strong Downtrend",
    "Downtrend",
    "Weak Downtrend",
    "Range-Bound",
    "Breakout-Up",
    "Breakout-Down",
    "High-Volatility Choppy",
    "Low-Volatility Quiet",
    "Reversal-Up",
    "Reversal-Down",
]

DirectionLabel = Literal["Up", "Down", "Flat"]
ExpiryType = Literal["weekly", "monthly"]  # market_transition.expiry_calendar, reused as-is
DominantSide = Literal["buy", "sell", "balanced"]  # analytics.volume_intelligence, reused as-is
ProfileShape = Literal["P", "b", "D", "B"]  # analytics.volume_profile_intelligence, reused as-is
RotationLabel = Literal["Trending", "Rotational"]  # analytics.volume_profile_intelligence, reused as-is
Moneyness = Literal["ITM", "ATM", "OTM"]
OptionType = Literal["CE", "PE"]
RunType = Literal["batch_backfill", "live_incremental", "labeling"]
RunStatus = Literal["running", "completed", "failed"]


@dataclass
class DataQualityFlags:
    """Which sub-computations were unavailable/degraded for this row, and
    why -- a row is never silently null with no explanation. Mirrors the
    "honestly return empty/None on thin data" philosophy already used
    throughout VIE/MTI, made explicit and machine-readable here since a
    feature-store consumer (unlike a live dashboard reader) needs to filter
    rows programmatically, not just read a caveat in prose."""

    warmup_incomplete: bool = False  # fewer candles than some rolling window needs
    baseline_thin: bool = False  # a volume/regime historical baseline had too few sample days
    option_data_unavailable: bool = False  # no option_chain_raw snapshot at/before this timestamp
    news_data_unavailable: bool = False
    notes: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# quant_market_features sub-groups
# ---------------------------------------------------------------------------
@dataclass
class PriceVolatilityFeatures:
    close: float
    ret_1m: float | None
    ret_5m: float | None
    realized_vol_20m: float | None  # stdev of trailing-20m 1-min returns (not annualized -- an intraday tool)
    atr_14: float | None  # analytics.breakout_boxes.compute_atr, reused
    gap_open_pct: float | None  # today's session open vs prior day's close
    body_pct: float | None  # |close-open| / (high-low) of the current 1-min candle, None if high==low
    upper_wick_pct: float | None
    lower_wick_pct: float | None


@dataclass
class VwapFeatures:
    vwap_now: float | None  # analytics.vwap.compute_vwap, reused
    vwap_distance_pct: float | None
    vwap_distance_atr: float | None  # distance normalized by atr_14
    vwap_slope_5m: float | None


@dataclass
class VolumeProfileFeatureSet:
    """Flattened from analytics.volume_profile.compute_volume_profile +
    analytics.volume_profile_intelligence.compute_volume_profile_intelligence,
    both called unmodified."""

    today_poc: float | None
    today_vah: float | None
    today_val: float | None
    poc_distance_pct: float | None
    profile_shape: ProfileShape | None
    opening_type: str | None
    rotation_label: RotationLabel | None
    volume_pace_pct: float | None
    is_inside_initial_balance: bool | None
    poc_migration_intraday: float | None  # developing[-1].poc - developing[0].poc


@dataclass
class VolumeIntelligenceFeatureSet:
    """Flattened from analytics.volume_intelligence.engine.compute_volume_intelligence,
    called unmodified -- see quant_features/volume_intelligence_features.py."""

    rvol_interval_pct: float | None
    rvol_cumulative_pct: float | None
    rvol_label: str | None
    volume_acceleration_label: str | None
    dominance_ratio: float | None
    dominant_side: DominantSide | None
    consecutive_dominant_minutes: int | None
    cumulative_pressure_ratio: float | None
    momentum_score: float | None
    momentum_label: str | None
    institutional_participation_score: int | None
    institutional_participation_label: str | None
    is_volume_spike: bool | None
    is_volume_dryup: bool | None
    is_absorption: bool | None
    is_exhaustion: bool | None
    volume_trend_label: str | None
    volume_character_label: str | None
    historical_similarity_top1_score: float | None
    forecast_probability_continuation: float | None
    forecast_confidence: str | None


@dataclass
class StructureFeatureSet:
    """From swings.detect_swings / trendlines.fit_trendlines /
    support_resistance.* / breakout_boxes.detect_breakout_boxes, all reused
    unmodified on the same 5-min-resampled candles analytics/levels.py
    already uses them on."""

    support_low: float | None
    support_high: float | None
    resistance_low: float | None
    resistance_high: float | None
    support_distance_pct: float | None
    resistance_distance_pct: float | None
    nearest_trendline_touch_count: int | None
    nearest_trendline_direction: Literal["up", "down"] | None
    breakout_box_status: str | None
    swing_structure_score: int | None  # trend_classifier.TrendResult.structure


@dataclass
class DecisionFeatureSet:
    """Captures the EXISTING decision engine's own outputs (trend_classifier
    + confidence_score, called with the same inputs analytics/levels.py
    already uses) as features -- does not re-derive a competing composite."""

    trend_label: str | None
    trend_score: int | None
    confidence_score: int | None
    sub_score_trend_alignment: float | None
    sub_score_vwap_position: float | None
    sub_score_structure_hh_hl: float | None
    sub_score_trendline_confluence: float | None
    sub_score_sr_proximity: float | None
    sub_score_breakout_confirmation: float | None
    sub_score_institutional_bias: float | None
    confidence_partial_data: bool | None


@dataclass
class RegimeFeatureSet:
    market_regime_3way: MarketRegime3Way | None  # market_transition.market_regime.classify_market_regime, reused
    market_regime_expanded: MarketRegimeExpanded | None  # new, derived -- see note on MarketRegimeExpanded above
    volatility_pace_pct: float | None  # market_transition.market_regime.compute_volatility_pace_pct, reused


@dataclass
class ExpiryFeatureSet:
    """From market_transition.expiry_calendar.classify_expiry_day, reused
    unmodified."""

    expiry_type: ExpiryType | None
    is_expiry_day: bool
    days_to_weekly_expiry: int | None
    days_to_monthly_expiry: int | None
    day_of_week: int  # 0=Monday .. 4=Friday
    minutes_since_open: int


@dataclass
class NewsFeatureSet:
    """From classified_events, gated strictly on classified_at <= timestamp
    -- never published_at (see quant_features/news_features.py)."""

    event_count_30m: int
    max_severity_30m: int | None
    dominant_sentiment_30m: str | None
    most_recent_event_direction: str | None
    most_recent_event_risk_level: str | None


@dataclass
class MarketFeatureRow:
    """One row of quant_market_features: everything computable from candles
    + existing analytics at (symbol, timestamp, feature_version). Covers the
    full price-history window (~4 months as of this milestone), unlike
    OptionFeatureRow."""

    symbol: str
    timestamp: datetime
    feature_version: str
    price: PriceVolatilityFeatures
    vwap: VwapFeatures
    volume_profile: VolumeProfileFeatureSet
    volume_intelligence: VolumeIntelligenceFeatureSet
    structure: StructureFeatureSet
    decision: DecisionFeatureSet
    regime: RegimeFeatureSet
    expiry: ExpiryFeatureSet
    news: NewsFeatureSet
    data_quality: DataQualityFlags = field(default_factory=DataQualityFlags)


# ---------------------------------------------------------------------------
# quant_option_features
# ---------------------------------------------------------------------------
@dataclass
class StrikeLadderEntry:
    """One strike/side of the ATM+/-3 ladder, parsed directly from
    option_chain_raw.raw_payload -- no existing function surfaces per-strike
    volume/iv/delta/ltp today, this is new parsing (see option_features.py)."""

    strike: float
    option_type: OptionType
    moneyness: Moneyness
    oi: float | None
    oi_delta_intraday: float | None
    volume: float | None
    iv: float | None
    ltp: float | None
    delta: float | None


@dataclass
class OptionFeatureRow:
    """One row of quant_option_features. Only computable while
    option_chain_raw has a snapshot at/before `timestamp` -- roughly the
    live-pipeline era (~1 month as of this milestone), NOT the full
    ~4-month price-history window MarketFeatureRow covers. `atm_strike`/
    `selected_ce_security_id`/`selected_pe_security_id` are recorded AS OF
    T (anti-survivorship-bias: never re-selected using information only
    known later)."""

    symbol: str
    timestamp: datetime
    feature_version: str
    expiry: date | None
    spot: float | None
    atm_strike: float | None
    pcr: float | None
    atm_iv_call: float | None
    atm_iv_put: float | None
    atm_iv_skew: float | None  # atm_iv_call - atm_iv_put
    call_oi_wall_strike: float | None
    put_oi_wall_strike: float | None
    call_oi_delta_intraday: float | None  # NEW: vs the immediately-prior option_chain_raw snapshot, not vs yesterday's close
    put_oi_delta_intraday: float | None
    strike_ladder: list[StrikeLadderEntry] = field(default_factory=list)
    data_quality: DataQualityFlags = field(default_factory=DataQualityFlags)


# ---------------------------------------------------------------------------
# quant_forward_outcomes
# ---------------------------------------------------------------------------
@dataclass
class ForwardOutcomeRow:
    """One row of quant_forward_outcomes -- computed STRICTLY from candles
    strictly after `timestamp` (indices > t_index, never <=). Horizons that
    would cross the session close are left None, never filled from the next
    day's open -- see labeling.py."""

    symbol: str
    timestamp: datetime
    feature_version: str
    atr_at_t: float | None  # the normalizer used for the volatility-adjusted labels, stored for reproducibility
    fwd_return_1m: float | None
    fwd_return_3m: float | None
    fwd_return_5m: float | None
    fwd_return_10m: float | None
    fwd_return_15m: float | None
    fwd_return_30m: float | None
    mfe_1m: float | None
    mae_1m: float | None
    mfe_5m: float | None
    mae_5m: float | None
    mfe_15m: float | None
    mae_15m: float | None
    mfe_30m: float | None
    mae_30m: float | None
    label_5m: DirectionLabel | None
    label_15m: DirectionLabel | None
    label_30m: DirectionLabel | None
    horizon_truncated_by_session_close: bool = False


@dataclass
class FeatureRunSummary:
    """Mirrors into quant_feature_runs -- the concrete implementation of
    feature versioning / run provenance."""

    run_type: RunType
    feature_version: str
    symbol: str
    start_date: date | None
    end_date: date | None
    rows_written: int
    started_at: datetime
    finished_at: datetime | None
    status: RunStatus
    error_message: str | None = None
