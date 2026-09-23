"""Shared paths and safe replacement of Plex artwork backups."""

import os
import tempfile
from pathlib import Path

from PIL import Image


def paths(backups, library, item):
    if item.type == 'episode':
        title = (getattr(item, 'grandparentTitle', None)
                 or getattr(item, 'parentTitle', None) or 'Unknown Series')
        folder = backups._get_backup_path(library, title,
                                          year=getattr(item, 'grandparentYear', None))
        season = int(getattr(item, 'parentIndex', None)
                     or getattr(item, 'seasonIndex', None) or 0)
        episode = int(getattr(item, 'index', None) or 0)
        prefix = f'S{season:02d}E{episode:02d}-poster_'
    else:
        folder = backups._get_backup_path(library, item.title,
                                          year=getattr(item, 'year', None))
        prefix = 'poster_'
    return folder / (prefix + 'original.jpg'), folder / (prefix + 'overlay.jpg')


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
    return original
