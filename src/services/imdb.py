"""Direct IMDb ratings: refresh the dataset cache and re-render changed posters."""

import asyncio
import logging
from types import SimpleNamespace

from src.rating_overlay.poster_storage import external_ids
from src.services import config, overlay, tasks
from src.services.models import ProcessRequest, SelectedImdbRequest
from src.services.progress import progress

logger = logging.getLogger('kometizarr')


def external_imdb_id(guids):
    return external_ids(SimpleNamespace(guids=guids)).get('imdb')


def _start(phase):
    progress.phase = phase
    progress.percent = 0
    progress.extra.update(scanned=0, matched=0, changed=0, pending=0, rendered=0, failed=0, logs=[])


def collect_items(libraries):
    result = {}
    for library in config.plex_server().library.sections():
        if library.title not in libraries or library.type not in ('show', 'movie'):
            continue
        items = library.all()
        if library.type == 'show':
            items += library.all(libtype='episode')
        found = []
        for item in items:
            imdb_id = external_imdb_id(getattr(item, 'guids', []) or [])
            if imdb_id:
                found.append((str(item.ratingKey), imdb_id))
        result[library.title] = found
    return result


def download_progress(stage, done, total):
    if stage == 'download':
        progress.extra.update(bytes_downloaded=done, bytes_total=total)
    progress.percent = min(84, (25 if stage == 'download' else 60) +
                           int((35 if stage == 'download' else 25) * done / total)) if total else 25
    progress.phase = 'IMDb-Datensatz laden' if stage == 'download' else 'IMDb-Datensatz auswerten'


def resolve_selected(library_name, keys):
    library = config.plex_server().library.section(library_name)
    entries = []
    for item in config.selected_items(library, keys):
        title = item.title
        if item.type == 'episode':
            season = getattr(item, 'parentIndex', 0) or 0
            episode = getattr(item, 'index', 0) or 0
            title = f"{getattr(item, 'grandparentTitle', '')} S{season:02d}E{episode:02d} · {title}"
        entries.append({'key': str(item.ratingKey), 'title': title, 'type': item.type,
                        'imdb_id': external_imdb_id(getattr(item, 'guids', []) or [])})
    return entries


async def run_selected(library_name, request):
    from src.rating_overlay.imdb_cache import ImdbRatingCache
    cache = None
    try:
        selected = await asyncio.to_thread(resolve_selected, library_name, request.rating_keys)
        progress.extra['scanned'] = len(selected)
        ids = {entry['imdb_id'] for entry in selected if entry['imdb_id']}
        cache = ImdbRatingCache()
        previous = cache.ratings(ids)
        progress.phase = 'IMDb-Wertungen laden'
        fetched = await asyncio.to_thread(cache.refresh, ids, download_progress) if ids else {}
        progress.extra['matched'] = len(fetched)
        progress.extra['updated_at'] = cache.updated_at()
        logs = []
        for entry in selected:
            imdb_id = entry['imdb_id']
            current = fetched.get(imdb_id)
            old = previous.get(imdb_id)
            changed = current is not None and old is not None and current != old
            if changed:
                progress.extra['changed'] += 1
            logs.append({'key': entry['key'], 'title': entry['title'], 'type': entry['type'],
                         'imdb_id': imdb_id, 'previous': old, 'rating': current,
                         'changed': changed, 'render': 'ausstehend' if request.mode == 'both' else None})
        progress.extra['logs'] = logs
        cache.close()
        cache = None
        progress.percent = 85
        if request.mode == 'both':
            settings = config.load_settings()
            progress.phase = 'Poster rendern'
            await overlay.run_overlay(ProcessRequest(
                library_name=library_name, rating_keys=request.rating_keys, force=True,
                operation='imdb_overlay',
                use_imdb_cache=True, record_results=True,
                rating_sources={**(config.design_for(settings, library_name)['rating_sources']
                                   or config.DEFAULT_RATING_SOURCES), 'imdb': True}))
            results = dict(progress.results)
            for row in logs:
                row['render'] = results.get(row['key'], 'fehlgeschlagen')
            progress.extra['rendered'] += progress.success
            progress.extra['failed'] += progress.failed
            if progress.error:
                raise RuntimeError(progress.error)
        progress.phase = 'Teilweise fehlgeschlagen' if progress.extra.get('failed') else 'Abgeschlossen'
        progress.percent = 100
    except Exception as exc:
        progress.error = str(exc)
        progress.phase = 'Fehlgeschlagen'
        logger.exception('Selected IMDb refresh failed')
    finally:
        if cache:
            cache.close()


async def run_sync(mode='both'):
    from src.rating_overlay.imdb_cache import ImdbRatingCache
    cache = None
    try:
        settings = config.load_settings()
        server = await asyncio.to_thread(config.plex_server)
        configured = settings['imdb_direct'].get('libraries') or [lib.title for lib in server.library.sections()]
        targets = await asyncio.to_thread(collect_items, configured)
        progress.extra['scanned'] = sum(len(items) for items in targets.values())
        ids = {imdb_id for items in targets.values() for _, imdb_id in items}
        if not ids:
            raise ValueError('No Plex items with an IMDb ID found')
        progress.phase = 'Downloading IMDb ratings'
        cache = ImdbRatingCache()
        before = cache.ratings(ids)
        fetched = await asyncio.to_thread(cache.refresh, ids, download_progress)
        progress.extra['matched'] = len(fetched)
        progress.percent = 85
        progress.extra['updated_at'] = cache.updated_at()
        # Close before handing processing to another thread/connection.
        changed = {}
        for name, items in targets.items():
            changed[name] = [key for key, imdb_id in items if imdb_id in fetched and
                             cache.applied(name, key) != (imdb_id, fetched[imdb_id])]
        progress.extra['changed'] = sum(before[imdb_id] != rating for imdb_id, rating in fetched.items()
                                         if imdb_id in before)
        progress.extra['pending'] = sum(len(keys) for keys in changed.values())
        cache.close()
        cache = None
        for library_name, keys in (changed.items() if mode == 'both' else []):
            if not keys:
                continue
            progress.phase = f'Rendering {library_name}'
            await overlay.run_overlay(ProcessRequest(
                library_name=library_name, rating_keys=keys, force=True,
                operation='imdb_overlay', use_imdb_cache=True))
            progress.extra['rendered'] += progress.success
            progress.extra['failed'] += progress.failed
            if progress.error:
                raise RuntimeError(f"{library_name}: {progress.error}")
        progress.phase = 'Complete'
        progress.percent = 100
    except Exception as exc:
        progress.error = str(exc)
        progress.phase = 'Failed'
        logger.exception('IMDb refresh failed')
    finally:
        if cache:
            cache.close()


@tasks.handler('imdb')
async def imdb_task(task):
    _start('Lese Plex')
    await run_sync(task['payload'].get('mode', 'both'))
    return progress.error


@tasks.handler('selected_imdb')
async def selected_imdb_task(task):
    _start('Lese Auswahl')
    progress.library = task['payload']['library']
    await run_selected(task['payload']['library'], SelectedImdbRequest(**task['payload']['request']))
    if progress.error:
        return progress.error
    return f"{progress.extra['failed']} Poster fehlgeschlagen" if progress.extra['failed'] else None
