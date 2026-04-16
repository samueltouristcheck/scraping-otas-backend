"""Ejecuta un ciclo de scraping real (GetYourGuide + Viator) usando la configuración del entorno.

Requisitos: pip install -r requirements.txt y playwright install chromium

Variables leídas desde .env o desde el entorno (como las genera run-real-scrape.ps1):
- GYG_MONITORED_TOURS_JSON
- VIATOR_MONITORED_TOURS_JSON

Uso:

    python -m scripts.run_real_scrape_once
"""

from __future__ import annotations

import asyncio

from scheduler.jobs.getyourguide_job import run_getyourguide_cycle
from scheduler.jobs.viator_job import run_viator_cycle


async def main() -> None:
    await run_getyourguide_cycle()
    await run_viator_cycle()


if __name__ == "__main__":
    asyncio.run(main())
