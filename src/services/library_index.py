"""Persistent library index for browsing, plus the poster cache it serves."""

import asyncio
import logging
import time

from src.services import config

logger = logging.getLogger('kometizarr')

# Short-lived image cache; browser entries live in persistent SQLite.
browse_image_cache = {}
# Library scans read Plex only and run beside the task worker.
scans = {}


def task_outcomes(task):
    """{rating key: reason or None} of everything a task touched: the selection it was
    started with, per-item results, failed items and items skipped for Kometa."""
    outcomes = {}
    payload = task.get('payload') or {}
    for source in (payload, payload.get('request') or {}):
        for key in source.get('rating_keys') or []:
            outcomes[str(key)] = None
        for name in ('rating_key', 'key'):
            if source.get(name):
                outcomes[str(source[name])] = None
    progress = task.get('progress') or {}
    for key in progress.get('failed_keys') or []:
        outcomes[str(key)] = 'fehlgeschlagen'
    for keys in (progress.get('kometa_keys') or {}).values():
        for key in keys:
            outcomes[str(key)] = 'Kometa erkannt'
    results = task.get('results')
    if isinstance(results, dict):
        outcomes.update({str(key): reason for key, reason in results.items()})
    elif isinstance(results, list):  # IMDb runs keep a log per item
        for row in results:
            if isinstance(row, dict) and row.get('key'):
                outcomes[str(row['key'])] = row.get('render') or (
                    'IMDb-Wertung geändert' if row.get('changed') else 'IMDb unverändert')
    return outcomes


def task_items(task, limit=500):
    """Touched items with titles and the show/season path for the library browser."""
    from src.rating_overlay.media_index import MediaIndex
    outcomes = task_outcomes(task)
    index = MediaIndex()
    try:
        rows = index.describe(list(outcomes)[:limit])
        for row in rows:
            row['result'] = outcomes[row['key']]
            row['path'] = index.ancestors(row['library'], row['key'])
    finally:
        index.close()
    def order(row):
        # movies by title; shows, then their seasons, then the episodes of each season
        show = row['series'] or (row['path'][0]['title'] if row['path'] else row['title']) or ''
        season = row['season'] if row['type'] == 'episode' else row['index'] if row['type'] == 'season' else -1
        return (row['library'], show.lower(), season or 0, row['type'] == 'episode', row['index'] or 0, row['title'] or '')
    rows.sort(key=order)
    return {'items': rows, 'total': len(outcomes), 'missing': max(0, min(len(outcomes), limit) - len(rows))}


def read_library_index(library_name, parent_key, episodes, q, page, page_size, conflicts_only=False,
                       missing_overlay=False, task_ids=(), errors_only=False):
    from src.rating_overlay.media_index import MediaIndex
    from src.services import tasks
    index = MediaIndex()
    try:
        updated_at, _ = index.snapshot(library_name, 'browse')
        only_keys, outcomes = None, {}
        if task_ids:
            for task_id in task_ids:
                task = tasks.with_tasks('fetch', task_id)
                if task:
                    outcomes.update({key: reason for key, reason in task_outcomes(task).items()
                                     if reason is not None or key not in outcomes})
            only_keys = index.related_keys(library_name, list(outcomes))
        result = index.browse(library_name, parent_key, episodes, q, page, page_size,
                              conflicts_only=conflicts_only, missing_overlay=missing_overlay,
                              only_keys=only_keys, errors_only=errors_only) if updated_at else {
            'total': 0, 'page': page, 'items': []}
        errors = index.errors(library_name, [item['key'] for item in result['items']])
        for item in result['items']:
            if outcomes.get(item['key']):
                item['result'] = outcomes[item['key']]
            if item['key'] in errors:
                item['error'] = errors[item['key']]
        # The overlay filter needs one scan after this feature was installed
        result['overlay_flags_ready'] = index.flags_ready(library_name)
        return updated_at, result
    finally:
        index.close()


def refresh_library_index(library_name, progress=None):
    from src.rating_overlay.media_index import MediaIndex
    library = config.plex_server().library.section(library_name)
    if library.type not in ('movie', 'show'):
        raise ValueError('Only movie and show libraries are supported')
    kinds = [None] if library.type == 'movie' else [None, 'season', 'episode']
    items = []
    if progress is not None:
        progress.update(phase='Lese Plex', scanned=0, total=0, sections_done=0,
                        sections_total=len(kinds))
    for kind in kinds:
        items.extend(library.all(libtype=kind) if kind else library.all())
        if progress is not None:
            progress.update(sections_done=progress['sections_done'] + 1,
                            scanned=len(items), total=len(items),
                            phase=f'Plex gelesen: {len(items)} Einträge')
    if progress is not None:
        progress.update(phase='Prüfe Overlays und Kometa-Labels', scanned=0, total=len(items))
    flags = overlay_flags(library, library_name, kinds)
    if progress is not None:
        progress.update(phase='Speichere Bibliothek', scanned=0, total=len(items))
    index = MediaIndex()
    try:
        index.replace_library(library_name, items, progress, flags=flags)
    finally:
        index.close()


