"""Direct IMDb ratings: status and starting refreshes."""

from fastapi import APIRouter, HTTPException

from src.services import config, tasks
from src.services.models import ImdbSyncRequest, SelectedImdbRequest
from src.services.progress import progress

router = APIRouter()


@router.get('/api/imdb-sync/status')
async def get_imdb_sync_status():
    return progress.imdb_view()


@router.post('/api/library/{library_name}/selected-imdb')
async def start_selected_imdb(library_name: str, request: SelectedImdbRequest):
    if request.mode not in ('ratings', 'both') or not 0 < len(request.rating_keys) <= 250:
        raise HTTPException(400, 'Select 1–250 items and a valid action')
    task_id = await tasks.enqueue('selected_imdb', {'library': library_name, 'request': request.model_dump()})
    return {'status': 'started', 'task_id': task_id}


@router.post('/api/imdb-sync')
async def start_imdb_sync(request: ImdbSyncRequest):
    if request.mode not in ('ratings', 'both'):
        raise HTTPException(400, 'Invalid IMDb sync mode')
    if not config.load_settings().get('imdb_direct', {}).get('enabled'):
        raise HTTPException(400, 'Enable direct IMDb ratings first')
    task_id = await tasks.enqueue('imdb', request.model_dump())
    return {'status': 'started', 'task_id': task_id}
