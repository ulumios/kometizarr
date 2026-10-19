"""Read-only access to the clean posters Kometa keeps before drawing its overlays.

Kometa stores them as ``<config>/overlays/<library> Original Posters/<ratingKey>.<ext>``.
Mount Kometa's config folder (or just its ``overlays`` folder) read-only to use them."""

import io
from pathlib import Path

from PIL import Image

EXTENSIONS = ('.jpg', '.jpeg', '.png', '.webp')


def overlays_dir(settings):
    configured = ((settings or {}).get('kometa') or {}).get('originals_dir')
    for candidate in ([configured] if configured else []) + ['/kometa/overlays', '/kometa/config/overlays']:
        if candidate and Path(candidate).is_dir():
            return Path(candidate)
    return None


def find_original(settings, library, rating_key):
    base = overlays_dir(settings)
    if base is None:
        return None
    name = (((settings or {}).get('kometa') or {}).get('library_map') or {}).get(library) or library
    folder = base / f'{name} Original Posters'
    for extension in EXTENSIONS:
        path = folder / f'{rating_key}{extension}'
        if path.is_file():
            return path
    return None


def as_jpeg(path):
    """Kometa keeps PNG/WEBP as well; backups are always JPEG."""
    with Image.open(path) as image:
        data = io.BytesIO()
        image.convert('RGB').save(data, 'JPEG', quality=95)
        return data.getvalue()
