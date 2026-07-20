from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.routers import dashboard, levels_detail, symbols
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

    return app


app = create_app()
