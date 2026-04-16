"""Elimina fuentes y snapshots dejados por scripts de demo (p. ej. Park Güell de prueba).

Tras ejecutarlo, vuelve a sembrar fuentes reales::

    python -m scripts.seed_monitored_tours

y lanza un scrape o espera al scheduler.

Uso: DATABASE_URL=... python -m scripts.purge_demo_market_data
     DATABASE_URL=... python -m scripts.purge_demo_market_data --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
from uuid import UUID

from sqlalchemy import delete, func, or_, select

from core.config import get_settings
from core.logging import configure_logging
from database.models import Availability, OtaSource, Price
from database.session import session_factory

DEMO_SCRAPE_RUN = UUID("00000000-0000-4000-8000-00000000d3d0")


def _demo_source_predicate():
    return or_(
        OtaSource.external_product_id.startswith("demo-"),
        OtaSource.product_url.ilike("%example-park-guell-demo%"),
        OtaSource.product_url.ilike("%example.invalid/demo/%"),
    )


async def _purge(*, dry_run: bool) -> None:
    settings = get_settings()
    configure_logging(settings.log_level)

    async with session_factory() as session:
        count_p_demo = await session.scalar(
            select(func.count()).select_from(Price).where(Price.raw_payload.contains({"demo": True}))
        )
        count_p_seed = await session.scalar(
            select(func.count()).select_from(Price).where(Price.raw_payload.contains({"demo_seed": True}))
        )
        count_p_run = await session.scalar(
            select(func.count()).select_from(Price).where(Price.scrape_run_id == DEMO_SCRAPE_RUN)
        )
        count_a_demo = await session.scalar(
            select(func.count()).select_from(Availability).where(Availability.raw_payload.contains({"demo": True}))
        )
        count_a_seed = await session.scalar(
            select(func.count()).select_from(Availability).where(Availability.raw_payload.contains({"demo_seed": True}))
        )
        count_a_run = await session.scalar(
            select(func.count()).select_from(Availability).where(Availability.scrape_run_id == DEMO_SCRAPE_RUN)
        )
        count_src = await session.scalar(select(func.count()).select_from(OtaSource).where(_demo_source_predicate()))

        print(
            "[purge] prices (demo / demo_seed / run demo): "
            f"{count_p_demo} / {count_p_seed} / {count_p_run}; "
            f"availability: {count_a_demo} / {count_a_seed} / {count_a_run}; "
            f"ota_sources demo: {count_src}"
        )

        if dry_run:
            print("[dry-run] No se ha borrado nada.")
            return

        await session.execute(delete(Price).where(Price.raw_payload.contains({"demo": True})))
        await session.execute(delete(Price).where(Price.raw_payload.contains({"demo_seed": True})))
        await session.execute(delete(Price).where(Price.scrape_run_id == DEMO_SCRAPE_RUN))
        await session.execute(delete(Availability).where(Availability.raw_payload.contains({"demo": True})))
        await session.execute(delete(Availability).where(Availability.raw_payload.contains({"demo_seed": True})))
        await session.execute(delete(Availability).where(Availability.scrape_run_id == DEMO_SCRAPE_RUN))
        await session.execute(delete(OtaSource).where(_demo_source_predicate()))
        await session.commit()
        print("Purge demo completado.")


def main() -> None:
    p = argparse.ArgumentParser(description="Quita datos y fuentes OTA de demos antiguos.")
    p.add_argument("--dry-run", action="store_true", help="Solo cuenta filas, no borra.")
    args = p.parse_args()
    asyncio.run(_purge(dry_run=args.dry_run))


if __name__ == "__main__":
    main()
