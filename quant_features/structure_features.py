"""Structural features (support/resistance, trendlines, breakout boxes,
swing structure) extracted from an already-computed analytics.levels.LevelsResult
-- not recomputed here. analytics.levels.compute_levels() already runs
swings.detect_swings -> trendlines.fit_trendlines -> support_resistance.* ->
breakout_boxes.detect_breakout_boxes in exactly this order (mirroring the
live decision engine's own composition); calling it once per row and
extracting from its result guarantees this module can never drift from what
the live engine actually computed, and avoids reimplementing that
orchestration a second time.
"""

from analytics.levels import LevelsResult

from .models import StructureFeatureSet


def compute_structure_feature_set(levels: LevelsResult) -> StructureFeatureSet:
    close = levels.close

    support_distance_pct = abs(close - levels.support.high) / close if levels.support else None
    resistance_distance_pct = abs(levels.resistance.low - close) / close if levels.resistance else None

    nearest_trendline_touch_count = nearest_trendline_direction = None
    if levels.trendlines:
        best = max(levels.trendlines, key=lambda t: t.touch_count)
        nearest_trendline_touch_count = best.touch_count
        nearest_trendline_direction = best.direction

    breakout_box_status = levels.breakout_boxes[-1].status if levels.breakout_boxes else None

    return StructureFeatureSet(
        support_low=levels.support.low if levels.support else None,
        support_high=levels.support.high if levels.support else None,
        resistance_low=levels.resistance.low if levels.resistance else None,
        resistance_high=levels.resistance.high if levels.resistance else None,
        support_distance_pct=support_distance_pct,
        resistance_distance_pct=resistance_distance_pct,
        nearest_trendline_touch_count=nearest_trendline_touch_count,
        nearest_trendline_direction=nearest_trendline_direction,
        breakout_box_status=breakout_box_status,
        swing_structure_score=levels.trend.structure if levels.trend else None,
    )
