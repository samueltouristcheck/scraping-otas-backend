import json
import logging
from datetime import datetime, timezone

from pydantic import ValidationError

from core.config import get_settings
from core.scrape_progress import ManualScrapeProgress
from core.services import persist_scrape_result, upsert_tour_and_source
from database.session import session_factory
from models.dto.monitoring import MonitoredTourSource
from scraping.getyourguide import GetYourGuideScraper

logger = logging.getLogger("scheduler.getyourguide")


def load_monitored_sources() -> list[MonitoredTourSource]:
    settings = get_settings()
    raw = settings.gyg_monitored_tours_json.strip()

    if not raw:
        return []

    payload = json.loads(raw)
    if not isinstance(payload, list):
        raise ValueError("GYG_MONITORED_TOURS_JSON must be a JSON array")

    sources: list[MonitoredTourSource] = []
    for item in payload:
        try:
            sources.append(MonitoredTourSource.model_validate(item))
        except ValidationError as exc:
            logger.error("invalid_monitored_source", extra={"error": str(exc), "item": item})
    return sources


async def run_getyourguide_cycle(*, progress: ManualScrapeProgress | None = None) -> None:
    settings = get_settings()
    monitored_sources = load_monitored_sources()
    if not monitored_sources:
        logger.warning("no_monitored_getyourguide_sources_configured")
        return

    scraper = GetYourGuideScraper(headless=True)
    captured_at = datetime.now(timezone.utc)

    try:
        for source_cfg in monitored_sources:
            if settings.gyg_future_only:
                horizons = GetYourGuideScraper.future_visit_horizons(
                    start_offset_days=max(0, min(180, settings.gyg_forward_start_offset_days)),
                    window_days=max(1, min(181, settings.gyg_forward_window_days)),
                )
            else:
                daily_horizon_days = max(0, min(180, settings.gyg_daily_horizon_days))
                horizons = scraper.default_horizons(daily_window_days=daily_horizon_days)
            logger.info(
                "scrape_started",
                extra={"ota": "getyourguide", "internal_code": source_cfg.internal_code, "url": str(source_cfg.source_url)},
            )

            # Resolve the OTA source once (not per-horizon)
            async with session_factory() as session:
                ota_source = await upsert_tour_and_source(
                    session=session,
                    source_cfg=source_cfg,
                    ota_name="getyourguide",
                )

            total_avail_with_slot = 0
            total_prices_with_slot = 0
            total_avail = 0
            total_prices = 0
            product_name: str | None = None
            raw_excerpt: str | None = None

            for hz in horizons:
                horizon_result = None
                try:
                    horizon_result = await scraper.scrape_one_horizon(
                        str(source_cfg.source_url),
                        hz,
                        captured_at=captured_at,
                        product_name=product_name,
                        raw_excerpt=raw_excerpt,
                    )
                except Exception as exc:
                    logger.warning(
                        "horizon_scrape_failed",
                        extra={
                            "ota": "getyourguide",
                            "internal_code": source_cfg.internal_code,
                            "date": hz.target_date.isoformat(),
                            "error": str(exc),
                        },
                    )
                else:
                    # Carry forward shared metadata across horizons
                    if horizon_result.product_name and product_name is None:
                        product_name = horizon_result.product_name
                    if horizon_result.raw_excerpt and raw_excerpt is None:
                        raw_excerpt = horizon_result.raw_excerpt

                    # Persist this horizon's data immediately
                    if horizon_result.prices or horizon_result.availability:
                        async with session_factory() as session:
                            await persist_scrape_result(
                                session=session,
                                source=ota_source,
                                scrape_result=horizon_result,
                            )

                    avail_with_slot = sum(1 for r in horizon_result.availability if r.slot_time is not None)
                    prices_with_slot = sum(1 for r in horizon_result.prices if r.slot_time is not None)
                    total_avail_with_slot += avail_with_slot
                    total_prices_with_slot += prices_with_slot
                    total_avail += len(horizon_result.availability)
                    total_prices += len(horizon_result.prices)

                    logger.info(
                        "horizon_persisted",
                        extra={
                            "ota": "getyourguide",
                            "internal_code": source_cfg.internal_code,
                            "date": hz.target_date.isoformat(),
                            "availability": len(horizon_result.availability),
                            "availability_with_slot": avail_with_slot,
                            "prices": len(horizon_result.prices),
                            "prices_with_slot": prices_with_slot,
                        },
                    )
                finally:
                    if progress is not None:
                        label = f"{source_cfg.internal_code} · {hz.target_date.isoformat()}"
                        await progress.advance("GetYourGuide", label)

            logger.info(
                "scrape_completed",
                extra={
                    "ota": "getyourguide",
                    "internal_code": source_cfg.internal_code,
                    "total_prices": total_prices,
                    "total_availability": total_avail,
                    "availability_with_slot": total_avail_with_slot,
                    "prices_with_slot": total_prices_with_slot,
                },
            )
    finally:
        await scraper.close()

