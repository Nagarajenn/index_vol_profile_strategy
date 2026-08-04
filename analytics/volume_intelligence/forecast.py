"""Expected Next Interval Behaviour: a fixed 10-minute-horizon heuristic
composite over volume trend, momentum, character, institutional
participation, and historical similarity. Never predicts the rest of the
trading day -- a documented heuristic composite (like
market_transition/live_advisor.py's compute_transition_risk_level()), not
a fitted statistical model.
"""

import pandas as pd

from .character import TREND_WINDOW, _price_direction
from .models import HistoricalSimilarity, InstitutionalParticipation, NextIntervalForecast, VolumeCharacter, VolumeMomentum, VolumeTrend

FORECAST_HORIZON_MINUTES = 10

TREND_WEIGHT = 0.30
MOMENTUM_WEIGHT = 0.25
CHARACTER_WEIGHT = 0.20
INSTITUTIONAL_WEIGHT = 0.15
SIMILARITY_WEIGHT = 0.10

MIN_FACTOR_CONTRIBUTION = 0.05
MAX_SUPPORTING_FACTORS = 4

MIN_CANDLES_FOR_MOMENTUM_INSTITUTIONAL = 8

_TREND_COMPONENT = {"Strong Increasing": 1.0, "Increasing": 0.5, "Stable": 0.0, "Decreasing": -0.5, "Strong Decreasing": -1.0}
# All of Markup/Markdown/Accumulation/Distribution are "a coherent, sustained
# volume story matching price action" -- continuation-supporting regardless
# of which direction that story is in. Only Climactic (an exhaustion/
# absorption climax) is reversal-supporting.
_CHARACTER_COMPONENT = {"Markup": 0.6, "Markdown": 0.6, "Accumulation": 0.3, "Distribution": 0.3, "Climactic": -0.7, "Quiet-Consolidation": 0.0}


def _momentum_component(momentum: VolumeMomentum, price_direction: str) -> float:
    """Positive momentum (buy-leaning) is continuation-supporting while
    price is up (or flat/undetermined); the sign flips only when price is
    down, so sell-leaning-during-a-downtrend correctly supports
    continuation and buy-leaning-during-a-downtrend correctly reads as a
    bullish divergence that opposes continuation."""
    return momentum.normalized_score if price_direction != "down" else -momentum.normalized_score


def _institutional_component(institutional: InstitutionalParticipation, momentum: VolumeMomentum, price_direction: str) -> float:
    """institutional.score is an unsigned magnitude; sign comes from
    whether momentum's buy/sell lean agrees with price direction (using
    momentum as the "which side" proxy rather than a separate dominance
    param, since the two are already the same underlying signal)."""
    base = institutional.score / 100.0
    momentum_is_buy_leaning = momentum.normalized_score >= 0
    divergence = (price_direction == "up" and not momentum_is_buy_leaning) or (price_direction == "down" and momentum_is_buy_leaning)
    return -base if divergence else base


def _similarity_component(similarity: HistoricalSimilarity) -> float:
    if not similarity.top_days or similarity.resemblance_label is None:
        return 0.0
    if similarity.resemblance_label in ("accumulation-like sessions", "distribution-like sessions"):
        return 0.3
    if similarity.resemblance_label == "climactic/high-volume sessions":
        return -0.3
    return 0.0


def _lean(value: float) -> str:
    return "continuation" if value >= 0 else "reversal"


