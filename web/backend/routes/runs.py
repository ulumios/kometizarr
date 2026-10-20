"""Starting and stopping runs, the task list and live progress."""

import asyncio
import time

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect

from src.services import library_index, overlay, tasks
from src.services.models import ProcessBatchRequest, ProcessRequest, PreviewRequest
from src.services.progress import connections, progress

router = APIRouter()


@router.post("/api/process")
async def start_processing(request: ProcessRequest):
    """Start overlay processing"""
    # Missing overlay options are filled from saved settings when the task runs.
    job_id = await tasks.enqueue('process', request.model_dump())
    return {"status": "started", "library": request.library_name, "task_id": job_id}


@router.post("/api/process-batch")
async def start_processing_batch(request: ProcessBatchRequest):
    """Process multiple libraries sequentially."""
    if not request.library_names:
        return {"error": "No libraries specified"}
    job_id = await tasks.enqueue('batch', request.model_dump())
    return {"status": "started", "libraries": request.library_names, "task_id": job_id}


@router.post("/api/plan")
async def plan_processing(request: ProcessRequest):
    """Preview a run: what would be rendered, skipped or fail, without changing anything."""
    job_id = await tasks.enqueue('plan', request.model_dump())
    return {"status": "started", "library": request.library_name, "task_id": job_id}


@router.post("/api/restore")
async def restore_originals(request: ProcessRequest):
    """Start restoring original posters from backups"""
    job_id = await tasks.enqueue('restore', request.model_dump())
    return {"status": "started", "library": request.library_name, "task_id": job_id}


@router.post("/api/stop")
@router.post("/api/restore/stop")
async def stop_processing():
    """Request a graceful stop of the running item loop"""
    if progress.running:
        progress.stop_requested = True
        return {"status": "stopping", "message": "Will stop after the current item"}
    return {"status": "idle", "message": "Nothing is running"}


@router.get("/api/progress")
async def get_progress():
    """The unified progress of the running (or last) task."""
    return progress.snapshot()


@router.get("/api/status")
async def get_status():
    return progress.live_view()


@router.get("/api/restore/status")
async def get_restore_status():
    return progress.restore_view()


@router.post("/api/preview")
async def preview_posters(request: PreviewRequest):
    return await asyncio.to_thread(overlay.preview_posters, request)


@router.websocket("/ws/progress")
async def websocket_progress(websocket: WebSocket):
    """Live progress; updates are pushed by progress.publish()."""
    await websocket.accept()
    connections.append(websocket)
    try:
        await websocket.send_json(progress.live_view())
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        if websocket in connections:
            connections.remove(websocket)


@router.get('/api/tasks')
async def list_tasks():
    rows = await asyncio.to_thread(tasks.with_tasks, 'list')
    for task in rows:
        # Polled every few seconds: send the size only, the items come from /items
        results = task.pop('results', None)
        task['result_count'] = len(results) if isinstance(results, (dict, list)) else 0
    if progress.running:
        snap = progress.snapshot()
        for task in rows:
            if task['id'] == progress.task_id:
                task['progress'] = {key: snap[key] for key in (
                    'done', 'total', 'success', 'failed', 'skipped', 'current', 'phase', 'percent')}
                task['live'] = snap
                break
    for library, state in library_index.scans.items():
        if state.get('is_running') or state.get('finished_at'):
            total, done = state.get('total', 0), state.get('scanned', 0)
            rows.insert(0, {'id': f'library-scan:{library}', 'kind': 'library_scan',
                'status': 'running' if state.get('is_running') else ('failed' if state.get('error') else 'completed'),
                'created_at': state.get('started_at') or time.time(), 'payload': {'libraries': [library]},
                'target': {'library': library}, 'error': state.get('error'),
                'progress': {'percent': int(done * 100 / total) if total else 0, 'done': done,
                             'total': total, 'phase': 'Bibliothek scannen'}})
    return {'tasks': rows}


@router.get('/api/tasks/{task_id}/status')
async def task_status(task_id: int):
    status = await asyncio.to_thread(tasks.with_tasks, 'get', task_id)
    if status is None:
        raise HTTPException(404, 'Task not found')
    return {'status': status}


async def _task_or_404(task_id):
    task = await asyncio.to_thread(tasks.with_tasks, 'fetch', task_id)
    if task is None:
        raise HTTPException(404, 'Task not found')
    return task


@router.get('/api/tasks/{task_id}/items')
async def task_items(task_id: int):
    """Items a task touched, with titles and the show/season path to open them in the library browser."""
    task = await _task_or_404(task_id)
    return await asyncio.to_thread(library_index.task_items, task)


@router.post('/api/tasks/{task_id}/run-plan')
async def run_plan(task_id: int):
    """Execute a finished preview with exactly its options."""
    task = await _task_or_404(task_id)
    if task['kind'] != 'plan':
        raise HTTPException(400, 'Not a preview task')
    kind, payload = tasks.follow_up(task)
    return {'status': 'started', 'task_id': await tasks.enqueue(kind, payload)}


@router.post('/api/tasks/{task_id}/retry')
async def retry_failed(task_id: int):
    """Start the same task again for the items that failed."""
    task = await _task_or_404(task_id)
    keys = ((task.get('progress') or {}).get('failed_keys')) or []
    if not keys:
        raise HTTPException(400, 'Keine fehlgeschlagenen Einträge gespeichert')
    try:
        kind, payload = tasks.follow_up(task, keys)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {'status': 'started', 'task_id': await tasks.enqueue(kind, payload), 'items': len(keys)}


@router.post('/api/tasks/{task_id}/kometa-reset')
async def reset_kometa_skipped(task_id: int):
    """Run the items a task skipped because of Kometa again, resetting Kometa's poster first."""
    task = await _task_or_404(task_id)
    groups = ((task.get('progress') or {}).get('kometa_keys')) or {}
    payload = task.get('payload') or {}
    imdb = task['kind'] in ('imdb', 'selected_imdb') or payload.get('operation') == 'imdb_overlay'
    started = []
    for library, keys in groups.items():
        if keys:
            started.append(await tasks.enqueue('process', ProcessRequest(
                library_name=library, rating_keys=keys, reset_kometa=True, force=imdb,
                operation='imdb_overlay' if imdb else None, use_imdb_cache=imdb).model_dump()))
    if not started:
        raise HTTPException(400, 'Keine wegen Kometa übersprungenen Einträge gespeichert')
    return {'status': 'started', 'task_id': started[-1], 'task_ids': started,
            'items': sum(len(keys) for keys in groups.values())}
