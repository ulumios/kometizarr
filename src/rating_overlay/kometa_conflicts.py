"""Safeguards for media still carrying Kometa's Plex Overlay label."""

import json
import os
from pathlib import Path


def has_overlay_label(item):
    return any(getattr(label, 'tag', None) == 'Overlay' for label in (getattr(item, 'labels', None) or []))


def has_kometizarr_overlay(backups, library_name, item):
    if item.type == 'episode':
        return (backups.backup_dir / library_name / 'episodes' / str(item.ratingKey) / 'overlay.jpg').is_file()
    return backups.has_overlay(library_name, item.title, year=getattr(item, 'year', None))


def select_agent_poster(item):
    """Pick a Plex agent poster; never reuse one of the uploaded overlay posters."""
    original = next((poster for poster in item.posters()
                     if all('upload' not in str(getattr(poster, attr, '') or '').lower()
                            for attr in ('ratingKey', 'provider', 'key'))), None)
    if original is None:
        return False
    original.select()
    item.reload()
    return True


class ManualPosterQueue:
    """Keep items out of processing after their label is removed until artwork changes."""

    def __init__(self, path='/backups/kometa_manual_pending.json'):
        self.path = Path(path)

    def _read(self):
        try:
            return json.loads(self.path.read_text())
        except (OSError, ValueError):
            return {}

    def _write(self, data):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix('.tmp')
        temp.write_text(json.dumps(data))
        os.replace(temp, self.path)

    @staticmethod
    def _key(library, item):
        return f'{library}:{item.ratingKey}'

    @staticmethod
    def _poster_identity(item):
        selected = next((poster for poster in item.posters() if getattr(poster, 'selected', False)), None)
        return {'thumb': getattr(item, 'thumb', None),
                'poster': getattr(selected, 'ratingKey', None) if selected else None}

    def mark(self, library, item):
        data = self._read()
        data[self._key(library, item)] = self._poster_identity(item)
        self._write(data)

    def remove(self, library, item):
        data = self._read()
        if self._key(library, item) in data:
            data.pop(self._key(library, item))
            self._write(data)

    def state(self, library, item):
        data = self._read()
        key = self._key(library, item)
        if key not in data:
            return 'none'
        if data[key] != self._poster_identity(item):
            return 'changed'
        return 'waiting'

    def is_pending(self, library, item):
        return self.state(library, item) == 'waiting'

    def keys(self, library):
        prefix = f'{library}:'
        return [key[len(prefix):] for key in self._read() if key.startswith(prefix)]