def _supporting_factors(
    trend: VolumeTrend | None, trend_value: float,
    momentum: VolumeMomentum, momentum_value: float,
    character: VolumeCharacter, character_value: float,
    institutional: InstitutionalParticipation, institutional_value: float,
    similarity: HistoricalSimilarity, similarity_value: float,
) -> list[str]:
    candidates: list[tuple[float, str]] = []

    if trend is not None:
        contribution = TREND_WEIGHT * trend_value
        if abs(contribution) >= MIN_FACTOR_CONTRIBUTION:
            candidates.append((abs(contribution), f"Volume trend: {trend.label} (supports {_lean(trend_value)})"))

    contribution = MOMENTUM_WEIGHT * momentum_value
    if abs(contribution) >= MIN_FACTOR_CONTRIBUTION:
        candidates.append((abs(contribution), f"Volume momentum: {momentum.label}, {momentum.streak_minutes} min streak (supports {_lean(momentum_value)})"))

    contribution = CHARACTER_WEIGHT * character_value
    if abs(contribution) >= MIN_FACTOR_CONTRIBUTION:
        candidates.append((abs(contribution), f"Character: {character.label} pattern (supports {_lean(character_value)})"))

    contribution = INSTITUTIONAL_WEIGHT * institutional_value
    if abs(contribution) >= MIN_FACTOR_CONTRIBUTION:
        alignment = "aligned with" if institutional_value >= 0 else "diverging from"
        candidates.append((abs(contribution), f"Institutional participation: {institutional.label}, {alignment} the current move"))

    if similarity.resemblance_label is not None:
        contribution = SIMILARITY_WEIGHT * similarity_value
        if abs(contribution) >= MIN_FACTOR_CONTRIBUTION:
            candidates.append((abs(contribution), f"Resembles {similarity.resemblance_label} historically (supports {_lean(similarity_value)})"))

    candidates.sort(key=lambda t: -t[0])
    return [text for _, text in candidates[:MAX_SUPPORTING_FACTORS]]


def compute_next_interval_forecast(
    trend: VolumeTrend | None,
    momentum: VolumeMomentum,
    character: VolumeCharacter,
    institutional: InstitutionalParticipation,
    similarity: HistoricalSimilarity,
    enriched: pd.DataFrame,
) -> NextIntervalForecast:
    price_direction = _price_direction(enriched, TREND_WINDOW)
    n_candles = len(enriched)

    trend_value = _TREND_COMPONENT.get(trend.label, 0.0) if trend is not None else 0.0
    trend_available = trend is not None

    momentum_value = _momentum_component(momentum, price_direction)
    momentum_available = n_candles >= MIN_CANDLES_FOR_MOMENTUM_INSTITUTIONAL

    character_value = _CHARACTER_COMPONENT.get(character.label, 0.0)

    institutional_value = _institutional_component(institutional, momentum, price_direction)
    institutional_available = n_candles >= MIN_CANDLES_FOR_MOMENTUM_INSTITUTIONAL

    similarity_value = _similarity_component(similarity)
    similarity_available = bool(similarity.top_days)

    composite = (
        TREND_WEIGHT * (trend_value if trend_available else 0.0)
        + MOMENTUM_WEIGHT * (momentum_value if momentum_available else 0.0)
        + CHARACTER_WEIGHT * character_value
        + INSTITUTIONAL_WEIGHT * (institutional_value if institutional_available else 0.0)
        + SIMILARITY_WEIGHT * (similarity_value if similarity_available else 0.0)
    )

    probability_continuation = max(0.1, min(0.9, 0.5 + composite * 0.4))
    probability_reversal = 1.0 - probability_continuation

    n_available = sum([trend_available, momentum_available, True, institutional_available, similarity_available])
    if n_available < 3:
        confidence = "Low"
    elif n_available == 5 and abs(composite) >= 0.5:
        confidence = "High"
    elif n_available >= 4 or abs(composite) >= 0.25:
        confidence = "Medium"
    else:
        confidence = "Low"

    supporting_factors = _supporting_factors(
        trend if trend_available else None, trend_value,
        momentum, momentum_value if momentum_available else 0.0,
        character, character_value,
        institutional, institutional_value if institutional_available else 0.0,
        similarity if similarity_available else HistoricalSimilarity(), similarity_value if similarity_available else 0.0,
    )

    return NextIntervalForecast(
        horizon_minutes=FORECAST_HORIZON_MINUTES,
        probability_continuation=round(probability_continuation, 3),
        probability_reversal=round(probability_reversal, 3),
        confidence=confidence,
        supporting_factors=supporting_factors,
        composite_score=round(composite, 3),
    )
