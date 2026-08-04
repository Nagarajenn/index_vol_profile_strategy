"""Deterministic, template-generated observation sentences -- never an LLM
call, same design decision as every other live/per-minute explanation in
this app. A "worth mentioning" gate (each template has its own concrete
trigger threshold) caps output to the most relevant observations rather
than surfacing all candidates every minute -- most minutes should produce
0-2 observations, which is the intended, honest behavior.
"""

import pandas as pd

from .character import TREND_WINDOW, _price_direction
from .models import (
    AbsorptionSignal,
    BuySellDominance,
    ExhaustionSignal,
    HistoricalSimilarity,
    InstitutionalParticipation,
    NextIntervalForecast,
    RvolReading,
    VolumeCharacter,
    VolumeDryUp,
    VolumeNarrative,
    VolumeSpike,
    VolumeTrend,
)

MAX_OBSERVATIONS = 4
RVOL_NOTABLE_DEVIATION_PCT = 20.0
DOMINANCE_STREAK_NOTABLE_MINUTES = 5
SELLING_WEAKENING_DROP = 0.1
SIMILARITY_NOTABLE_THRESHOLD = 0.75
_DOMINANCE_WINDOW = 8  # matches pressure.py's default


def build_headline(character: VolumeCharacter, forecast: NextIntervalForecast) -> str:
    lean = "continuation" if forecast.probability_continuation >= forecast.probability_reversal else "reversal"
    probability = forecast.probability_continuation if lean == "continuation" else forecast.probability_reversal
    return f"{character.label} character with a {lean} lean ({probability:.0%}, {forecast.confidence} confidence)."


def _rvol_observation(rvol: RvolReading) -> tuple[int, str] | None:
    primary = rvol.primary
    if primary is None or primary.interval_rvol_pct is None:
        return None
    deviation = primary.interval_rvol_pct - 100.0
    if abs(deviation) < RVOL_NOTABLE_DEVIATION_PCT:
        return None
    direction = "above" if deviation > 0 else "below"
    return 2, f"Current interval volume is {abs(deviation):.0f}% {direction} the 20-day average."


def _dominance_streak_observation(dominance: BuySellDominance) -> tuple[int, str] | None:
    if dominance.dominant_side == "balanced" or dominance.consecutive_dominant_minutes < DOMINANCE_STREAK_NOTABLE_MINUTES:
        return None
    return 1, f"{dominance.dominant_side.capitalize()} volume has dominated the last {dominance.consecutive_dominant_minutes} minutes."


def _sell_ratio(window: pd.DataFrame) -> float | None:
    buy = float(window["buy_volume"].sum())
    sell = float(window["sell_volume"].sum())
    return sell / (buy + sell) if (buy + sell) > 0 else None


def _selling_weakening_observation(enriched: pd.DataFrame, price_direction: str) -> tuple[int, str] | None:
    if price_direction != "down" or len(enriched) < _DOMINANCE_WINDOW * 2:
        return None
    recent_ratio = _sell_ratio(enriched.tail(_DOMINANCE_WINDOW))
    prior_ratio = _sell_ratio(enriched.iloc[-(_DOMINANCE_WINDOW * 2) : -_DOMINANCE_WINDOW])
    if recent_ratio is None or prior_ratio is None:
        return None
    if prior_ratio - recent_ratio >= SELLING_WEAKENING_DROP:
        return 1, "Selling pressure is weakening despite falling prices."
    return None


def _breakout_volume_observation(enriched: pd.DataFrame, trend: VolumeTrend | None) -> tuple[int, str] | None:
    if trend is None or trend.label not in ("Increasing", "Strong Increasing") or len(enriched) < TREND_WINDOW:
        return None
    window = enriched.tail(TREND_WINDOW)
    current_close = float(window["close"].iloc[-1])
    if current_close >= float(window["close"].max()) or current_close <= float(window["close"].min()):
        return 3, "Volume expansion supports the current breakout."
    return None


