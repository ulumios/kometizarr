"""Maintenance: backup storage, orphaned backups and old poster uploads in Plex."""

import asyncio
import hashlib
import json
import logging
import shutil
from pathlib import Path

from src.rating_overlay.poster_storage import ORIGINAL, OVERLAY, backup_id, episode_code
from src.services import config, tasks
from src.services.progress import progress

logger = logging.getLogger('kometizarr')

MAX_LISTED = 500
DATA_FILES = {'media_index.sqlite3', 'tasks.sqlite3', 'imdb_ratings.sqlite3', 'poster_cache'}


def _size(path):
    if path.is_file():
        return path.stat().st_size
    return sum(f.stat().st_size for f in path.rglob('*') if f.is_file())


def overview():
    """Disk usage per library folder; reads the disk only."""
    root = config.BACKUP_DIR
    result = []
    if not root.is_dir():
        return {'libraries': result, 'total_bytes': 0}
    for folder in sorted(p for p in root.iterdir() if p.is_dir() and p.name not in DATA_FILES):
        files = [f for f in folder.rglob('*') if f.is_file()]
        result.append({'library': folder.name, 'bytes': sum(f.stat().st_size for f in files),
                       'originals': sum(1 for f in files if f.name in (ORIGINAL, 'poster_original.jpg')
                                        or f.name.endswith('-poster_original.jpg')),
                       'overlays': sum(1 for f in files if f.name in (OVERLAY, 'poster_overlay.jpg')
                                       or f.name.endswith('-poster_overlay.jpg'))})
    usage = shutil.disk_usage(root)
    return {'libraries': result, 'total_bytes': sum(entry['bytes'] for entry in result),
            'disk_free': usage.free, 'disk_total': usage.total}


def audit_library(library_name, items=None):
    """Backup folders without a matching Plex item (orphans) and unmigrated title folders.

    ``items`` defaults to every movie/show/episode of the library from Plex."""
    folder = config.backup_library_dir(library_name)
    if items is None:
        library = config.plex_server().library.section(library_name)
        items = library.all() + (library.all(libtype='episode') if library.type == 'show' else [])
    expected = {}  # backup_id -> set of episode codes
    show_ids = {}
    for item in items:
        if item.type in ('movie', 'show'):
            expected.setdefault(backup_id(item), set())
            show_ids[str(item.ratingKey)] = backup_id(item)
    for item in items:
        if item.type == 'episode':
            show = show_ids.get(str(getattr(item, 'grandparentRatingKey', '')))
            if show:
                expected.setdefault(show, set()).add(episode_code(item))
    current_keys = {str(item.ratingKey) for item in items}
    orphans, legacy = [], []
    checked = 0
    if folder.is_dir():
        for entry in sorted(p for p in folder.iterdir() if p.is_dir()):
            relative = entry.name
            if entry.name == 'episodes' or (entry / 'poster_original.jpg').exists() or \
                    any(entry.glob('S*E*-poster_original.jpg')):
                legacy.append({'path': relative, 'bytes': _size(entry)})
                continue
            checked += 1
            if entry.name not in expected:
                if _recorded_key(entry) not in current_keys:
                    orphans.append({'path': relative, 'bytes': _size(entry)})
                continue
            for child in sorted(p for p in entry.iterdir() if p.is_dir()):
                if child.name not in expected[entry.name]:
                    orphans.append({'path': f'{relative}/{child.name}', 'bytes': _size(child)})
    if checked > 20 and len(orphans) > checked / 2:
        # Guards against a Plex listing without external IDs marking everything as orphaned
        raise ValueError(f'Prüfung unplausibel: {len(orphans)} von {checked} Ordnern ohne Plex-Eintrag')
    return {'library': library_name, 'items': len(items),
            'orphans': orphans[:MAX_LISTED], 'orphan_count': len(orphans),
            'orphan_bytes': sum(o['bytes'] for o in orphans),
            'legacy': legacy[:MAX_LISTED], 'legacy_count': len(legacy)}


def _recorded_key(folder):
    try:
        return str(json.loads((folder / 'metadata.json').read_text()).get('rating_key'))
    except (OSError, ValueError, AttributeError):
        return None


def delete_orphans(library_name, paths):
    """Delete only paths that a fresh audit still reports as orphaned."""
    audit = audit_library(library_name)
    if audit['orphan_count'] > MAX_LISTED:
        raise ValueError('Zu viele verwaiste Ordner; bitte in Teilen löschen')
    allowed = {entry['path'] for entry in audit['orphans']}
    folder = config.backup_library_dir(library_name)
    deleted, freed = [], 0
    for relative in paths:
        if relative not in allowed:
            continue
        target = (folder / relative).resolve()
        if folder.resolve() not in target.parents:
            continue
        freed += _size(target)
        shutil.rmtree(target)
        deleted.append(relative)
        try:
            target.parent.rmdir()  # drop a show folder left empty
        except OSError:
            pass
    return {'deleted': deleted, 'freed_bytes': freed}


