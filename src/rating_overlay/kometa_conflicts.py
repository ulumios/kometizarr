"""Safeguards for media still carrying Kometa's Plex Overlay label."""

import json

from src.rating_overlay.data_paths import data_file

# Kometa marks every item whose poster it overlaid with this Plex label.
KOMETA_LABEL = 'Overlay'


def has_overlay_label(item):
    return any(getattr(label, 'tag', None) == KOMETA_LABEL for label in (getattr(item, 'labels', None) or []))


def remove_overlay_label(item):
    """Hand the item over from Kometa to Kometizarr; returns True if a label was removed."""
    if not has_overlay_label(item):
        return False
    item.removeLabel(KOMETA_LABEL)
    return True


def has_kometizarr_overlay(backups, library_name, item):
    return backups.has_overlay(library_name, item)


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
    """Keep items out of processing after their label is removed until artwork changes.

    Stored as ``kometa_state='manual_pending'`` in item_state."""

    def __init__(self, path=None):
        self.path = path or data_file('media_index.sqlite3')

    def _store(self):
        from src.rating_overlay.item_state import ItemState
        return ItemState(self.path)

    @staticmethod
    def _poster_identity(item):
        selected = next((poster for poster in item.posters() if getattr(poster, 'selected', False)), None)
        return {'thumb': getattr(item, 'thumb', None),
                'poster': getattr(selected, 'ratingKey', None) if selected else None}

    def mark(self, library, item):
        with self._store() as store:
            store.update(library, item, kometa_state='manual_pending',
                         manual_identity=self._poster_identity(item))

    def remove(self, library, item):
        with self._store() as store:
            row = store.get(library, item.ratingKey)
            if row and row['kometa_state'] == 'manual_pending':
                store.update(library, item.ratingKey, kometa_state='none', manual_identity=None)

    def state(self, library, item):
        with self._store() as store:
            row = store.get(library, item.ratingKey)
        if not row or row['kometa_state'] != 'manual_pending':
            return 'none'
        if json.loads(row['manual_identity'] or '{}') != self._poster_identity(item):
            return 'changed'
        return 'waiting'

    def is_pending(self, library, item):
        return self.state(library, item) == 'waiting'

    def keys(self, library):
        with self._store() as store:
            return store.keys(library, kometa_state='manual_pending')
