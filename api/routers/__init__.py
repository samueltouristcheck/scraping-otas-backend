from api.routers.health import router as health_router
from api.routers.market import router as market_router
from api.routers.scraping_trigger import router as scraping_trigger_router
from api.routers.viator_listing import router as viator_listing_router

__all__ = ["health_router", "market_router", "scraping_trigger_router", "viator_listing_router"]
