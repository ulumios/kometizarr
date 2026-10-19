"""Durable task queue access and the single worker that runs every task kind."""

import asyncio
import logging

from src.services.progress import progress, publish

logger = logging.getLogger('kometizarr')

HANDLERS = {}  # kind -> async fn(task) returning an error string or None


def handler(kind):
    def register(fn):
        HANDLERS[kind] = fn
        return fn
    return register


def with_tasks(action, *args):
    from src.rating_overlay.task_queue import TaskQueue
    queue = TaskQueue()
    try:
        return getattr(queue, action)(*args)
    finally:
        queue.close()


async def enqueue(kind, payload):
    return await asyncio.to_thread(with_tasks, 'add', kind, payload)


async def run_task(task):
    progress.reset(task['id'], task['kind'], library=_library_of(task['payload']))
    await publish(force=True)
    run = HANDLERS.get(task['kind'])
    try:
        error = await run(task) if run else f"Unbekannter Auftrag: {task['kind']}"
    except Exception as exc:
        logger.exception('Task %s failed', task['id'])
        error = str(exc)
    progress.finish(error)
    await publish(force=True)
    await asyncio.to_thread(with_tasks, 'finish', task['id'], error)
    return error


async def worker():
    await asyncio.to_thread(with_tasks, 'resume')
    while True:
        try:
            task = await asyncio.to_thread(with_tasks, 'claim')
            if task is None:
                await asyncio.sleep(2)
                continue
            await run_task(task)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception('Task worker error')
            await asyncio.sleep(3)


def _library_of(payload):
    if not isinstance(payload, dict):
        return None
    return payload.get('library_name') or payload.get('library') or (
        ', '.join(payload['library_names']) if payload.get('library_names') else None)