# ── Old uploads inside Plex's metadata bundles ───────────────────────────────

def plex_data_dir(settings):
    """The mounted "Plex Media Server" folder, if configured and present."""
    configured = (settings.get('maintenance') or {}).get('plex_data_dir') or '/plex'
    path = Path(configured)
    return path if (path / 'Metadata').is_dir() else None


def bundle_dir(base, item):
    """Same formula as plexapi's metadataDirectory: sha1 of the item's Plex GUID."""
    kind = 'Movies' if item.type == 'movie' else 'TV Shows'
    digest = hashlib.sha1(item.guid.encode('utf-8')).hexdigest()
    return base / 'Metadata' / kind / digest[0] / f'{digest[1:]}.bundle'


def stale_uploads(base, item):
    """Uploaded posters Plex lists for the item that are not selected and exist on disk."""
    uploads = bundle_dir(base, item) / 'Uploads' / 'posters'
    if not uploads.is_dir():
        return []
    found = []
    for poster in item.posters():
        key = str(getattr(poster, 'ratingKey', '') or '')
        if not key.startswith('upload://posters/') or getattr(poster, 'selected', False):
            continue
        path = uploads / key.rsplit('/', 1)[-1]
        if path.is_file() and path.parent == uploads:
            found.append(path)
    return found


@tasks.handler('backup_audit')
async def audit_task(task):
    libraries = task['payload'].get('libraries') or [entry['library'] for entry in overview()['libraries']]
    progress.total = len(libraries)
    reports = []
    for name in libraries:
        progress.phase = f'Prüfe {name}'
        progress.current = name
        try:
            reports.append(await asyncio.to_thread(audit_library, name))
        except Exception as exc:
            logger.exception('Backup audit failed for %s', name)
            reports.append({'library': name, 'error': str(exc)})
            progress.count('failed')
        progress.done += 1
        progress.extra['reports'] = reports
    progress.phase = 'Abgeschlossen'
    return None


@tasks.handler('backup_cleanup')
async def cleanup_task(task):
    payload = task['payload']
    progress.phase = f"Lösche verwaiste Backups in {payload['library']}"
    result = await asyncio.to_thread(delete_orphans, payload['library'], payload.get('paths') or [])
    progress.success = len(result['deleted'])
    progress.extra.update(result)
    progress.phase = 'Abgeschlossen'
    return None


@tasks.handler('plex_uploads')
async def plex_uploads_task(task):
    payload = task['payload']
    base = plex_data_dir(config.load_settings())
    if base is None:
        return 'Plex-Datenordner ist nicht eingebunden (/plex mit Unterordner Metadata)'
    dry_run = payload.get('dry_run', True)
    progress.phase = 'Trockenlauf' if dry_run else 'Alte Uploads löschen'
    found_files, found_bytes = 0, 0
    for name in payload['libraries']:
        library = await asyncio.to_thread(lambda: config.plex_server().library.section(name))
        items = await asyncio.to_thread(library.all)
        progress.begin_items('maintenance', total=len(items), library=name)
        for position, item in enumerate(items, 1):
            if progress.stop_requested:
                break
            progress.done, progress.current = position, item.title
            try:
                stale = await asyncio.to_thread(stale_uploads, base, item)
                for path in stale:
                    found_files += 1
                    found_bytes += path.stat().st_size
                    if not dry_run:
                        path.unlink()
                progress.count('success' if stale else 'skipped')
            except Exception:
                logger.exception('Could not inspect uploads of %s', item.ratingKey)
                progress.count('failed', item.ratingKey)
        progress.end_items()
    progress.extra.update(files=found_files, bytes=found_bytes, dry_run=dry_run)
    progress.phase = 'Abgeschlossen'
    return None


PLEX_ACTIONS = {'clean_bundles': 'cleanBundles', 'empty_trash': 'emptyTrash', 'optimize': 'optimize'}


@tasks.handler('plex_maintenance')
async def plex_maintenance_task(task):
    action = task['payload']['action']
    if action not in PLEX_ACTIONS:
        return f'Unbekannte Aktion: {action}'
    progress.phase = action
    await asyncio.to_thread(lambda: getattr(config.plex_server().library, PLEX_ACTIONS[action])())
    progress.phase = 'In Plex gestartet'
    return None
