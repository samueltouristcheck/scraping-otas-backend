"""Encolar manualmente un ciclo completo de scraping (GYG + Viator) en segundo plano."""

from __future__ import annotations

import logging

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException

from core.config import get_settings
from scheduler.jobs import run_getyourguide_cycle, run_viator_cycle

logger = logging.getLogger("api.scraping_trigger")

router = APIRouter(prefix="/scraping", tags=["scraping"])


@router.post("/trigger", summary="Encolar ciclo de scraping (GYG + Viator)")
async def trigger_scraping_cycle(
    background_tasks: BackgroundTasks,
    x_scraping_token: str | None = Header(default=None, alias="X-Scraping-Token"),
) -> dict[str, str]:
    settings = get_settings()
    secret = (settings.scraping_trigger_secret or "").strip()
    if not secret:
        raise HTTPException(status_code=404, detail="Scraping trigger not configured (SCRAPING_TRIGGER_SECRET)")
    if not x_scraping_token or x_scraping_token.strip() != secret:
        raise HTTPException(status_code=403, detail="Invalid X-Scraping-Token")

    async def run_both() -> None:
        try:
            await run_getyourguide_cycle()
            await run_viator_cycle()
            logger.info("manual_scrape_cycle_finished")
        except Exception:
            logger.exception("manual_scrape_cycle_failed")

    background_tasks.add_task(run_both)
    return {"status": "scheduled"}
