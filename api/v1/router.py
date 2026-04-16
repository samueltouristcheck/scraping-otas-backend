from fastapi import APIRouter

from api.routers import health_router, market_router, scraping_trigger_router, viator_listing_router

api_v1_router = APIRouter()


@api_v1_router.get(
    "",
    summary="API v1 index",
    description="Abre esta URL en el navegador para comprobar que el prefijo /api/v1 responde; los datos están en /tours, /health, etc.",
)
async def api_v1_index() -> dict[str, str]:
    """Evita 404 en la URL base que usa el frontend como VITE_API_BASE_URL."""
    return {
        "service": "OTA Competitive Intelligence API",
        "version": "v1",
        "health": "/api/v1/health",
        "health_db": "/api/v1/health/db",
        "tours": "/api/v1/tours",
        "docs": "/docs",
    }


api_v1_router.include_router(health_router)
api_v1_router.include_router(market_router)
api_v1_router.include_router(scraping_trigger_router)
api_v1_router.include_router(viator_listing_router)
