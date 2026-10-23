import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from src.rating_overlay.api_cache import ApiCache
from src.rating_overlay.plex_poster_manager import PlexPosterManager


def stream(code):
    return SimpleNamespace(streamType=2, languageCode=code)


class Episode:
    """Like a Plex episode listed for a whole library: parts without streams until reload()."""
    def __init__(self, size, codes):
        self.title, self.size, self.codes, self.reloads = 'Pilot', size, codes, 0
        self.media = [SimpleNamespace(parts=[SimpleNamespace(id=7, size=size, file='/tv/a.mkv', streams=[])])]

    def reload(self):
        self.reloads += 1
        self.media = [SimpleNamespace(parts=[SimpleNamespace(
            id=7, size=self.size, file='/tv/a.mkv', streams=[stream(code) for code in self.codes])])]


class EpisodeLanguagesTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.cache = ApiCache(Path(self.folder.name) / 'c.db')
        self.manager = PlexPosterManager.__new__(PlexPosterManager)
        self.manager.rating_fetcher = SimpleNamespace(cache=self.cache)

    def tearDown(self):
        self.cache.close()
        self.folder.cleanup()

    def test_loads_streams_once_per_file(self):
        first = Episode(100, ['ger', 'eng'])
        self.assertEqual([code for code, _ in self.manager.episode_languages(first)], ['DE', 'EN'])
        again = Episode(100, ['ger', 'eng'])
        self.assertEqual([code for code, _ in self.manager.episode_languages(again)], ['DE', 'EN'])
        self.assertEqual((first.reloads, again.reloads), (1, 0))

    def test_replaced_file_is_read_anew(self):
        self.manager.episode_languages(Episode(100, ['eng']))
        upgraded = Episode(250, ['ger', 'eng'])
        self.assertEqual([code for code, _ in self.manager.episode_languages(upgraded)], ['DE', 'EN'])
        self.assertEqual(upgraded.reloads, 1)

    def test_full_item_needs_no_reload_and_unanalysed_file_is_not_remembered(self):
        full = Episode(100, ['jpn'])
        full.reload()
        self.assertEqual([code for code, _ in self.manager.episode_languages(full)], ['JA'])
        self.assertEqual(full.reloads, 1)
        pending = Episode(300, [])
        self.assertEqual(self.manager.episode_languages(pending), [])
        self.assertIsNone(self.cache.lookup('audio:7:300:/tv/a.mkv'))


if __name__ == '__main__':
    unittest.main()
