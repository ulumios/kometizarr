"""Kometa conflicts: items still carrying Kometa's Overlay label."""

import asyncio
import logging
import time

from src.services import config, library_index, tasks
from src.services.progress import progress

logger = logging.getLogger('kometizarr')

# library -> last conflict list shown in the UI (persisted in media_index)
snapshots = {}


def remember(library_name, item):
    """Persist a conflict discovered by a webhook or manual render."""
    from src.rating_overlay.media_index import MediaIndex
    index = MediaIndex()
    try:
        key = str(item.ratingKey)
        entry = {'key': key, 'title': item.title, 'type': item.type,
                 'year': getattr(item, 'year', None),
                 'series': getattr(item, 'grandparentTitle', None),
                 'season': getattr(item, 'parentIndex', None),
                 'episode': getattr(item, 'index', None),
                 'has_kometizarr_overlay': False, 'pending_manual': False,
                 'manual_ready': False}
        index.record_conflict(library_name, item, entry)
        snapshots.pop(library_name, None)
    finally:
        index.close()


def forget(library_name, rating_key):
    """Remove a resolved conflict from the persistent local snapshot."""
    from src.rating_overlay.media_index import MediaIndex
    index = MediaIndex()
    try:
        index.forget_conflict(library_name, rating_key)
        # Conflicts are resolved by removing Kometa's label (render or reset)
        index.set_flags(library_name, rating_key, kometa_label=False)
        snapshots.pop(library_name, None)
    finally:
        index.close()


def is_recorded(library_name, item):
    from src.rating_overlay.media_index import MediaIndex
    index = MediaIndex()
    try:
        return index.has_conflict(library_name, item.ratingKey)
    finally:
        index.close()


async def run_scan(library_name):
    state = snapshots[library_name]
    try:
        state['items'] = await asyncio.to_thread(scan_library, library_name, state)
        from src.rating_overlay.media_index import MediaIndex
        def save():
            index = MediaIndex()
            try:
                for entry in state['items']:
                    item = type('ConflictItem', (), {
                        'ratingKey': entry['key'], 'title': entry['title'],
                        'type': entry['type'], 'grandparentRatingKey': None,
                        'parentRatingKey': None})()
                    index.record_conflict(library_name, item, entry)
            finally:
                index.close()
        await asyncio.to_thread(save)
        state['updated_at'] = time.time()
        state['error'] = None
    except Exception as exc:
        logger.exception('Conflict scan failed for %s', library_name)
        state['error'] = str(exc)
        state['updated_at'] = time.time()
    finally:
        if not state['error']:
            state.update(phase='Abgeschlossen', percent=100)
        state['is_running'] = False


def scan_library(library_name, progress=None):
    from plexapi.exceptions import NotFound
    from src.rating_overlay.backup_manager import PosterBackupManager
    from src.rating_overlay.kometa_conflicts import (
        KOMETA_LABEL, ManualPosterQueue, has_overlay_label, has_kometizarr_overlay)
    from src.rating_overlay.media_index import MediaIndex
    library = config.plex_server().library.section(library_name)
    if library.type not in ('movie', 'show'):
        raise ValueError('Only movie and series libraries are supported')
    backups = PosterBackupManager(backup_dir=str(config.BACKUP_DIR))
    queue = ManualPosterQueue()
    pending_keys = set(queue.keys(library_name))
    found = {}
    kinds = ('movie',) if library.type == 'movie' else ('show', 'episode')
    for position, kind in enumerate(kinds):
        if progress is not None:
            progress.update(phase=f'Suche {"Filme" if kind == "movie" else "Serien" if kind == "show" else "Episoden"}',
                            percent=int(50 * position / len(kinds)))
        try:
            items = library.search(libtype=kind, label=KOMETA_LABEL)
        except Exception as exc:
            raise RuntimeError(f'Plex-Labelsuche für {kind} fehlgeschlagen: {exc}') from exc
        for item in items:
            try:
                if has_overlay_label(item):
                    found[str(item.ratingKey)] = item
            except NotFound:
                if progress is not None:
                    progress['skipped'] += 1
                logger.info('Plex item disappeared during conflict scan: %s', item.ratingKey)
        if progress is not None:
            progress['percent'] = int(50 * (position + 1) / len(kinds))
    for key in pending_keys:
        if key not in found:
            try:
                found[key] = library.fetchItem(int(key))
            except NotFound:
                queue.remove(library_name, type('RemovedItem', (), {'ratingKey': key})())
                if progress is not None:
                    progress['skipped'] += 1
                continue
            except Exception:
                logger.exception('Could not fetch pending Plex item %s', key)
                continue
    output = []
    index = MediaIndex()
    try:
        if progress is not None:
            progress.update(phase='Prüfe gefundene Einträge', total=len(found), processed=0)
        for item in found.values():
            try:
                manual_state = queue.state(library_name, item)
                pending = manual_state != 'none'
                label = has_overlay_label(item)
                if not label and not pending:
                    continue
                thumb = getattr(item, 'thumb', None)
                if thumb and index.has_item(library_name, item.ratingKey) and thumb != index.thumb(library_name, item.ratingKey):
                    index.update_thumb(library_name, item.ratingKey, thumb)
                    library_index.browse_image_cache.pop((library_name, str(item.ratingKey)), None)
                output.append({'key': str(item.ratingKey), 'title': item.title,
                               'type': item.type, 'year': getattr(item, 'year', None),
                               'series': getattr(item, 'grandparentTitle', None),
                               'season': getattr(item, 'parentIndex', None),
                               'episode': getattr(item, 'index', None),
                               'pending_manual': manual_state == 'waiting', 'manual_ready': manual_state == 'changed',
                               'has_label': label,
                               'has_kometizarr_overlay': has_kometizarr_overlay(backups, library_name, item)})
            except NotFound:
                if str(item.ratingKey) in pending_keys:
                    queue.remove(library_name, item)
                if progress is not None:
                    progress['skipped'] += 1
                logger.info('Plex item disappeared during conflict details: %s', item.ratingKey)
            finally:
                if progress is not None:
                    progress['processed'] += 1
                    progress['percent'] = min(99, 50 + int(49 * progress['processed'] / max(1, progress['total'])))
    finally:
        index.close()
    return sorted(output, key=lambda entry: (entry['series'] or entry['title'], entry['season'] or 0, entry['episode'] or 0))


