from datetime import datetime

from fastapi import APIRouter, Depends, Query

from app.api.v1.dependencies import get_quant_feature_service
from app.services.quant_feature_service import QuantFeatureService

router = APIRouter()


@router.get("/quant-features/{symbol}")
async def get_latest_quant_features(
    symbol: str, service: QuantFeatureService = Depends(get_quant_feature_service)
) -> dict:
    """Latest precomputed quant_market_features row for `symbol` --
    informational/export only, does not feed the strategy engine. Not
    wired into any dashboard panel yet; intended for external analysis
    (backtesting, threshold-tuning, a future ML step) via the Quant
    Feature Store (see quant_features/)."""
    return await service.get_latest(symbol)


@router.get("/quant-features/{symbol}/history")
async def get_quant_features_history(
    symbol: str,
    start: datetime = Query(...),
    end: datetime = Query(...),
    service: QuantFeatureService = Depends(get_quant_feature_service),
) -> list[dict]:
    """Precomputed quant_market_features rows for `symbol` in [start, end]
    -- same informational/export scope as the latest-row endpoint above."""
    return await service.get_history(symbol, start, end)
