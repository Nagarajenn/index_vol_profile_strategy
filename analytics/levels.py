import json
from dataclasses import dataclass, field
from datetime import datetime

import pandas as pd

from analytics.breakout_boxes import BreakoutBox, detect_breakout_boxes
from analytics.confidence_score import ConfidenceResult, compute_confidence
from analytics.institutional_bias import InstitutionalBiasResult, classify_institutional_bias
from analytics.resample import resample_series_last, resample_to_interval
from analytics.support_resistance import Zone, build_candidates, cluster_zones, nearest_support_resistance
from analytics.swings import SwingPoint, detect_swings
from analytics.trend_classifier import TrendResult, classify_trend
from analytics.trendlines import Trendline, fit_trendlines
from analytics.volume_profile import VolumeProfileResult, compute_volume_profile
from analytics.vwap import compute_vwap
from config.settings import PROJECT_ROOT
from option_chain.summary import OptionChainSummary

with open(PROJECT_ROOT / "config" / "scoring_weights.json") as _f:
    DEFAULT_SCORING_WEIGHTS = json.load(_f)


@dataclass
class LevelsResult:
    symbol: str
    as_of: datetime
    close: float
    vwap_now: float | None
    candles_5min: pd.DataFrame
    vwap_5min: pd.Series
    today_vp: VolumeProfileResult | None
    yesterday_vp: VolumeProfileResult | None
    swings: list[SwingPoint] = field(default_factory=list)
    trendlines: list[Trendline] = field(default_factory=list)
    support: Zone | None = None
    resistance: Zone | None = None
    breakout_boxes: list[BreakoutBox] = field(default_factory=list)
    trend: TrendResult | None = None
    institutional_bias: InstitutionalBiasResult | None = None
    confidence: ConfidenceResult | None = None


def compute_levels(
    symbol: str,
    day_candles_1min: pd.DataFrame,
    instrument_meta: dict,
    prior_day_candles_1min: pd.DataFrame | None = None,
    prior_day_ohlc: dict | None = None,
    option_summary: OptionChainSummary | None = None,
    scoring_weights: dict | None = None,
) -> LevelsResult:
    """Run the full M2-M5 analytics stack on one day's developing 1-min
    candles (already truncated to the desired "as of" cutoff by the caller)
    and return every computed level in one object.
    """
    bin_size = instrument_meta["volume_profile_bin_size"]

    vwap_1min = compute_vwap(day_candles_1min)
    today_vp = compute_volume_profile(day_candles_1min, bin_size)
    candles_5min = resample_to_interval(day_candles_1min, 5)
    vwap_5min = resample_series_last(vwap_1min, day_candles_1min["timestamp"], 5)

    yesterday_vp = None
    if prior_day_candles_1min is not None and not prior_day_candles_1min.empty:
        yesterday_vp = compute_volume_profile(prior_day_candles_1min, bin_size)

    close = float(day_candles_1min["close"].iloc[-1])
    vwap_now = float(vwap_1min.iloc[-1]) if len(vwap_1min) else None
    as_of = day_candles_1min["timestamp"].iloc[-1].to_pydatetime()

    swings = detect_swings(candles_5min)
    trendlines = fit_trendlines(swings, candles_5min)
    boxes = detect_breakout_boxes(candles_5min)

    confirmed_swings = [s for s in swings if s.confirmed]
    candidates = build_candidates(
        current_price=close,
        round_number_step=instrument_meta["round_number_step"],
        prior_day_high=prior_day_ohlc.get("high") if prior_day_ohlc else None,
        prior_day_low=prior_day_ohlc.get("low") if prior_day_ohlc else None,
        prior_day_close=prior_day_ohlc.get("close") if prior_day_ohlc else None,
        today_vp=today_vp,
        yesterday_vp=yesterday_vp,
        confirmed_swings=confirmed_swings,
    )
    zones = cluster_zones(candidates, instrument_meta["sr_cluster_tolerance_pct"])
    support, resistance = nearest_support_resistance(zones, close)

    trend = classify_trend(candles_5min, vwap_now, swings)
    bias = classify_institutional_bias(option_summary, close)
    confidence = compute_confidence(
        trend=trend,
        vwap_now=vwap_now,
        close=close,
        trendlines=trendlines,
        support=support,
        resistance=resistance,
        breakout_boxes=boxes,
        institutional_bias=bias,
        weights=scoring_weights or DEFAULT_SCORING_WEIGHTS,
    )

    return LevelsResult(
        symbol=symbol,
        as_of=as_of,
        close=close,
        vwap_now=vwap_now,
        candles_5min=candles_5min,
        vwap_5min=vwap_5min,
        today_vp=today_vp,
        yesterday_vp=yesterday_vp,
        swings=swings,
        trendlines=trendlines,
        support=support,
        resistance=resistance,
        breakout_boxes=boxes,
        trend=trend,
        institutional_bias=bias,
        confidence=confidence,
    )
