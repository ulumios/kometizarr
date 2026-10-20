"""Scheduled runs: normal/force overlay runs and the daily IMDb refresh."""

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from src.services import config, tasks
from src.services.models import ProcessRequest

logger = logging.getLogger('kometizarr')

scheduler = AsyncIOScheduler()


def _add_cron_job(job_id: str, schedule: str, libraries: list, force: bool, episodes: bool = False):
    parts = schedule.split()
    if len(parts) != 5:
        return
    trigger = CronTrigger(
        minute=parts[0], hour=parts[1],
        day=parts[2], month=parts[3], day_of_week=parts[4]
    )
    scheduler.add_job(
        cron_run_libraries,
        trigger=trigger,
        args=[libraries, force, episodes],
        id=job_id,
        replace_existing=True,
    )
    label = ", ".join(libraries) if libraries else "all"
    logger.info(f"Cron [{job_id}] scheduled: {schedule} for [{label}] (force={force}, episodes={episodes})")


def reschedule(settings: dict):
    """Apply both cron configs to the scheduler."""
    scheduler.remove_all_jobs()
    for key, force in [("cron_normal", False), ("cron_force", True)]:
        cron = settings.get(key, {})
        if cron.get("enabled") and cron.get("schedule"):
            try:
                _add_cron_job(key, cron["schedule"], cron.get("libraries", []), force,
                              bool(cron.get("include_episodes")))
            except Exception as e:
                logger.error(f"Failed to schedule {key}: {e}")
    imdb = settings.get('imdb_direct') or {}
    if imdb.get('enabled') and (imdb.get('auto_fetch') or imdb.get('auto_render')):
        try:
            scheduler.add_job(cron_imdb_sync, CronTrigger(hour=int(imdb.get('hour', 4)), minute=0),
                              id='imdb_refresh', replace_existing=True)
        except (ValueError, TypeError) as exc:
            logger.error('Invalid IMDb refresh hour: %s', exc)


async def cron_imdb_sync():
    await tasks.enqueue('imdb', {'mode': 'both' if config.load_settings()['imdb_direct'].get('auto_render') else 'ratings'})


async def run_libraries_sequentially(libraries: list, force: bool, episodes: bool = False):
    """Fetch all Plex library names if list is empty, then process each sequentially."""
    if not libraries:
        try:
            libraries = [lib.title for lib in config.plex_server().library.sections()
                         if lib.type in ('movie', 'show')]
        except Exception as e:
            logger.error(f"Cron: failed to fetch library list: {e}")
            return
    label = "force" if force else "normal"
    for lib_name in libraries:
        logger.info(f"Cron ({label}): processing {lib_name}")
        # Overlay options are taken from the saved settings when the task runs.
        # Episodes only matter for show libraries; the run ignores the flag elsewhere.
        await tasks.enqueue('process', ProcessRequest(library_name=lib_name, force=force,
                                                      include_episodes=episodes).model_dump())


async def cron_run_libraries(libraries: list, force: bool = False, episodes: bool = False):
    """Persist scheduled work before execution, even when another job is active."""
    await run_libraries_sequentially(libraries, force, episodes)


def next_runs():
    result = {}
    for key in ("cron_normal", "cron_force"):
        job = scheduler.get_job(key)
        result[key] = job.next_run_time.isoformat() if job and job.next_run_time else None
    return result
