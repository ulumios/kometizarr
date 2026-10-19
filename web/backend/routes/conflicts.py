"""Kometa conflicts: list, status and actions."""

from fastapi import APIRouter, HTTPException

from src.services import conflicts, tasks
from src.services.models import ConflictAction
from src.services.progress import progress

router = APIRouter()


@router.get('/api/kometa/conflicts')
async def get_kometa_conflicts(library_name: str, refresh: bool = False):
    return await conflicts.get_conflicts(library_name, refresh)


@router.get('/api/kometa/conflicts/status')
async def get_kometa_conflict_status():
    return progress.conflict_view()


@router.post('/api/kometa/conflicts/action')
async def act_on_kometa_conflicts(request: ConflictAction):
    if request.action not in ('reset_render', 'remove_label') or not 0 < len(request.rating_keys) <= 250:
        raise HTTPException(400, 'Select 1–250 items and a supported action')
    task_id = await tasks.enqueue('conflict', request.model_dump())
    return {'status': 'started', 'task_id': task_id}
