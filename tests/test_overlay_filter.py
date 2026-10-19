import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src.rating_overlay.media_index import MediaIndex
from src.services import config, library_index


def item(key, kind, title, parent=None, **extra):
    return SimpleNamespace(ratingKey=key, type=kind, title=title, parentRatingKey=parent, year=2000,
                           index=extra.pop('index', None), thumb=None, guids=[], **extra)


class OverlayFilterTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.index = MediaIndex(Path(self.folder) / 'index.db')
        self.movies = [item(1, 'movie', 'Mit Overlay'), item(2, 'movie', 'Ohne Overlay'),
                       item(3, 'movie', 'Kometa'), item(4, 'movie', 'Konflikt')]
        flags = {1: (1, 0), 2: (0, 0), 3: (0, 1), 4: (0, 0)}
        self.index.replace_library('Filme', self.movies, flags=lambda i: flags[i.ratingKey])
        self.index.record_conflict('Filme', self.movies[3], {'key': '4'})
        self.shows = [item(10, 'show', 'Fertig'), item(11, 'season', 'Staffel 1', parent=10, index=1),
                      item(12, 'episode', 'Pilot', parent=11, index=1, grandparentTitle='Fertig', parentIndex=1),
                      item(20, 'show', 'Offen'), item(21, 'season', 'Staffel 1', parent=20, index=1),
                      item(22, 'episode', 'Neu', parent=21, index=1, grandparentTitle='Offen', parentIndex=1),
                      item(23, 'episode', 'Kometa-Folge', parent=21, index=2, grandparentTitle='Offen', parentIndex=1)]
        show_flags = {10: (1, 0), 11: (None, None), 12: (1, 0), 20: (1, 0), 21: (None, None), 22: (0, 0), 23: (0, 1)}
        self.index.replace_library('Serien', self.shows, flags=lambda i: show_flags[i.ratingKey])

    def tearDown(self):
        self.index.close()

    def keys(self, library, **kw):
        return [entry['key'] for entry in self.index.browse(library, missing_overlay=True, **kw)['items']]

    def test_movies_without_overlay_hide_kometa(self):
        self.assertEqual(self.keys('Filme'), ['2'])
        self.assertTrue(self.index.flags_ready('Filme'))

    def test_shows_listed_through_episodes_without_overlay(self):
        self.assertEqual(self.keys('Serien'), ['20'])
        self.assertEqual(self.keys('Serien', parent_key=20), ['21'])
        self.assertEqual(self.keys('Serien', parent_key=21), ['22'])
        self.assertEqual(self.keys('Serien', episodes=True), ['22'])

    def test_flags_follow_renders(self):
        self.index.set_flags('Filme', 2, has_overlay=True)
        self.assertEqual(self.keys('Filme'), [])
        self.index.set_flags('Filme', 1, has_overlay=False)
        self.assertEqual(self.keys('Filme'), ['1'])


class ScanFlagsTest(unittest.TestCase):
    def test_scan_reads_overlay_files_and_label_search(self):
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / 'Filme' / 'tt1').mkdir(parents=True)
            (Path(folder) / 'Filme' / 'tt1' / 'overlay.jpg').write_bytes(b'x')
            done = SimpleNamespace(ratingKey=1, type='movie', title='A', year=1, guids=[SimpleNamespace(id='imdb://tt1')])
            kometa = SimpleNamespace(ratingKey=2, type='movie', title='B', year=1, guids=[])
            library = SimpleNamespace(type='movie', search=lambda libtype, label: [kometa])
            with patch.object(config, 'BACKUP_DIR', Path(folder)):
                flags = library_index.overlay_flags(library, 'Filme', [None])
                self.assertEqual(flags(done), (1, 0))
                self.assertEqual(flags(kometa), (0, 1))


if __name__ == '__main__':
    unittest.main()
