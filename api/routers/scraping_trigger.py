"""Encolar manualmente un ciclo completo de scraping (GYG + Viator) en segundo plano."""

from __future__ import annotations

import logging

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException

from core.config import get_settings
from core.scrape_progress import ManualScrapeProgress, mark_done, mark_error, read_state, try_set_running
from scheduler.jobs.getyourguide_job import load_monitored_sources as load_gyg_sources
from scheduler.jobs.getyourguide_job import run_getyourguide_cycle
from scheduler.jobs.viator_job import _viator_horizons, load_monitored_sources as load_viator_sources, run_viator_cycle
from scraping.getyourguide.scraper import GetYourGuideScraper

logger = logging.getLogger("api.scraping_trigger")

router = APIRouter(prefix="/scraping", tags=["scraping"])


def _compute_total_scrape_steps() -> int:
    """Un paso por cada horizonte y fuente monitorizada (GYG + Viator)."""
    settings = get_settings()
    gyg_sources = load_gyg_sources()
    if settings.gyg_future_only:
        gh = GetYourGuideScraper.future_visit_horizons(
            start_offset_days=max(0, min(180, settings.gyg_forward_start_offset_days)),
            window_days=max(1, min(181, settings.gyg_forward_window_days)),
        )
    else:
        daily = max(0, min(180, settings.gyg_daily_horizon_days))
        gh = GetYourGuideScraper.default_horizons(daily_window_days=daily)
    total = len(gyg_sources) * len(gh)

    viator_sources = load_viator_sources()
    vh = _viator_horizons(settings)
    total += len(viator_sources) * len(vh)
    return total


def _require_trigger_token(x_scraping_token: str | None) -> None:
    settings = get_settings()
    secret = (settings.scraping_trigger_secret or "").strip()
    if not secret:
        raise HTTPException(status_code=404, detail="Scraping trigger not configured (SCRAPING_TRIGGER_SECRET)")
    if not x_scraping_token or x_scraping_token.strip() != secret:
        raise HTTPException(status_code=403, detail="Invalid X-Scraping-Token")


@router.get("/status", summary="Estado del scrape manual (progreso)")
async def scraping_status(x_scraping_token: str | None = Header(default=None, alias="X-Scraping-Token")) -> dict:
    _require_trigger_token(x_scraping_token)
    return await read_state()


@router.post("/trigger", summary="Encolar ciclo de scraping (GYG + Viator)")
async def trigger_scraping_cycle(
    background_tasks: BackgroundTasks,
    x_scraping_token: str | None = Header(default=None, alias="X-Scraping-Token"),
) -> dict[str, str | int]:
    _require_trigger_token(x_scraping_token)

    if not await try_set_running():
        raise HTTPException(status_code=409, detail="Ya hay un scrape en curso")

    total_steps = _compute_total_scrape_steps()
    progress = ManualScrapeProgress(total_steps) if total_steps > 0 else None

    async def run_both() -> None:
        try:
            await run_getyourguide_cycle(progress=progress)
            await run_viator_cycle(progress=progress)
            await mark_done()
            logger.info("manual_scrape_cycle_finished", extra={"total_steps": total_steps})
        except Exception as exc:
            logger.exception("manual_scrape_cycle_failed")
            await mark_error(str(exc))

    background_tasks.add_task(run_both)
    return {"status": "scheduled", "total_steps": total_steps}
