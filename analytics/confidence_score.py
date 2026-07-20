from dataclasses import dataclass, field

from analytics.breakout_boxes import BreakoutBox
from analytics.institutional_bias import InstitutionalBiasResult
from analytics.support_resistance import Zone
from analytics.trend_classifier import TrendResult
from analytics.trendlines import Trendline

SR_PROXIMITY_FULL_CREDIT_PCT = 0.01  # within 1% of price -> max proximity score
VWAP_FULL_CREDIT_PCT = 0.005  # 0.5% away from VWAP -> max distance score


@dataclass
class ConfidenceResult:
    score: int  # 0-100
    sub_scores: dict = field(default_factory=dict)
    weights_used: dict = field(default_factory=dict)
    partial_data: bool = False


def _trend_direction(trend: TrendResult) -> str | None:
    if trend.score > 0:
        return "up"
    if trend.score < 0:
        return "down"
    return None


def compute_confidence(
    trend: TrendResult,
    vwap_now: float | None,
    close: float,
    trendlines: list[Trendline],
    support: Zone | None,
    resistance: Zone | None,
    breakout_boxes: list[BreakoutBox],
    institutional_bias: InstitutionalBiasResult,
    weights: dict,
) -> ConfidenceResult:
    direction = _trend_direction(trend)
    sub: dict = {}

    sub["trend_alignment"] = abs(trend.score) / 3

    if vwap_now:
        dist_pct = abs(close - vwap_now) / vwap_now
        sub["vwap_position"] = min(dist_pct / VWAP_FULL_CREDIT_PCT, 1.0)
    else:
        sub["vwap_position"] = 0.0

    sub["structure_hh_hl"] = 1.0 if trend.structure != 0 and (trend.structure > 0) == (trend.score > 0) else 0.0

    matching_tl = [t for t in trendlines if t.direction == direction] if direction else []
    if matching_tl:
        best = max(matching_tl, key=lambda t: t.touch_count)
        sub["trendline_confluence"] = 1.0 if best.touch_count >= 3 else 0.5
    else:
        sub["trendline_confluence"] = 0.0

    distances = []
    if support is not None:
        distances.append(abs(close - support.high) / close)
    if resistance is not None:
        distances.append(abs(resistance.low - close) / close)
    if distances:
        sub["sr_proximity"] = max(0.0, 1 - min(distances) / SR_PROXIMITY_FULL_CREDIT_PCT)
    else:
        sub["sr_proximity"] = 0.0

    confirmed = [b for b in breakout_boxes if b.status in ("confirmed_up", "confirmed_down")]
    if confirmed:
        last_box = confirmed[-1]
        matches_dir = (last_box.status == "confirmed_up" and direction == "up") or (
            last_box.status == "confirmed_down" and direction == "down"
        )
        sub["breakout_confirmation"] = 1.0 if matches_dir else 0.3
    elif any(b.status == "forming" for b in breakout_boxes):
        sub["breakout_confirmation"] = 0.3
    else:
        sub["breakout_confirmation"] = 0.0

    partial_data = not institutional_bias.available
    if institutional_bias.available and institutional_bias.score is not None:
        sub["institutional_bias"] = abs(institutional_bias.score) / 2

    active_weights = {k: v for k, v in weights.items() if k in sub}
    total_weight = sum(active_weights.values())
    weights_used = {k: v / total_weight for k, v in active_weights.items()} if total_weight else {}

    raw_score = sum(sub[k] * weights_used.get(k, 0) for k in sub) * 100
    score = max(0, min(100, round(raw_score)))

    return ConfidenceResult(score=score, sub_scores=sub, weights_used=weights_used, partial_data=partial_data)
