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
