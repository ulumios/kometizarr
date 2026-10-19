"""Status page: is everything Kometizarr depends on reachable and configured?"""

import os
import shutil
import time
from collections import deque
from datetime import datetime, timezone

import requests

from src.services import config

CACHE_SECONDS = 300
TIMEOUT = 8
_cache = {'at': 0.0, 'checks': None}

# Most recent webhook calls, newest first (in memory; reset on restart)
webhook_events = deque(maxlen=20)


def record_webhook(source, event, status, library=None, title=None):
    webhook_events.appendleft({'at': time.time(), 'source': source, 'event': event,
                               'status': status, 'library': library, 'title': title})


def _check(name, fn):
    started = time.monotonic()
    try:
        state, detail = fn()
    except Exception as exc:
        state, detail = 'error', str(exc)[:200]
    return {'name': name, 'state': state, 'detail': detail,
            'ms': int((time.monotonic() - started) * 1000)}


def _plex():
    if not os.getenv('PLEX_URL') or not os.getenv('PLEX_TOKEN'):
        return 'error', 'PLEX_URL oder PLEX_TOKEN fehlt'
    server = config.plex_server()
    return 'ok', f'{server.friendlyName} · Version {server.version}'


def _tmdb():
    key = os.getenv('TMDB_API_KEY')
    if not key:
        return 'missing', 'Kein TMDB_API_KEY (Wertungen kommen dann nur aus Plex)'
    response = requests.get('https://api.themoviedb.org/3/configuration', params={'api_key': key}, timeout=TIMEOUT)
    return ('ok', 'Schlüssel gültig') if response.ok else ('error', f'HTTP {response.status_code}')


def _omdb():
    key = os.getenv('OMDB_API_KEY')
    if not key:
        return 'missing', 'Optional, nicht gesetzt'
    data = requests.get('https://www.omdbapi.com/', params={'i': 'tt0111161', 'apikey': key}, timeout=TIMEOUT).json()
    return ('ok', 'Schlüssel gültig') if data.get('Response') == 'True' else ('error', data.get('Error', 'Unbekannt'))


def _mdblist():
    key = os.getenv('MDBLIST_API_KEY')
    if not key:
        return 'missing', 'Optional, nicht gesetzt'
    data = requests.get('https://mdblist.com/api/', params={'apikey': key, 'i': 'tt0111161'}, timeout=TIMEOUT).json()
    return ('error', str(data.get('error'))) if data.get('error') else ('ok', 'Schlüssel gültig')


def _imdb_dataset(settings):
    if not (settings.get('imdb_direct') or {}).get('enabled'):
        return 'missing', 'Direkte IMDb-Wertungen sind ausgeschaltet'
    from src.rating_overlay.imdb_cache import ImdbRatingCache
    cache = ImdbRatingCache()
    try:
        updated = cache.updated_at()
    finally:
        cache.close()
    if not updated:
        return 'warning', 'Noch nie geladen'
    age = datetime.now(timezone.utc) - datetime.fromisoformat(updated)
    days = age.total_seconds() / 86400
    return ('ok' if days < 3 else 'warning'), f'Stand {updated[:16].replace("T", " ")} ({days:.1f} Tage alt)'


def _disk():
    usage = shutil.disk_usage(config.BACKUP_DIR)
    free = usage.free / usage.total
    detail = f'{usage.free / 1024 ** 3:.1f} GB von {usage.total / 1024 ** 3:.1f} GB frei'
    return ('ok' if free > 0.1 else 'warning' if free > 0.03 else 'error'), detail


def _mounts(settings):
    from src.rating_overlay.kometa_originals import overlays_dir
    from src.services.maintenance import plex_data_dir
    kometa, plex = overlays_dir(settings), plex_data_dir(settings)
    return [
        {'name': 'Kometa-Originale', 'state': 'ok' if kometa else 'missing',
         'detail': str(kometa) if kometa else 'Nicht eingebunden (optional, /kometa)'},
        {'name': 'Plex-Datenordner', 'state': 'ok' if plex else 'missing',
         'detail': str(plex) if plex else 'Nicht eingebunden (optional, /plex)'},
    ]


def external_checks(refresh=False):
    if refresh or _cache['checks'] is None or time.time() - _cache['at'] > CACHE_SECONDS:
        settings = config.load_settings()
        _cache['checks'] = [_check('Plex', _plex), _check('TMDB', _tmdb), _check('OMDb', _omdb),
                            _check('MDBList', _mdblist),
                            _check('IMDb-Datensatz', lambda: _imdb_dataset(settings))]
        _cache['at'] = time.time()
    return _cache['checks'], _cache['at']


def report(refresh=False):
    from src.services import schedule, tasks
    from src.services.progress import progress
    settings = config.load_settings()
    checks, checked_at = external_checks(refresh)
    rows = tasks.with_tasks('list', 100)
    day_ago = time.time() - 86400
    return {
        'checks': checks + [_check('Speicherplatz /backups', _disk)] + _mounts(settings),
        'checked_at': checked_at,
        'queue': {'queued': tasks.with_tasks('queued_count'),
                  'running': progress.snapshot() if progress.running else None,
                  'failed_24h': sum(1 for row in rows if row['status'] == 'failed' and row['updated_at'] > day_ago),
                  'completed_24h': sum(1 for row in rows if row['status'] == 'completed' and row['updated_at'] > day_ago)},
        'schedule': {**schedule.next_runs(),
                     'imdb_refresh': _next_run(schedule.scheduler.get_job('imdb_refresh'))},
        'webhooks': list(webhook_events),
    }


def _next_run(job):
    return job.next_run_time.isoformat() if job and job.next_run_time else None