async def get_conflicts(library_name, refresh=False):
    state = snapshots.get(library_name)
    if state is None:
        from src.rating_overlay.media_index import MediaIndex
        def load():
            index = MediaIndex()
            try:
                return time.time(), index.conflicts(library_name)
            finally:
                index.close()
        updated_at, items = await asyncio.to_thread(load)
        state = {'is_running': False, 'items': items or [], 'error': None, 'updated_at': updated_at,
                 'phase': 'Bereit', 'percent': 0, 'processed': 0, 'total': 0, 'skipped': 0}
        snapshots[library_name] = state
    for name, default in (('phase', 'Bereit'), ('percent', 0), ('processed', 0), ('total', 0), ('skipped', 0)):
        state.setdefault(name, default)
    # Konflikte werden beim Webhook oder Overlay-Lauf erkannt und als Snapshot
    # gespeichert. Nur „Aktualisieren“ (refresh) startet einen Plex-Scan.
    if refresh and not state['is_running']:
        state.update(is_running=True, error=None, phase='Startet', percent=0, processed=0,
                     total=0, skipped=0)
        asyncio.create_task(run_scan(library_name))
    return {'items': state['items'], 'is_running': state['is_running'], 'error': state['error'],
            'phase': state['phase'], 'percent': state['percent'], 'processed': state['processed'],
            'total': state['total'], 'skipped': state['skipped']}


def remove_labels(request):
    from src.rating_overlay.kometa_conflicts import KOMETA_LABEL, ManualPosterQueue, has_overlay_label
    library = config.plex_server().library.section(request.library_name)
    queue = ManualPosterQueue()
    items = config.selected_items(library, request.rating_keys)
    progress.total = len(items)
    for item in items:
        key = str(item.ratingKey)
        if not has_overlay_label(item):
            progress.count('skipped', key, 'kein Overlay-Label')
            continue
        try:
            queue.mark(request.library_name, item)
            item.removeLabel(KOMETA_LABEL)
            progress.count('success', key, 'Label entfernt · Poster in Plex wechseln')
        except Exception:
            queue.remove(request.library_name, item)
            progress.count('failed', key, 'Label konnte nicht entfernt werden')


@tasks.handler('conflict')
async def run_action(task):
    from src.services import overlay
    from src.services.models import ConflictAction, ProcessRequest
    request = ConflictAction(**task['payload'])
    progress.total = len(request.rating_keys)
    try:
        if request.action == 'remove_label':
            progress.phase = 'Kometa-Label entfernen'
            await asyncio.to_thread(remove_labels, request)
        else:
            progress.phase = 'Original wiederherstellen und Overlay rendern'
            await overlay.run_overlay(ProcessRequest(
                library_name=request.library_name, rating_keys=request.rating_keys,
                force=True, reset_kometa=True, record_results=True))
        progress.phase = 'Fehlgeschlagen' if progress.error else 'Abgeschlossen'
        return progress.error
    finally:
        snapshots.pop(request.library_name, None)
