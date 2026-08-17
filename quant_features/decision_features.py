"""Captures the EXISTING decision engine's own outputs (trend_classifier +
confidence_score, as run by analytics.levels.compute_levels) as features --
does not re-derive a competing composite. See structure_features.py for why
this module takes an already-computed LevelsResult rather than recomputing
classify_trend()/compute_confidence() itself.
"""

from analytics.levels import LevelsResult

from .models import DecisionFeatureSet


def compute_decision_feature_set(levels: LevelsResult) -> DecisionFeatureSet:
    sub = (levels.confidence.sub_scores if levels.confidence else {}) or {}

    return DecisionFeatureSet(
        trend_label=levels.trend.label if levels.trend else None,
        trend_score=levels.trend.score if levels.trend else None,
        confidence_score=levels.confidence.score if levels.confidence else None,
        sub_score_trend_alignment=sub.get("trend_alignment"),
        sub_score_vwap_position=sub.get("vwap_position"),
        sub_score_structure_hh_hl=sub.get("structure_hh_hl"),
        sub_score_trendline_confluence=sub.get("trendline_confluence"),
        sub_score_sr_proximity=sub.get("sr_proximity"),
        sub_score_breakout_confirmation=sub.get("breakout_confirmation"),
        sub_score_institutional_bias=sub.get("institutional_bias"),
        confidence_partial_data=levels.confidence.partial_data if levels.confidence else None,
    )