def overlay_flags(library, library_name, kinds):
    """(has_overlay, kometa_label) per item for the "ohne Overlay" filter.

    Kometa labels come from one label search per type instead of reading every item."""
    from src.rating_overlay.backup_manager import PosterBackupManager
    from src.rating_overlay.kometa_conflicts import KOMETA_LABEL
    labelled = set()
    for kind in kinds:
        libtype = kind or library.type
        try:
            labelled.update(str(item.ratingKey) for item in library.search(libtype=libtype, label=KOMETA_LABEL))
        except Exception:
            logger.exception('Kometa label search failed for %s', libtype)
    backups = PosterBackupManager(str(config.BACKUP_DIR))

    def flags(item):
        if item.type not in ('movie', 'show', 'episode'):
            return None, None
        return int(backups.has_overlay(library_name, item)), int(str(item.ratingKey) in labelled)
    return flags


def set_flags(library_name, rating_key, **flags):
    """Update the overlay filter flags of one indexed item; never breaks a run."""
    from src.rating_overlay.media_index import MediaIndex
    try:
        index = MediaIndex()
        try:
            index.set_flags(library_name, rating_key, **flags)
        finally:
            index.close()
    except Exception:
        logger.exception('Could not update overlay flags for %s', rating_key)


def index_new_item(library_name, item):
    """Update one newly added media item without rescanning its library."""
    from src.rating_overlay.media_index import MediaIndex
    index = MediaIndex()
    try:
        if not index.snapshot(library_name, 'browse')[0]:
            return
        ancestors = []
        parent_key = getattr(item, 'parentRatingKey', None)
        if parent_key and not index.has_item(library_name, parent_key):
            parent = item.parent()
            ancestors.append(parent)
            grandparent_key = getattr(parent, 'parentRatingKey', None)
            if grandparent_key and not index.has_item(library_name, grandparent_key):
                ancestors.append(parent.parent())
        for ancestor in reversed(ancestors):
            index.upsert_item(library_name, ancestor, has_overlay=None)
        from src.rating_overlay.kometa_conflicts import has_overlay_label
        index.upsert_item(library_name, item, has_overlay=0, kometa_label=int(has_overlay_label(item)))
    finally:
        index.close()


async def run_library_index_scan(library_name):
    try:
        await asyncio.to_thread(refresh_library_index, library_name, scans[library_name])
        scans[library_name]['error'] = None
    except Exception as exc:
        logger.exception('Library index refresh failed for %s', library_name)
        scans[library_name]['error'] = str(exc)
    finally:
        scans[library_name]['is_running'] = False
        scans[library_name]['finished_at'] = time.time()


def invalidate_browse_poster(library, rating_key):
    browse_image_cache.pop((library, str(rating_key)), None)
    try:
        from src.rating_overlay.media_index import MediaIndex
        index = MediaIndex()
        try:
            index.invalidate_artwork(library, rating_key)
            index.update_thumb(library, rating_key, None)
        finally:
            index.close()
    except Exception:
        logger.exception('Could not invalidate indexed poster for %s', rating_key)


def cache_backup_artwork(library, item, backups, overlaid):
    """Serve newly saved image bytes without another Plex request."""
    try:
        from src.rating_overlay.media_index import MediaIndex
        from src.rating_overlay.poster_storage import paths
        original, overlay = paths(backups, library, item)
        selected = overlay if overlaid else original
        if not selected.is_file():
            return
        from PIL import Image
        with Image.open(selected) as image:
            mime = Image.MIME.get(image.format, 'image/jpeg')
        index = MediaIndex()
        try:
            index.store_artwork(library, item.ratingKey, selected.read_bytes(), mime,
                                getattr(item, 'thumb', None))
        finally:
            index.close()
    except Exception:
        logger.exception('Could not cache poster for %s/%s', library, item.ratingKey)


def start_scan(library_name):
    """Start a background scan unless one is already running; True when started."""
    state = scans.setdefault(library_name, {'is_running': False, 'error': None})
    if state.get('is_running'):
        return False
    state.update(is_running=True, error=None, scanned=0, total=0,
                 started_at=time.time(), finished_at=None)
    asyncio.create_task(run_library_index_scan(library_name))
    return True
