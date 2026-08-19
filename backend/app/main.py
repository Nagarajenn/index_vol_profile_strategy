from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.routers import (
    dashboard,
    levels_detail,
    market_intelligence,
    market_transition,
    quant_features,
    symbols,
    volume_intelligence,
    volume_profile,
)
from app.core.config import settings
from app.exceptions import register_exception_handlers


def create_app() -> FastAPI:
    app = FastAPI(title="Trading Intelligence Dashboard API", version="0.1.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["GET"],
        allow_headers=["*"],
    )

    register_exception_handlers(app)

    app.include_router(symbols.router, prefix="/api/v1", tags=["symbols"])
    app.include_router(dashboard.router, prefix="/api/v1", tags=["dashboard"])
    app.include_router(levels_detail.router, prefix="/api/v1", tags=["levels"])
    app.include_router(volume_profile.router, prefix="/api/v1", tags=["volume-profile"])
    app.include_router(volume_intelligence.router, prefix="/api/v1", tags=["volume-intelligence"])
    app.include_router(market_intelligence.router, prefix="/api/v1", tags=["market-intelligence"])
    app.include_router(market_transition.router, prefix="/api/v1", tags=["market-transition"])
    app.include_router(quant_features.router, prefix="/api/v1", tags=["quant-features"])

    return app


app = create_app()
