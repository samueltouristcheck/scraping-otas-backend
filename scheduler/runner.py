import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from core.config import get_settings
from core.logging import configure_logging
from scheduler.jobs import run_getyourguide_cycle, run_viator_cycle


async def run_scheduler() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)

    logger = logging.getLogger("scheduler.runner")
    scheduler = AsyncIOScheduler(timezone=settings.scheduler_tz)

    scheduler.add_job(
        run_getyourguide_cycle,
        trigger=CronTrigger.from_crontab(settings.scheduler_cron),
        id="getyourguide_cycle",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=120,
        replace_existing=True,
    )

    scheduler.add_job(
        run_viator_cycle,
        trigger=CronTrigger.from_crontab(settings.viator_scheduler_cron),
        id="viator_cycle",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=120,
        replace_existing=True,
    )

    scheduler.start()
    logger.info(
        "scheduler_started",
        extra={"timezone": settings.scheduler_tz, "cron": settings.scheduler_cron},
    )

    if settings.scheduler_run_on_startup:
        await run_getyourguide_cycle()
        await run_viator_cycle()

    stop_event = asyncio.Event()
    try:
        await stop_event.wait()
    finally:
        scheduler.shutdown(wait=False)
        logger.info("scheduler_stopped")


if __name__ == "__main__":
    asyncio.run(run_scheduler())
