"""Settings, fresh Plex posters and deleting backups."""

import asyncio
import logging
import shutil

from fastapi import APIRouter

from src.services import config, schedule, tasks
from src.services.models import FreshPostersRequest, ProcessRequest
from src.services.progress import progress

logger = logging.getLogger('kometizarr')
router = APIRouter()

_fresh_poster_tasks = {}  # queued 'fresh_posters' task id -> library


@router.get("/api/settings")
async def get_settings():
    settings = config.load_settings()
    for key, next_run in schedule.next_runs().items():
        settings.setdefault(key, {})["next_run"] = next_run
    return settings


@router.put("/api/settings")
async def update_settings(settings: dict):
    config.save_settings(settings)
    schedule.reschedule(settings)
    result = {"status": "saved"}
    for key, next_run in schedule.next_runs().items():
        result[f"{key}_next_run"] = next_run
    return result


@router.post("/api/fetch-fresh-posters")
async def start_fetch_fresh_posters(request: FreshPostersRequest):
    """Queue the same agent-poster reset the library browser uses, for a whole library."""
    task_id = await tasks.enqueue('fresh_posters', ProcessRequest(
        library_name=request.library_name, reset_to_plex=True).model_dump())
    _fresh_poster_tasks[task_id] = request.library_name
    return {"status": "started", "task_id": task_id}


@router.get("/api/fetch-fresh-posters/status")
async def get_fresh_posters_status():
    for task_id in list(_fresh_poster_tasks):
        if await asyncio.to_thread(tasks.with_tasks, 'get', task_id) not in ('queued', 'running'):
            _fresh_poster_tasks.pop(task_id)
    view = progress.restore_view()
    task = view['task']
    if task['kind'] != 'fresh_posters':
        task = {**task, 'done': 0, 'total': 0, 'success': 0, 'failed': 0, 'current': None,
                'library': next(iter(_fresh_poster_tasks.values()), None)}
    return {"is_running": bool(_fresh_poster_tasks), "library": task['library'],
            "progress": task['done'], "total": task['total'], "restored": task['success'],
            "failed": task['failed'], "current_item": task['current']}


@router.delete("/api/backups")
async def delete_backups(library_name: str, confirm: str = ""):
    if confirm != "DELETE":
        return {"error": "Must pass confirm=DELETE"}
    try:
        backup_dir = config.backup_library_dir(library_name)
    except ValueError as e:
        return {"error": str(e)}
    if not backup_dir.is_dir():
        return {"error": f"No backups found for {library_name}"}
    try:
        item_count = sum(1 for _ in backup_dir.iterdir())
        shutil.rmtree(backup_dir)
        logger.info(f"Deleted backups for {library_name} ({item_count} items)")
        return {"status": "deleted", "items": item_count}
    except Exception as e:
        return {"error": str(e)}
