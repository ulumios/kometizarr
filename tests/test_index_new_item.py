import sys
import types

from src.services import library_index


class Item:
    def __init__(self, kind, key, parent_key=None, parent=None):
        self.TYPE, self.ratingKey, self.parentRatingKey, self._up = kind, key, parent_key, parent

    def season(self):
        assert self.TYPE == 'episode'
        return self._up

    def show(self):
        assert self.TYPE == 'season'
        return self._up


class FakeIndex:
    known, written = set(), []

    def snapshot(self, library, kind):
        return ['x'], None

    def has_item(self, library, key):
        return key in self.known

    def upsert_item(self, library, item, **flags):
        self.written.append(item.ratingKey)

    def close(self):
        pass


def run(monkeypatch, known):
    FakeIndex.known, FakeIndex.written = set(known), []
    monkeypatch.setitem(sys.modules, 'src.rating_overlay.media_index', types.SimpleNamespace(MediaIndex=FakeIndex))
    monkeypatch.setitem(sys.modules, 'src.rating_overlay.kometa_conflicts', types.SimpleNamespace(has_overlay_label=lambda item: False))
    show = Item('show', 's')
    season = Item('season', 'se', 's', show)
    library_index.index_new_item('Serien', Item('episode', 'e', 'se', season))
    return FakeIndex.written


def test_new_episode_adds_missing_season_and_show(monkeypatch):
    assert run(monkeypatch, []) == ['s', 'se', 'e']


def test_new_episode_in_known_season(monkeypatch):
    assert run(monkeypatch, ['se']) == ['e']


def test_new_season_of_known_show(monkeypatch):
    assert run(monkeypatch, ['s']) == ['se', 'e']
