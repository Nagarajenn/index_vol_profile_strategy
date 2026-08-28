from datetime import date

from fastapi import APIRouter, Depends

from app.api.v1.dependencies import get_live_transition_advisor_service, get_market_transition_service
from app.schemas.market_transition import (
    CasCohortAnalysisResponseDTO,
    CasIntelligenceResponseDTO,
    CasWindowedDetailResponseDTO,
    LiveAdvisoryDTO,
    MtiResearchResponseDTO,
)
from app.services.live_transition_advisor_service import LiveTransitionAdvisorService
from app.services.market_transition_service import MarketTransitionService

router = APIRouter()


@router.get("/market-transition/{symbol}/research", response_model=MtiResearchResponseDTO)
async def get_market_transition_research(
    symbol: str, service: MarketTransitionService = Depends(get_market_transition_service)
) -> MtiResearchResponseDTO:
    """Market Transition Intelligence research view: factor-correlation
    findings across all analyzed trading days, plus each day's per-day
    score. Research/validation tool, entirely independent of the trading
    decision engine -- does not feed confidence_score or any live signal.
    """
    return await service.get_research(symbol)


@router.get("/market-transition/{symbol}/live-advisor", response_model=LiveAdvisoryDTO)
async def get_live_transition_advisor(
    symbol: str, service: LiveTransitionAdvisorService = Depends(get_live_transition_advisor_service)
) -> LiveAdvisoryDTO:
    """Live Market Transition Advisor: compares today's in-progress session
    against the historical MTI database above. Only produces a meaningful
    read between 2:00 PM and 3:01 PM IST -- outside that window `is_active`
    is false. Never a trading signal: risk_level is capped to
    Observe/Low/Medium/High/Very High, no buy/sell language anywhere.
    Read-only, independent of the trading decision engine.
    """
    return await service.get_live_advisory(symbol)


@router.get("/market-transition/{symbol}/cas-intelligence", response_model=CasIntelligenceResponseDTO)
async def get_cas_intelligence(
    symbol: str, service: MarketTransitionService = Depends(get_market_transition_service)
) -> CasIntelligenceResponseDTO:
    """CAS Intelligence: the 3pm transition re-analyzed under NSE's
    post-2026-08-03 Closing Auction Session framework (14:31-14:59 pre-
    window trend vs. 15:00-15:39 post-window trend), alongside each day's
    outcome under the original (unmodified) methodology for comparison, and
    option-chain context (PCR, institutional bias) at ~14:59. Additive/
    parallel research view -- does not feed the trading decision engine or
    replace /research or /live-advisor above. Volume is only reported
    through 15:14 (post_window_pre_auction_volume): Dhan's 1-min feed does
    not report reliable per-minute volume once the Closing Auction Session
    begins at 15:15.
    """
    return await service.get_cas_intelligence(symbol)


@router.get(
    "/market-transition/{symbol}/cas-intelligence/{session_date}/windowed-detail",
    response_model=CasWindowedDetailResponseDTO,
)
async def get_cas_windowed_detail(
    symbol: str, session_date: date, service: MarketTransitionService = Depends(get_market_transition_service)
) -> CasWindowedDetailResponseDTO:
    """Phase 7B: dual-resolution pre/post-3pm transition detail for one
    day -- six 5-minute pre-transition windows (14:30-14:59, FORECAST
    INFORMATION) at native detail, sixteen native 1-minute post-transition
    rows (15:00-15:15, ACTUAL OUTCOME), and 7 leakage-safe forecast
    checkpoints. Lazy-loaded on demand (not eagerly joined into
    /cas-intelligence above) -- fetch only when a UI expands a specific
    day. Pre-transition and post-transition data are never merged
    server-side; the two must stay visually distinct in any UI that
    renders this response.
    """
    return await service.get_cas_windowed_detail(symbol, session_date)


@router.get("/market-transition/{symbol}/cas-cohort-analysis", response_model=CasCohortAnalysisResponseDTO)
async def get_cas_cohort_analysis(
    symbol: str, service: MarketTransitionService = Depends(get_market_transition_service)
) -> CasCohortAnalysisResponseDTO:
    """Phase 7C: historical cohorts + pre-3pm warning-indicator statistics.
    Groups CAS-era days into 7 named cohorts (derived from Phase 7A's
    transition_type x magnitude_tier) and, for each cohort, compares its
    pre-3pm (14:55-14:59) state against the rest of the sample --
    "which conditions preceded this kind of outcome", complementary to
    (not a replacement for) /cas-intelligence's factor-correlation study.
    Every cohort is always present in the response, even with n_days=0.
    Does not claim predictive power from a low p-value alone: every
    result carries N and is explicitly marked "Insufficient data" below
    the cohort-appropriate minimum sample size.
    """
    return await service.get_cas_cohort_analysis(symbol)
