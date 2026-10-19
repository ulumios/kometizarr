"""Maintenance: backup storage, orphaned backups, old uploads and Plex housekeeping."""

import asyncio
from typing import List

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.services import config, maintenance, tasks

router = APIRouter()


class AuditRequest(BaseModel):
    libraries: List[str] = []


class CleanupRequest(BaseModel):
    library: str
    paths: List[str]


class UploadsRequest(BaseModel):
    libraries: List[str]
    dry_run: bool = True


class PlexActionRequest(BaseModel):
    action: str


@router.get('/api/maintenance/overview')
async def maintenance_overview():
    data = await asyncio.to_thread(maintenance.overview)
    data['plex_data_dir'] = bool(maintenance.plex_data_dir(config.load_settings()))
    return data


@router.get('/api/maintenance/audit/latest')
async def latest_audit():
    """Reports of the newest finished backup audit."""
    for task in await asyncio.to_thread(tasks.with_tasks, 'list', 100):
        if task['kind'] == 'backup_audit' and task['status'] in ('completed', 'failed'):
            return {'task_id': task['id'], 'reports': ((task.get('progress') or {}).get('extra') or {}).get('reports', [])}
    return {'task_id': None, 'reports': []}


@router.post('/api/maintenance/audit')
async def start_audit(request: AuditRequest):
    return {'status': 'started', 'task_id': await tasks.enqueue('backup_audit', request.model_dump())}


@router.post('/api/maintenance/cleanup')
async def start_cleanup(request: CleanupRequest):
    if not request.paths:
        raise HTTPException(400, 'Keine Ordner ausgewählt')
    try:
        config.backup_library_dir(request.library)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {'status': 'started', 'task_id': await tasks.enqueue('backup_cleanup', request.model_dump())}


@router.post('/api/maintenance/plex-uploads')
async def start_plex_uploads(request: UploadsRequest):
    if not request.libraries:
        raise HTTPException(400, 'Select at least one library')
    return {'status': 'started', 'task_id': await tasks.enqueue('plex_uploads', request.model_dump())}


@router.post('/api/maintenance/plex')
async def start_plex_action(request: PlexActionRequest):
    if request.action not in maintenance.PLEX_ACTIONS:
        raise HTTPException(400, 'Unknown action')
    return {'status': 'started', 'task_id': await tasks.enqueue('plex_maintenance', request.model_dump())}