def _conviction_divergence_observation(price_direction: str, trend: VolumeTrend | None) -> tuple[int, str] | None:
    if price_direction == "up" and trend is not None and trend.label in ("Decreasing", "Strong Decreasing"):
        return 1, "Price is rising while volume is declining, suggesting weakening conviction."
    return None


def _similarity_observation(similarity: HistoricalSimilarity) -> tuple[int, str] | None:
    if not similarity.top_days or similarity.resemblance_label is None or similarity.top_days[0].similarity < SIMILARITY_NOTABLE_THRESHOLD:
        return None
    return 2, f"Current volume profile closely resembles previous {similarity.resemblance_label}."


def _spike_observation(spike: VolumeSpike) -> tuple[int, str] | None:
    if not spike.is_spike or spike.multiple is None:
        return None
    return 1, f"Volume spike detected: {spike.multiple:.1f}x the recent average."


def _dryup_observation(dryup: VolumeDryUp) -> tuple[int, str] | None:
    if not dryup.is_dryup or dryup.fraction is None:
        return None
    return 3, f"Volume has dried up to {dryup.fraction:.0%} of the recent average."


def _absorption_observation(absorption: AbsorptionSignal) -> tuple[int, str] | None:
    if not absorption.detected:
        return None
    return 1, "High volume with little price movement suggests absorption near current levels."


def _exhaustion_observation(exhaustion: ExhaustionSignal) -> tuple[int, str] | None:
    if not exhaustion.detected:
        return None
    move_word = "up-move" if exhaustion.direction == "up" else "down-move"
    return 1, f"A volume climax with a rejection wick suggests possible exhaustion of the {move_word}."


def _institutional_observation(institutional: InstitutionalParticipation, dominance: BuySellDominance) -> tuple[int, str] | None:
    if institutional.label not in ("High", "Very High"):
        return None
    side_phrase = f"aligned with {dominance.dominant_side} dominance" if dominance.dominant_side != "balanced" else "with no clear side dominance"
    return 2, f"Institutional-scale participation is elevated ({institutional.label}), {side_phrase}."


def build_observations(
    enriched: pd.DataFrame,
    rvol: RvolReading,
    dominance: BuySellDominance,
    trend: VolumeTrend | None,
    spike: VolumeSpike,
    dryup: VolumeDryUp,
    absorption: AbsorptionSignal,
    exhaustion: ExhaustionSignal,
    institutional: InstitutionalParticipation,
    similarity: HistoricalSimilarity,
    max_observations: int = MAX_OBSERVATIONS,
) -> list[str]:
    price_direction = _price_direction(enriched, TREND_WINDOW)

    results = [
        _rvol_observation(rvol),
        _dominance_streak_observation(dominance),
        _selling_weakening_observation(enriched, price_direction),
        _breakout_volume_observation(enriched, trend),
        _conviction_divergence_observation(price_direction, trend),
        _similarity_observation(similarity),
        _spike_observation(spike),
        _dryup_observation(dryup),
        _absorption_observation(absorption),
        _exhaustion_observation(exhaustion),
        _institutional_observation(institutional, dominance),
    ]
    candidates = [r for r in results if r is not None]
    candidates.sort(key=lambda t: t[0])
    return [text for _, text in candidates[:max_observations]]


def build_narrative(
    rvol: RvolReading,
    dominance: BuySellDominance,
    trend: VolumeTrend | None,
    character: VolumeCharacter,
    spike: VolumeSpike,
    dryup: VolumeDryUp,
    absorption: AbsorptionSignal,
    exhaustion: ExhaustionSignal,
    institutional: InstitutionalParticipation,
    similarity: HistoricalSimilarity,
    forecast: NextIntervalForecast,
    enriched: pd.DataFrame,
) -> VolumeNarrative:
    headline = build_headline(character, forecast)
    observations = build_observations(enriched, rvol, dominance, trend, spike, dryup, absorption, exhaustion, institutional, similarity)
    return VolumeNarrative(headline=headline, observations=observations)
