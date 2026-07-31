from app.models import MtiDailyTransition, MtiFactorCorrelation
from app.repositories.protocols import MarketTransitionRepositoryProtocol
from app.schemas.market_transition import (
    ContributingFactorDTO,
    MtiDailyResultDTO,
    MtiFactorCorrelationDTO,
    MtiResearchResponseDTO,
)


class MarketTransitionService:
    """Read-only assembly of the Market Transition Intelligence research
    view. All the actual statistical work happens offline in
    market_transition/ (run via scripts/run_market_transition_research.py)
    -- this service just fetches the persisted results and maps them to
    DTOs, entirely independent of the trading decision engine.
    """

    def __init__(self, repo: MarketTransitionRepositoryProtocol) -> None:
        self._repo = repo

    async def get_research(self, symbol: str, limit: int = 200) -> MtiResearchResponseDTO:
        daily_rows = await self._repo.list_daily(symbol, limit)
        correlation_rows = await self._repo.list_correlations(symbol)

        correlations = [self._to_correlation_dto(r) for r in correlation_rows]
        correlations.sort(key=lambda c: (c.p_value is None, c.p_value if c.p_value is not None else 1.0))

        daily_results = [self._to_daily_dto(r) for r in daily_rows]

        return MtiResearchResponseDTO(
            symbol=symbol,
            total_days_analyzed=len(daily_results),
            correlations=correlations,
            daily_results=daily_results,
        )

    @staticmethod
    def _to_correlation_dto(row: MtiFactorCorrelation) -> MtiFactorCorrelationDTO:
        return MtiFactorCorrelationDTO(
            factor_name=row.factor_name,
            factor_type=row.factor_type,
            target=row.target,
            n_days=row.n_days,
            statistic=row.statistic,
            p_value=row.p_value,
            confidence_label=row.confidence_label,
            direction_note=row.direction_note,
            category_breakdown=row.category_breakdown,
        )

    @staticmethod
    def _to_daily_dto(row: MtiDailyTransition) -> MtiDailyResultDTO:
        factors = [ContributingFactorDTO(**f) for f in (row.top_contributing_factors or [])]
        return MtiDailyResultDTO(
            session_date=row.session_date,
            profile_shape_1459=row.profile_shape_1459,
            market_regime_1459=row.market_regime_1459,
            expiry_type=row.expiry_type,
            transition_direction=row.transition_direction,
            transition_move=row.transition_move,
            post_transition_move=row.post_transition_move,
            outcome=row.outcome,
            outcome_magnitude=row.outcome_magnitude,
            transition_risk_score=row.transition_risk_score,
            probability_continuation=row.probability_continuation,
            probability_reversal=row.probability_reversal,
            expected_volatility=row.expected_volatility,
            expected_direction=row.expected_direction,
            historical_similarity_score=row.historical_similarity_score,
            top_contributing_factors=factors,
            statistical_confidence=row.statistical_confidence,
            explanation=row.explanation,
            computed_at=row.computed_at,
        )
