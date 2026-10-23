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

    def test_kometa_check_for_selection(self):
        self.assertEqual(sorted(self.index.kometa_keys('Filme', ['1', '2', '3', '4'])), ['3', '4'])
        # a selected season stands for its episodes
        self.assertEqual(self.index.kometa_keys('Serien', ['21']), ['23'])
        self.assertEqual(self.index.kometa_keys('Serien', []), [])

    def test_result_filter_keeps_path_to_touched_items(self):
        related = self.index.related_keys('Serien', ['23'])
        self.assertEqual(related, {'23', '21', '20'})
        self.assertEqual([e['key'] for e in self.index.browse('Serien', only_keys=related)['items']], ['20'])
        self.assertEqual([e['key'] for e in self.index.browse('Serien', parent_key=20, only_keys=related)['items']], ['21'])
        self.assertEqual([e['key'] for e in self.index.browse('Serien', parent_key=21, only_keys=related)['items']], ['23'])
        # a selected season stands for its episodes
        self.assertEqual(self.index.related_keys('Serien', ['21']), {'21', '22', '23', '20'})

    def test_describe_and_ancestors(self):
        self.assertEqual([row['library'] for row in self.index.describe(['23', '2', 'x'])], ['Serien', 'Filme'])
        self.assertEqual([entry['key'] for entry in self.index.ancestors('Serien', '23')], ['20', '21'])
        self.assertEqual(self.index.ancestors('Filme', '2'), [])

    def test_task_outcomes_collect_selection_results_and_kometa(self):
        from src.services.library_index import task_outcomes
        task = {'payload': {'library_name': 'Serien', 'rating_keys': ['21']},
                'progress': {'failed_keys': ['22'], 'kometa_keys': {'Serien': ['23']}},
                'results': {'22': 'kein Poster'}}
        self.assertEqual(task_outcomes(task), {'21': None, '22': 'kein Poster', '23': 'Kometa erkannt'})
        imdb = {'payload': {'library': 'Filme', 'request': {'rating_keys': ['2']}},
                'results': [{'key': '2', 'render': 'gerendert'}]}
        self.assertEqual(task_outcomes(imdb), {'2': 'gerendert'})

    def test_errors_only_lists_failed_items_and_their_path(self):
        from src.rating_overlay.item_state import ItemState
        self.assertEqual(self.index.browse('Serien', errors_only=True)['items'], [])  # no state table yet
        with ItemState(Path(self.folder) / 'index.db') as store:
            store.update('Serien', '23', status='failed', reason='Kein Poster in Plex')
            store.update('Serien', '22', status='skipped', reason='Kometa-Konflikt: übersprungen')
            store.update('Filme', '2', status='failed', reason='Keine TMDB- oder IMDb-ID')
            store.update('Filme', '1', status='rendered')
        keys = lambda library, **kw: [e['key'] for e in self.index.browse(library, errors_only=True, **kw)['items']]
        self.assertEqual(keys('Filme'), ['2'])
        self.assertEqual(keys('Serien'), ['20'])
        self.assertEqual(keys('Serien', parent_key=20), ['21'])
        self.assertEqual(keys('Serien', parent_key=21), ['23'])
        self.assertEqual(keys('Serien', episodes=True), ['23'])
        self.assertEqual(self.index.errors('Serien', ['22', '23']), {'23': 'Kein Poster in Plex'})

    def test_skip_reasons_that_are_errors(self):
        from src.rating_overlay.decision import item_status
        self.assertEqual(item_status('skipped', 'kein sauberes Agent-Poster gefunden'), 'failed')
        self.assertEqual(item_status('failed', 'Keine TMDB- oder IMDb-ID'), 'failed')
        self.assertEqual(item_status('skipped', 'Kometa-Konflikt: Reset erforderlich'), 'skipped')
        self.assertEqual(item_status('skipped', 'wartet auf manuelles Plex-Poster'), 'skipped')


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
