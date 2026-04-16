import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.v1.router import api_v1_router
from core.config import get_settings
from core.logging import configure_logging
from database.session.engine import async_engine


@asynccontextmanager
async def lifespan(_: FastAPI):
    logger = logging.getLogger("api.lifespan")
    logger.info("api_starting")
    try:
        yield
    finally:
        logger.info("api_stopping")
        await async_engine.dispose()


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(
        title="OTA Competitive Intelligence API",
        version="0.1.0",
        lifespan=lifespan,
    )

    # Navegador: fetch desde Vercel (*.vercel.app) exige CORS. allow_origin_regex cubre
    # producción y previews sin listar cada URL en FRONTEND_ORIGINS.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.frontend_origins,
        allow_origin_regex=r"https://.+\.vercel\.app",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(api_v1_router, prefix="/api/v1")

    @app.get("/", include_in_schema=False)
    async def root() -> dict[str, str]:
        return {
            "service": "OTA Competitive Intelligence API",
            "health": "/api/v1/health",
            "docs": "/docs",
        }

    return app


app = create_app()
