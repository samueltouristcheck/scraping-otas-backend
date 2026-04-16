from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import Availability, OtaSource, Price, Tour
from models.dto.monitoring import MonitoredTourSource
from models.dto.scraping import ScrapeResult


async def upsert_tour_and_source(
    session: AsyncSession,
    source_cfg: MonitoredTourSource,
    ota_name: str,
) -> OtaSource:
    tour_stmt = select(Tour).where(Tour.internal_code == source_cfg.internal_code)
    tour = await session.scalar(tour_stmt)

    if tour is None:
        tour = Tour(
            attraction=source_cfg.attraction,
            variant=source_cfg.variant,
            internal_code=source_cfg.internal_code,
            market=source_cfg.market,
            city=source_cfg.city,
            is_active=True,
        )
        session.add(tour)
        await session.flush()

    source_stmt = select(OtaSource).where(
        OtaSource.ota_name == ota_name,
        OtaSource.external_product_id == source_cfg.external_product_id,
    )
    source = await session.scalar(source_stmt)

    if source is None:
        source = OtaSource(
            tour_id=tour.id,
            ota_name=ota_name,
            external_product_id=source_cfg.external_product_id,
            product_url=str(source_cfg.source_url),
            default_currency="EUR",
            default_locale="en",
            is_active=True,
            source_metadata={
                "attraction": source_cfg.attraction,
                "variant": source_cfg.variant,
                "city": source_cfg.city,
            },
        )
        session.add(source)
        await session.flush()
    else:
        source.tour_id = tour.id
        source.product_url = str(source_cfg.source_url)
        source.is_active = True
        source.source_metadata = {
            "attraction": source_cfg.attraction,
            "variant": source_cfg.variant,
            "city": source_cfg.city,
        }

    return source


async def persist_scrape_result(
    session: AsyncSession,
    source: OtaSource,
    scrape_result: ScrapeResult,
) -> None:
    scrape_run_id = uuid4()

    for item in scrape_result.prices:
        session.add(
            Price(
                ota_source_id=source.id,
                scrape_run_id=scrape_run_id,
                observed_at=item.observed_at,
                target_date=item.target_date,
                horizon_days=item.horizon_days,
                slot_time=item.slot_time,
                language_code=item.language_code,
                option_name=item.option_name,
                currency_code=item.currency_code,
                list_price=item.list_price,
                final_price=item.final_price,
                raw_payload={
                    "ota_name": scrape_result.ota_name,
                    "source_url": str(scrape_result.source_url),
                    "popularity_count_yesterday": item.popularity_count_yesterday,
                    "popularity_label": item.popularity_label,
                    "detail_tour_name": item.detail_tour_name,
                    "detail_page_url": item.detail_page_url,
                },
            )
        )

    for item in scrape_result.availability:
        session.add(
            Availability(
                ota_source_id=source.id,
                scrape_run_id=scrape_run_id,
                observed_at=item.observed_at,
                target_date=item.target_date,
                horizon_days=item.horizon_days,
                slot_time=item.slot_time,
                language_code=item.language_code,
                option_name=item.option_name,
                is_available=item.is_available,
                seats_available=item.seats_available,
                raw_payload={
                    "ota_name": scrape_result.ota_name,
                    "source_url": str(scrape_result.source_url),
                    "detail_tour_name": item.detail_tour_name,
                    "detail_page_url": item.detail_page_url,
                },
            )
        )

    await session.commit()
