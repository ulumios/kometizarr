"""Backup layout by stable media ID and safe replacement of Plex artwork backups.

Layout::

    <backup_dir>/<library>/<backup_id>/original.jpg | overlay.jpg | metadata.json
    <backup_dir>/<library>/<show_backup_id>/S01E02/original.jpg | overlay.jpg

``backup_id`` is the IMDb ID, else ``tmdb-<id>``, ``tvdb-<id>`` or ``plex-<ratingKey>``.
Backups written by older versions (title/year folders) are moved here on first access.
"""

import json
import logging
import os
import tempfile
from pathlib import Path

from PIL import Image

logger = logging.getLogger(__name__)

ORIGINAL = 'original.jpg'
OVERLAY = 'overlay.jpg'
METADATA = 'metadata.json'

# grandparentRatingKey -> show backup_id; avoids one Plex request per episode
_show_ids = {}


def external_ids(item):
    """Return {'imdb': 'tt…', 'tmdb': '603', 'tvdb': '…'} from Plex GUIDs."""
    ids = {}
    for guid in getattr(item, 'guids', None) or []:
        value = str(getattr(guid, 'id', guid))
        scheme, _, rest = value.partition('://')
        if scheme in ('imdb', 'tmdb', 'tvdb') and rest and scheme not in ids:
            ids[scheme] = rest
    return ids


def backup_id(item):
    ids = external_ids(item)
    if ids.get('imdb'):
        return ids['imdb']
    for scheme in ('tmdb', 'tvdb'):
        if ids.get(scheme):
            return f'{scheme}-{ids[scheme]}'
    return f'plex-{item.ratingKey}'


def show_backup_id(episode):
    key = getattr(episode, 'grandparentRatingKey', None)
    if key is None:
        return 'plex-unknown-show'
    key = str(key)
    if key not in _show_ids:
        try:
            _show_ids[key] = backup_id(episode.show())
        except Exception:
            _show_ids[key] = f'plex-{key}'
    return _show_ids[key]


def episode_code(item):
    season = int(getattr(item, 'parentIndex', None) or getattr(item, 'seasonIndex', None) or 0)
    episode = int(getattr(item, 'index', None) or 0)
    return f'S{season:02d}E{episode:02d}'


def item_folder(backups, library, item):
    root = Path(backups.backup_dir) / library
    if item.type == 'episode':
        return root / show_backup_id(item) / episode_code(item)
    return root / backup_id(item)


def _safe_title(title):
    return ''.join(c for c in (title or '') if c.isalnum() or c in (' ', '-', '_')).strip()


def _legacy_candidates(backups, library, item):
    """(original, overlay, metadata) locations used before backups were keyed by ID."""
    root = Path(backups.backup_dir) / library
    if item.type == 'episode':
        series = _safe_title(getattr(item, 'grandparentTitle', None)
                             or getattr(item, 'parentTitle', None) or 'Unknown Series')
        year = getattr(item, 'grandparentYear', None)
        prefix = episode_code(item) + '-poster_'
        folders = [root / f'{series} ({year})'] if year else []
        for folder in folders + [root / series]:
            yield folder / (prefix + 'original.jpg'), folder / (prefix + 'overlay.jpg'), None
        legacy = root / 'episodes' / str(item.ratingKey)
        yield legacy / 'original.jpg', legacy / 'overlay.jpg', None
    else:
        title, year = _safe_title(item.title), getattr(item, 'year', None)
        folders = [root / f'{title} ({year})'] if year else []
        for folder in folders + [root / title]:
            yield folder / 'poster_original.jpg', folder / 'poster_overlay.jpg', folder / METADATA


def _belongs_to(metadata_file, item):
    """A title folder may belong to a same-named item; trust its recorded rating key."""
    if metadata_file is None or not metadata_file.is_file():
        return True
    try:
        recorded = json.loads(metadata_file.read_text()).get('rating_key')
    except (OSError, ValueError):
        return True
    return recorded is None or str(recorded) == str(item.ratingKey)


def migrate_legacy(backups, library, item, folder=None):
    """Move an old title/year backup into the ID folder. Never overwrites or deletes images."""
    folder = folder or item_folder(backups, library, item)
    if (folder / ORIGINAL).exists():
        return False
    for original, overlay, metadata in _legacy_candidates(backups, library, item):
        if not original.is_file() or not _belongs_to(metadata, item):
            continue
        folder.mkdir(parents=True, exist_ok=True)
        os.replace(original, folder / ORIGINAL)
        for source, name in ((overlay, OVERLAY), (metadata, METADATA)):
            if source is not None and source.is_file() and not (folder / name).exists():
                os.replace(source, folder / name)
        try:
            original.parent.rmdir()  # only succeeds once the old folder is empty
        except OSError:
            pass
        logger.info('Migrated backup %s → %s', original.parent, folder)
        return True
    return False


def paths(backups, library, item):
    """(original, overlay) for an item; migrates an old backup on first access."""
    folder = item_folder(backups, library, item)
    try:
        migrate_legacy(backups, library, item, folder)
    except OSError:
        logger.exception('Could not migrate legacy backup for %s', item.ratingKey)
    return folder / ORIGINAL, folder / OVERLAY


def write_metadata(backups, library, item, **extra):
    folder = item_folder(backups, library, item)
    folder.mkdir(parents=True, exist_ok=True)
    data = {'rating_key': str(item.ratingKey), 'title': item.title, 'type': item.type,
            'year': getattr(item, 'year', None), 'ids': external_ids(item), **extra}
    if item.type == 'episode':
        data.update(series=getattr(item, 'grandparentTitle', None), episode=episode_code(item))
    (folder / METADATA).write_text(json.dumps(data, indent=2, default=str))


def replace_image(destination, content):
    """Validate before replacing an existing original; preserve it on failure."""
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=destination.parent, prefix='.poster-',
                                         suffix='.jpg', delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(content)
        with Image.open(temporary) as image:
            image.verify()
        os.replace(temporary, destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def capture_plex(backups, library, item, server, token):
    """Cache exactly the currently selected artwork, keeping old backup on error."""
    source = getattr(item, 'thumb', None) if item.type == 'episode' else getattr(item, 'posterUrl', None)
    if not source:
        raise ValueError(f'No Plex artwork for {item.ratingKey}')
    url = server.url(source) if source.startswith('/') else source
    response = server._session.get(url, headers={'X-Plex-Token': token}, timeout=30)
    response.raise_for_status()
    original, overlay = paths(backups, library, item)
    replace_image(original, response.content)
    overlay.unlink(missing_ok=True)
    write_metadata(backups, library, item)
    return original
