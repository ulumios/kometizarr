"""One progress model for whatever the worker runs (docs/KONZEPT.md, section 3).

``progress`` is the single source of truth. It is persisted to the task table, pushed to
WebSocket clients and rendered into the older status shapes the UI still reads."""

import asyncio
import time
from datetime import datetime

COUNTERS = ('done', 'total', 'success', 'failed', 'skipped')
MAX_FAILED_KEYS = 2000
RESTORE_KINDS = ('restore', 'fresh_posters')
IMDB_KINDS = ('imdb', 'selected_imdb')


class RunProgress:
    def __init__(self):
        self.history = {}  # kind -> last finished snapshot
        self.reset()

    def reset(self, task_id=None, kind=None, library=None, phase=''):
        self.task_id, self.kind, self.library, self.phase = task_id, kind, library, phase
        self.running = task_id is not None
        self.stop_requested = False
        self.items_kind = None       # 'process' or 'restore' while an item loop runs
        self.force_mode = False
        self.current = None
        self.results = {}
        self.failed_keys = []        # for "retry failed"; survives nested item loops
        self.kometa_keys = {}        # library -> keys skipped for Kometa, offered for a reset
        self.error = None
        self.percent = None          # explicit percentage for phases without items
        self.extra = {}              # task specific numbers (IMDb: scanned, matched, …)
        self.started_at = time.time()
        self.items_started_at = datetime.now()
        for name in COUNTERS:
            setattr(self, name, 0)

    def begin_items(self, items_kind, total=0, library=None):
        """Start an item loop; nested loops (IMDb → render) restart only the counters."""
        self.items_kind = items_kind
        self.library = library or self.library
        self.items_started_at = datetime.now()
        self.error = None
        self.current = None
        for name in COUNTERS:
            setattr(self, name, 0)
        self.total = total

    def end_items(self):
        self.items_kind = None
        self.current = None

    def count(self, counter, key=None, reason=None):
        setattr(self, counter, getattr(self, counter) + 1)
        if key is not None and counter == 'failed' and len(self.failed_keys) < MAX_FAILED_KEYS:
            self.failed_keys.append(str(key))
        if key is not None and reason is not None:
            self.results[str(key)] = reason

    def kometa_skipped(self, library, key):
        keys = self.kometa_keys.setdefault(library, [])
        if len(keys) < MAX_FAILED_KEYS and str(key) not in keys:
            keys.append(str(key))

    def finish(self, error=None):
        self.error = error or self.error
        self.running = False
        self.items_kind = None
        self.stop_requested = False
        if self.kind:
            self.history[self.kind] = self.snapshot()

    def computed_percent(self):
        if self.percent is not None:
            return self.percent
        return int(self.done * 100 / self.total) if self.total else 0

    def snapshot(self):
        return {'task_id': self.task_id, 'kind': self.kind, 'library': self.library,
                'phase': self.phase, 'running': self.running, 'items_kind': self.items_kind,
                'done': self.done, 'total': self.total, 'success': self.success,
                'failed': self.failed, 'skipped': self.skipped, 'current': self.current,
                'percent': self.computed_percent(), 'error': self.error,
                'stop_requested': self.stop_requested, 'started_at': self.started_at,
                'extra': dict(self.extra), 'results': dict(self.results),
                'failed_keys': list(self.failed_keys),
                'kometa_keys': {library: list(keys) for library, keys in self.kometa_keys.items()}}

    # ── Views in the shape the existing UI components read ────────────────────

    def _last(self, kinds):
        if self.kind in kinds and (self.running or not self.history.get(self.kind)):
            return self.snapshot()
        finished = [self.history[kind] for kind in kinds if kind in self.history]
        return max(finished, key=lambda snap: snap['started_at']) if finished else None

    def processing_view(self):
        active = self.running and self.items_kind == 'process'
        snap = self.snapshot()
        view = {'is_processing': active, 'current_library': snap['library'], 'progress': snap['done'],
                'total': snap['total'], 'success': snap['success'], 'failed': snap['failed'],
                'skipped': snap['skipped'], 'current_item': snap['current'],
                'stop_requested': snap['stop_requested'], 'force_mode': self.force_mode,
                # per-item results stay in the task list; the live view is sent after every item
                'task': {key: value for key, value in snap.items() if key != 'results'}}
        if snap['error']:
            view['error'] = snap['error']
        return view

    def restore_view(self):
        snap = self.snapshot() if self.items_kind == 'restore' or self.kind in RESTORE_KINDS \
            else (self._last(RESTORE_KINDS) or self.snapshot())
        view = {'is_restoring': self.running and self.items_kind == 'restore',
                'current_library': snap['library'], 'progress': snap['done'], 'total': snap['total'],
                'restored': snap['success'], 'failed': snap['failed'], 'skipped': snap['skipped'],
                'current_item': snap['current'], 'stop_requested': snap['stop_requested'], 'task': snap}
        if snap['error']:
            view['error'] = snap['error']
        return view

    def live_view(self):
        """What the progress banner shows: the running item loop, restore or render."""
        restoring = self.items_kind == 'restore' or (self.items_kind is None and self.kind in RESTORE_KINDS)
        return self.restore_view() if restoring else self.processing_view()

    def imdb_view(self):
        snap = self._last(IMDB_KINDS)
        base = {'is_running': False, 'phase': 'idle', 'scanned': 0, 'matched': 0, 'changed': 0,
                'pending': 0, 'rendered': 0, 'failed': 0, 'error': None, 'updated_at': None,
                'logs': [], 'percent': 0}
        if not snap:
            return base
        rendering = snap['items_kind'] == 'process' and snap['total']
        percent = (min(99, 85 + int(15 * snap['done'] / snap['total'])) if rendering and snap['running']
                   else snap['percent'])
        return {**base, **snap['extra'], 'is_running': snap['running'], 'phase': snap['phase'],
                'error': snap['error'], 'percent': percent, 'library': snap['library'],
                'task_id': snap['task_id'], 'kometa_keys': snap['kometa_keys'],
                'rendered': snap['extra'].get('rendered', 0) + (snap['success'] if rendering and snap['running'] else 0),
                'failed': snap['extra'].get('failed', 0) + (snap['failed'] if rendering and snap['running'] else 0)}

    def conflict_view(self):
        snap = self._last(('conflict',))
        if not snap:
            return {'is_running': False, 'phase': 'idle', 'total': 0, 'resolved': 0, 'skipped': 0,
                    'failed': 0, 'error': None, 'results': {}}
        return {'is_running': snap['running'], 'phase': snap['phase'], 'total': snap['total'],
                'resolved': snap['success'], 'skipped': snap['skipped'], 'failed': snap['failed'],
                'error': snap['error'], 'results': snap['results']}


