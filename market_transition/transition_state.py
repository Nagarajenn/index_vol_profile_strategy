"""Unified 2:59pm market-state vector (Phase 9B, spec Part 7).

Pure synthesis over already-computed fields -- every categorical read
here comes straight off the 14:55-14:59 PreTransitionWindow (Phase 7B)
and, optionally, the option-positioning classification from
option_chain/snapshot_features.py (Phase 9A). No new statistics, no DB
access -- this module only labels and cross-references numbers that
already exist elsewhere, plus a small, explicit contradiction-detection
rule set (documented heuristics, not a claim of causal proof -- same
"associated with, not caused by" framing this whole engine uses
elsewhere).
"""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from market_transition.cas_windows import PreTransitionWindow

FLAT_PCT_THRESHOLD = 0.02  # matches cas_transition.py's own flat-move threshold, for consistency
OI_STRUCTURE_MIN_DELTA = 0.0  # any nonzero net skew is reported; the label itself carries the caveat


@dataclass
class MarketStateVector:
    price_bias: str
    volume_bias: str
    vwap_position: str
    poc_migration: str
    profile_acceptance: str
    option_bias: str
    pcr_trend: str
    oi_structure: str
    iv_trend: str
    regime: str
    news_bias: str
    contradictions: list[str] = field(default_factory=list)


def _price_bias(window: "PreTransitionWindow") -> str:
    if window.pct_change is None:
        return "Unknown"
    if window.pct_change >= FLAT_PCT_THRESHOLD:
        return "bullish"
    if window.pct_change <= -FLAT_PCT_THRESHOLD:
        return "bearish"
    return "flat"


def _volume_bias(window: "PreTransitionWindow") -> str:
    if window.dominant_side == "buy":
        return "Increasing buy pressure"
    if window.dominant_side == "sell":
        return "Increasing sell pressure"
    return "Balanced"


def _vwap_position(window: "PreTransitionWindow") -> str:
    if window.price_distance_from_vwap is None:
        return "Unknown"
    if window.price_distance_from_vwap > 0:
        return "Above VWAP"
    if window.price_distance_from_vwap < 0:
        return "Below VWAP"
    return "At VWAP"


def _poc_migration(window: "PreTransitionWindow") -> str:
    slope = window.poc_slope if window.poc_slope is not None else window.poc_change_during_window
    if slope is None:
        return "Unknown"
    if slope > 0:
        return "Migrating higher"
    if slope < 0:
        return "Migrating lower"
    return "Stable"


def _profile_acceptance(window: "PreTransitionWindow") -> str:
    if window.close is None or window.vah is None or window.val is None:
        return "Unknown"
    if window.close > window.vah:
        return "Acceptance above VAH"
    if window.close < window.val:
        return "Acceptance below VAL"
    return "Within value area"


def _pcr_trend(window: "PreTransitionWindow") -> str:
    if window.pcr_change is None:
        return "Unknown"
    if window.pcr_change > 0:
        return "Rising"
    if window.pcr_change < 0:
        return "Falling"
    return "Flat"


def _oi_structure(window: "PreTransitionWindow") -> str:
    if window.call_oi_change is None or window.put_oi_change is None:
        return "Unknown"
    if window.call_oi_change > window.put_oi_change:
        return "Call-side concentration increasing"
    if window.put_oi_change > window.call_oi_change:
        return "Put-side concentration increasing"
    return "Balanced"


def _iv_trend(window: "PreTransitionWindow") -> str:
    if window.iv_change is None:
        return "Unknown"
    if window.iv_change > 0:
        return "Increasing"
    if window.iv_change < 0:
        return "Decreasing"
    return "Stable"


def _news_bias(window: "PreTransitionWindow") -> str:
    if window.news_risk_score is None:
        return "Neutral"
    if window.news_risk_score >= 60:
        return "Elevated risk"
    if window.news_risk_score >= 30:
        return "Mild risk"
    return "Neutral"


def _detect_contradictions(
    price_bias: str, oi_structure: str, option_bias: str | None,
) -> list[str]:
    """Deterministic, documented heuristic rules -- flags evidence that
    points the opposite way from the price-direction read, per spec Part
    7's exact example ("Bearish price BUT Put OI increasing strongly").
    Never claims which signal is "right", only that they disagree."""
    contradictions: list[str] = []

    if price_bias == "bearish" and oi_structure == "Put-side concentration increasing":
        contradictions.append("Bearish price but Put OI concentration is increasing")
    elif price_bias == "bullish" and oi_structure == "Call-side concentration increasing":
        contradictions.append("Bullish price but Call OI concentration is increasing")

    if option_bias is not None:
        if price_bias == "bearish" and option_bias == "BULLISH":
            contradictions.append("Bearish price vs. bullish option positioning")
        elif price_bias == "bullish" and option_bias == "BEARISH":
            contradictions.append("Bullish price vs. bearish option positioning")

    return contradictions


def build_market_state_vector(
    final_pre_window: "PreTransitionWindow", option_bias: str | None = None,
) -> MarketStateVector:
    """`final_pre_window` is the 14:55-14:59 PreTransitionWindow -- the
    richest single snapshot of "what's known by 2:59pm". `option_bias` is
    the BULLISH/BEARISH/NEUTRAL/MIXED/RAPIDLY_CHANGING classification from
    option_chain.snapshot_features.classify_option_positioning, computed
    by the caller from a fresh at-or-before-14:59 option chain read (not
    tied to the 8 fixed daily checkpoints, which don't include 14:59
    itself) -- optional, since it's None whenever option data isn't
    available for that day."""
    price_bias = _price_bias(final_pre_window)
    oi_structure = _oi_structure(final_pre_window)

    return MarketStateVector(
        price_bias=price_bias,
        volume_bias=_volume_bias(final_pre_window),
        vwap_position=_vwap_position(final_pre_window),
        poc_migration=_poc_migration(final_pre_window),
        profile_acceptance=_profile_acceptance(final_pre_window),
        option_bias=option_bias or "N/A",
        pcr_trend=_pcr_trend(final_pre_window),
        oi_structure=oi_structure,
        iv_trend=_iv_trend(final_pre_window),
        regime=final_pre_window.market_regime or "Unknown",
        news_bias=_news_bias(final_pre_window),
        contradictions=_detect_contradictions(price_bias, oi_structure, option_bias),
    )
