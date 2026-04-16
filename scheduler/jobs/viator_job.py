import json
import logging
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from pydantic import ValidationError

from core.config import get_settings
from core.services import persist_scrape_result, upsert_tour_and_source
from database.session import session_factory
from models.dto.monitoring import MonitoredTourSource
from models.dto.scraping import ScrapedAvailabilityPoint, ScrapedPricePoint, ScrapeResult
from scraping.viator.listing_scraper import ViatorListingScraper

logger = logging.getLogger("scheduler.viator")


def load_monitored_sources() -> list[MonitoredTourSource]:
    settings = get_settings()
    raw = settings.viator_monitored_tours_json.strip()

    if not raw:
        return []

    payload = json.loads(raw)
    if not isinstance(payload, list):
        raise ValueError("VIATOR_MONITORED_TOURS_JSON must be a JSON array")

    sources: list[MonitoredTourSource] = []
    for item in payload:
        try:
            sources.append(MonitoredTourSource.model_validate(item))
        except ValidationError as exc:
            logger.error("invalid_monitored_source", extra={"error": str(exc), "item": item})
    return sources


def _parse_price(raw: str | None) -> Decimal | None:
    if not raw:
        return None
    try:
        return Decimal(str(raw).replace(",", ".").strip())
    except InvalidOperation:
        return None


async def run_viator_cycle() -> None:
    settings = get_settings()
    monitored_sources = load_monitored_sources()
    if not monitored_sources:
        logger.warning("no_monitored_viator_sources_configured")
        return

    # Viator listing scraper must run non-headless (Cloudflare blocks headless)
    scraper = ViatorListingScraper(headless=False)
    captured_at = datetime.now(timezone.utc)
    # Misma referencia calendario que /prices/latest (datetime.now(UTC).date()) para no quedar fuera de la ventana.
    today = datetime.now(timezone.utc).date()

    try:
        for source_cfg in monitored_sources:
            listing_url = str(source_cfg.source_url)
            logger.info(
                "scrape_started",
                extra={"ota": "viator", "internal_code": source_cfg.internal_code, "url": listing_url},
            )

            # Upsert tour + source in DB
            async with session_factory() as session:
                ota_source = await upsert_tour_and_source(
                    session=session,
                    source_cfg=source_cfg,
                    ota_name="viator",
                )

            # Scrape the listing page (first page only — no infinite scroll needed)
            try:
                cards = await scraper.scrape_listing(
                    listing_url,
                    max_scroll_rounds=2,    # one pass to load the page, one to confirm no more
                    stale_rounds_limit=1,   # stop as soon as first round is stale
                )
                if not cards and "/tours/" in listing_url:
                    cards = await scraper.scrape_product_page_snapshot(listing_url)
            except Exception as exc:
                logger.error(
                    "listing_scrape_failed",
                    extra={"ota": "viator", "internal_code": source_cfg.internal_code, "error": str(exc)},
                )
                continue

            # Map each card to price + availability points (horizon_days=0 = current snapshot)
            prices: list[ScrapedPricePoint] = []
            availability: list[ScrapedAvailabilityPoint] = []

            for card in cards:
                price_val = _parse_price(card.get("price_eur"))
                if price_val is None:
                    continue  # skip cards without a parseable price

                option_name = (card.get("name") or "")[:500]

                prices.append(
                    ScrapedPricePoint(
                        target_date=today,
                        horizon_days=0,
                        observed_at=captured_at,
                        option_name=option_name,
                        currency_code="EUR",
                        list_price=price_val,
                        final_price=price_val,
                    )
                )
                availability.append(
                    ScrapedAvailabilityPoint(
                        target_date=today,
                        horizon_days=0,
                        observed_at=captured_at,
                        option_name=option_name,
                        is_available=True,
                    )
                )

            scrape_result = ScrapeResult(
                ota_name="viator",
                source_url=source_cfg.source_url,
                product_name=source_cfg.attraction,
                captured_at=captured_at,
                prices=prices,
                availability=availability,
            )

            if prices or availability:
                async with session_factory() as session:
                    await persist_scrape_result(
                        session=session,
                        source=ota_source,
                        scrape_result=scrape_result,
                    )

            logger.info(
                "scrape_completed",
                extra={
                    "ota": "viator",
                    "internal_code": source_cfg.internal_code,
                    "cards_found": len(cards),
                    "prices_persisted": len(prices),
                },
            )

    finally:
        await scraper.close()