progress = RunProgress()

# ── Publishing: task table (throttled) and WebSocket clients ─────────────────

connections = []
_last_write = 0.0
_last_result_count = 0


async def publish(force=False):
    """Persist the active task's progress and push the live view to every client."""
    global _last_write, _last_result_count
    from src.services import tasks
    result_count = len(progress.results)
    # Results grow with every item; writing them at most once a second keeps large runs cheap
    if progress.task_id and (force or time.monotonic() - _last_write > 1 or not progress.running
                             or (result_count != _last_result_count and result_count < 50)):
        snap = progress.snapshot()
        await asyncio.to_thread(
            tasks.with_tasks, 'update_progress', progress.task_id,
            {**{key: snap[key] for key in ('done', 'total', 'success', 'failed', 'skipped',
                                           'current', 'phase', 'percent', 'failed_keys', 'kometa_keys')},
             'library': snap['library'],
             'extra': {key: value for key, value in snap['extra'].items() if key != 'logs'}},
            progress.extra.get('logs') if progress.kind in IMDB_KINDS else (progress.results or None))
        _last_write = time.monotonic()
        _last_result_count = result_count
    view = progress.live_view()
    for connection in list(connections):
        try:
            await connection.send_json(view)
        except Exception:
            if connection in connections:
                connections.remove(connection)
