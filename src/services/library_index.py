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


def read_library_index(library_name, parent_key, episodes, q, page, page_size, conflicts_only=False):
    from src.rating_overlay.media_index import MediaIndex
    index = MediaIndex()
    try:
        updated_at, _ = index.snapshot(library_name, 'browse')
        result = index.browse(library_name, parent_key, episodes, q, page, page_size,
                              conflicts_only=conflicts_only) if updated_at else {
            'total': 0, 'page': page, 'items': []}
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
        progress.update(phase='Speichere Bibliothek', scanned=0, total=len(items))
    index = MediaIndex()
    try:
        index.replace_library(library_name, items, progress)
    finally:
        index.close()


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
            index.upsert_item(library_name, ancestor)
        index.upsert_item(library_name, item)
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
